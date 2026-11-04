from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from statistics import fmean
from zoneinfo import ZoneInfo

from tradinggpt_options.data.models import MarketCandle
from tradinggpt_options.options.chain_analytics import (
    OptionChainView,
    OptionLegAnalytics,
)
from tradinggpt_options.research.decisions import TradeDecision

MARKET_TIMEZONE = ZoneInfo("Asia/Kolkata")
MODEL_VERSION = "baseline-ema-vwap-rsi-v1"


@dataclass(frozen=True, slots=True)
class BaselineStrategyConfig:
    minimum_candles: int = 30
    max_candle_age_seconds: int = 600
    max_chain_age_seconds: int = 15
    minimum_confidence_score: float = 65.0
    maximum_spread_percent: float = 2.5
    minimum_option_volume: int = 100
    minimum_open_interest: int = 1000
    minimum_delta_abs: float = 0.40
    maximum_delta_abs: float = 0.65

    def __post_init__(self) -> None:
        if self.minimum_candles < 25:
            raise ValueError("minimum_candles must be at least 25")
        if self.max_candle_age_seconds < 1 or self.max_chain_age_seconds < 1:
            raise ValueError("freshness limits must be positive")
        if (
            not isfinite(self.minimum_confidence_score)
            or not 0 <= self.minimum_confidence_score <= 100
        ):
            raise ValueError("minimum_confidence_score must be finite and in [0, 100]")
        if (
            not isfinite(self.maximum_spread_percent)
            or self.maximum_spread_percent <= 0
        ):
            raise ValueError("maximum_spread_percent must be finite and positive")
        if self.minimum_option_volume < 0 or self.minimum_open_interest < 0:
            raise ValueError("minimum volume and OI cannot be negative")
        if (
            not isfinite(self.minimum_delta_abs)
            or not isfinite(self.maximum_delta_abs)
            or not 0 < self.minimum_delta_abs <= self.maximum_delta_abs <= 1
        ):
            raise ValueError("delta bounds must satisfy 0 < min <= max <= 1")


@dataclass(frozen=True, slots=True)
class UnderlyingIndicators:
    close: float
    ema_9: float
    ema_21: float
    rsi_14: float
    vwap_session: float
    atr_14: float
    volume_ratio: float


@dataclass(frozen=True, slots=True)
class BaselineAnalysis:
    decision: TradeDecision
    candidate: OptionLegAnalytics | None
    indicators: UnderlyingIndicators | None
    warnings: tuple[str, ...]


