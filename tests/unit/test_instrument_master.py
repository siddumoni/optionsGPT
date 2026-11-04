from tradinggpt_options.data.instrument_master import (
    parse_kite_futures_instruments,
    parse_kite_instruments,
)

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


def test_infers_index_underlying_when_kite_name_column_is_blank() -> None:
    rows = [
        "201,1,NIFTY26NOV25000CE,,0,2026-11-26,25000,0.05,65,CE,NFO-OPT,NFO",
        "202,2,BANKNIFTY26NOV56000PE,,0,2026-11-26,56000,0.05,30,PE,NFO-OPT,NFO",
        "203,3,FINNIFTY26NOV26000CE,,0,2026-11-26,26000,0.05,60,CE,NFO-OPT,NFO",
        "204,4,MIDCPNIFTY26NOV13000PE,,0,2026-11-26,13000,0.05,120,PE,NFO-OPT,NFO",
        "205,5,NIFTYNXT5026NOV70000CE,,0,2026-11-26,70000,0.05,25,CE,NFO-OPT,NFO",
    ]
    result = parse_kite_instruments(HEADER + "\n".join(rows) + "\n")
    assert {item.underlying for item in result.contracts} == {
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "NIFTYNXT50",
    }
    assert result.rejected_rows == 0


def test_rejects_blank_name_for_unrecognized_index_or_stock_symbol() -> None:
    row = (
        "206,6,UNKNOWN26NOV100CE,,0,2026-11-26,100,0.05,1,CE,NFO-OPT,NFO\n"
    )
    result = parse_kite_instruments(HEADER + row)
    assert result.contracts == ()
    assert result.rejected_rows == 1


def test_parses_nearest_expiry_nfo_futures_with_blank_index_names() -> None:
    rows = [
        "301,1,NIFTY26NOVFUT,,0,2026-11-26,0,0.05,65,FUT,NFO-FUT,NFO",
        "302,2,BANKNIFTY26NOVFUT,,0,2026-11-26,0,0.05,30,FUT,NFO-FUT,NFO",
        "303,3,RELIANCE26NOVFUT,RELIANCE,0,2026-11-26,0,0.05,250,FUT,NFO-FUT,NFO",
    ]
    result = parse_kite_futures_instruments(HEADER + "\n".join(rows) + "\n")
    assert len(result.contracts) == 3
    assert {item.underlying for item in result.contracts} == {
        "NIFTY",
        "BANKNIFTY",
        "RELIANCE",
    }
    assert result.rejected_rows == 0
