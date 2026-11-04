from tradinggpt_options.data.instrument_master import parse_kite_instruments

HEADER = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,"
    "expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
)


def test_parses_only_option_contracts_and_filters_underlying() -> None:
    data = HEADER + (
        "123,1,NIFTY26NOV25000CE,NIFTY,0,2026-11-26,25000,0.05,65,CE,NFO-OPT,NFO\n"
        "124,2,NIFTY26NOV25000PE,NIFTY,0,2026-11-26,25000,0.05,65,PE,NFO-OPT,NFO\n"
        "125,3,INFY,INFY,0,,,0.05,1,EQ,NSE,NSE\n"
    )
    result = parse_kite_instruments(data, underlyings={"NIFTY"})
    assert len(result.contracts) == 2
    assert {contract.option_type for contract in result.contracts} == {"CE", "PE"}
    assert result.rejected_rows == 0


def test_rejects_duplicate_exchange_symbol() -> None:
    line = (
        "123,1,NIFTY26NOV25000CE,NIFTY,0,2026-11-26,"
        "25000,0.05,65,CE,NFO-OPT,NFO\n"
    )
    result = parse_kite_instruments(HEADER + line + line)
    assert len(result.contracts) == 1
    assert result.rejected_rows == 1


def test_rejects_option_row_without_expiry() -> None:
    line = (
        "126,4,NIFTY26NOV25000CE,NIFTY,0,,25000,0.05,65,CE,NFO-OPT,NFO\\n"
    )
    result = parse_kite_instruments(HEADER + line)
    assert result.contracts == ()
    assert result.rejected_rows == 1