def _ema(values: Sequence[float], period: int) -> float:
    alpha = 2.0 / (period + 1.0)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def _rsi(values: Sequence[float], period: int = 14) -> float:
    changes = [current - previous for previous, current in zip(values, values[1:])]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = fmean(gains[:period])
    average_loss = fmean(losses[:period])
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _atr(candles: Sequence[MarketCandle], period: int = 14) -> float:
    true_ranges: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        high = float(candle.high)
        low = float(candle.low)
        close = float(candle.close)
        true_range = high - low
        if previous_close is not None:
            true_range = max(
                true_range,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        true_ranges.append(true_range)
        previous_close = close
    return fmean(true_ranges[-period:])


def _indicators(candles: Sequence[MarketCandle]) -> UnderlyingIndicators:
    closes = [float(candle.close) for candle in candles]
    latest_day = candles[-1].timestamp.astimezone(MARKET_TIMEZONE).date()
    session = [
        candle
        for candle in candles
        if candle.timestamp.astimezone(MARKET_TIMEZONE).date() == latest_day
    ]
    volume_sum = sum(candle.volume for candle in session)
    if volume_sum <= 0:
        raise ValueError("current session has no positive traded volume")
    vwap = sum(
        (
            (float(candle.high) + float(candle.low) + float(candle.close))
            / 3.0
        ) * candle.volume
        for candle in session
    ) / volume_sum
    prior_volumes = [candle.volume for candle in candles[-21:-1]]
    average_volume = fmean(prior_volumes) if prior_volumes else 0.0
    volume_ratio = (
        candles[-1].volume / average_volume if average_volume > 0 else 0.0
    )
    return UnderlyingIndicators(
        close=closes[-1],
        ema_9=_ema(closes[-30:], 9),
        ema_21=_ema(closes[-30:], 21),
        rsi_14=_rsi(closes[-30:], 14),
        vwap_session=vwap,
        atr_14=_atr(candles[-30:], 14),
        volume_ratio=volume_ratio,
    )


def _score(indicators: UnderlyingIndicators, direction: str) -> float:
    atr = max(indicators.atr_14, 1e-9)
    trend_strength = min(
        1.0,
        abs(indicators.ema_9 - indicators.ema_21) / atr,
    )
    vwap_strength = min(
        1.0,
        abs(indicators.close - indicators.vwap_session) / atr,
    )
    volume_strength = min(1.0, indicators.volume_ratio / 1.5)
    rsi_strength = (
        min(1.0, max(0.0, (indicators.rsi_14 - 50.0) / 20.0))
        if direction == "BULLISH"
        else min(1.0, max(0.0, (50.0 - indicators.rsi_14) / 20.0))
    )
    score = (
        45.0
        + 15.0 * trend_strength
        + 15.0 * vwap_strength
        + 10.0 * volume_strength
        + 15.0 * rsi_strength
    )
    return round(min(100.0, max(0.0, score)), 1)


def _select_candidate(
    chain: OptionChainView,
    *,
    option_type: str,
    config: BaselineStrategyConfig,
) -> OptionLegAnalytics | None:
    target_delta = 0.50 if option_type == "CE" else -0.50
    candidates: list[tuple[float, OptionLegAnalytics]] = []
    for row in chain.strikes:
        leg = row.call if option_type == "CE" else row.put
        if leg is None or leg.greeks is None or leg.mid_price is None:
            continue
        if leg.quality_flags:
            continue
        if leg.spread_percent is None or float(leg.spread_percent) > config.maximum_spread_percent:
            continue
        if (leg.volume or 0) < config.minimum_option_volume:
            continue
        if (leg.open_interest or 0) < config.minimum_open_interest:
            continue
        delta = leg.greeks.delta
        if option_type == "CE" and delta <= 0:
            continue
        if option_type == "PE" and delta >= 0:
            continue
        delta_abs = abs(delta)
        if not config.minimum_delta_abs <= delta_abs <= config.maximum_delta_abs:
            continue
        rank = abs(delta - target_delta) + float(leg.spread_percent) / 100.0
        candidates.append((rank, leg))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def analyze_baseline(
    candles: Sequence[MarketCandle],
    chain: OptionChainView,
    *,
    now: datetime,
    config: BaselineStrategyConfig | None = None,
) -> BaselineAnalysis:
    """Explainable EMA/VWAP/RSI baseline; heuristic score is not win probability."""
    settings = config or BaselineStrategyConfig()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if len(candles) < settings.minimum_candles:
        return BaselineAnalysis(
            TradeDecision(
                chain.underlying,
                "NO_TRADE",
                None,
                None,
                ("insufficient underlying candle history",),
                (),
                MODEL_VERSION,
            ),
            None,
            None,
            ("minimum candle sample not met",),
        )
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    identities = {
        (candle.exchange, candle.tradingsymbol, candle.interval)
        for candle in ordered
    }
    if len(identities) != 1:
        raise ValueError("all candles must belong to one instrument and interval")
    timestamps = [candle.timestamp for candle in ordered]
    if len(set(timestamps)) != len(timestamps):
        raise ValueError("underlying candles contain duplicate timestamps")
    latest = ordered[-1]
    age_seconds = (now.astimezone(UTC) - latest.timestamp.astimezone(UTC)).total_seconds()
    if age_seconds < -5 or age_seconds > settings.max_candle_age_seconds:
        return BaselineAnalysis(
            TradeDecision(
                chain.underlying,
                "NO_TRADE",
                None,
                None,
                ("latest underlying candle is stale or timestamped in the future",),
                (),
                MODEL_VERSION,
            ),
            None,
            None,
            ("underlying candle freshness check failed",),
        )
    chain_age = (
        now.astimezone(UTC) - chain.snapshot_at.astimezone(UTC)
    ).total_seconds()
    if chain_age < -5 or chain_age > settings.max_chain_age_seconds:
        return BaselineAnalysis(
            TradeDecision(
                chain.underlying,
                "NO_TRADE",
                None,
                None,
                ("option chain snapshot is stale or timestamped in the future",),
                (),
                MODEL_VERSION,
            ),
            None,
            None,
            ("option chain freshness check failed",),
        )

    try:
        indicators = _indicators(ordered[-30:])
    except ValueError as exc:
        return BaselineAnalysis(
            TradeDecision(
                chain.underlying,
                "NO_TRADE",
                None,
                None,
                (str(exc),),
                (),
                MODEL_VERSION,
            ),
            None,
            None,
            ("indicator calculation could not be completed",),
        )
    if not all(
        isfinite(value)
        for value in (
            indicators.close,
            indicators.ema_9,
            indicators.ema_21,
            indicators.rsi_14,
            indicators.vwap_session,
            indicators.atr_14,
            indicators.volume_ratio,
        )
    ) or indicators.atr_14 <= 0:
        return BaselineAnalysis(
            TradeDecision(
                chain.underlying,
                "NO_TRADE",
                None,
                None,
                ("indicator inputs are invalid or ATR is zero",),
                (),
                MODEL_VERSION,
            ),
            None,
            indicators,
            ("indicator validation failed",),
        )

    bullish = (
        indicators.ema_9 > indicators.ema_21
        and indicators.close > indicators.vwap_session
        and 52.0 <= indicators.rsi_14 <= 70.0
        and indicators.volume_ratio >= 0.8
    )
    bearish = (
        indicators.ema_9 < indicators.ema_21
        and indicators.close < indicators.vwap_session
        and 30.0 <= indicators.rsi_14 <= 48.0
        and indicators.volume_ratio >= 0.8
    )
    if bullish == bearish:
        rationale = (
            "EMA/VWAP/RSI/volume conditions do not agree on one direction",
        )
        return BaselineAnalysis(
            TradeDecision(
                chain.underlying,
                "NO_TRADE",
                None,
                None,
                rationale,
                (),
                MODEL_VERSION,
            ),
            None,
            indicators,
            ("baseline has no directional edge",),
        )

    direction = "BULLISH" if bullish else "BEARISH"
    option_type = "CE" if bullish else "PE"
    score = _score(indicators, direction)
    if score < settings.minimum_confidence_score:
        return BaselineAnalysis(
            TradeDecision(
                chain.underlying,
                "NO_TRADE",
                score,
                None,
                (f"{direction.lower()} score below configured threshold",),
                (),
                MODEL_VERSION,
            ),
            None,
            indicators,
            ("heuristic score is below threshold; score is not a probability",),
        )

    candidate = _select_candidate(
        chain,
        option_type=option_type,
        config=settings,
    )
    if candidate is None:
        return BaselineAnalysis(
            TradeDecision(
                chain.underlying,
                "NO_TRADE",
                score,
                None,
                (f"no liquid {option_type} contract passed delta/spread/OI/volume filters",),
                (),
                MODEL_VERSION,
            ),
            None,
            indicators,
            ("no option contract passed liquidity and quote-quality filters",),
        )

    rationale = (
        f"{direction.lower()} trend: EMA9 is {'above' if bullish else 'below'} EMA21",
        f"underlying close is {'above' if bullish else 'below'} session VWAP",
        f"RSI14={indicators.rsi_14:.1f}; volume ratio={indicators.volume_ratio:.2f}",
        "selected option delta/spread/OI/volume passed configured filters",
    )
    warnings = (
        "heuristic confidence score is not a calibrated win probability",
        "news, scheduled events and broader market breadth are not integrated",
    )
    return BaselineAnalysis(
        TradeDecision(
            chain.underlying,
            option_type,
            score,
            None,
            rationale,
            (),
            MODEL_VERSION,
        ),
        candidate,
        indicators,
        warnings,
    )
