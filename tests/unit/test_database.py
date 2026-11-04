from sqlalchemy import create_engine, inspect, text

from tradinggpt_options.storage.database import create_schema


def test_create_schema_adds_quote_depth_columns_to_legacy_sqlite_database() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE paper_trades (
                    id VARCHAR(36) PRIMARY KEY,
                    account_id INTEGER,
                    exchange VARCHAR(12),
                    tradingsymbol VARCHAR(64),
                    underlying VARCHAR(64),
                    expiry DATE,
                    strike NUMERIC(18, 4),
                    option_type VARCHAR(2),
                    lot_size INTEGER,
                    quantity INTEGER,
                    entry_premium NUMERIC(18, 4),
                    exit_premium NUMERIC(18, 4),
                    entry_at DATETIME,
                    exit_at DATETIME,
                    status VARCHAR(16),
                    gross_pnl NUMERIC(18, 2),
                    charges NUMERIC(18, 2),
                    net_pnl NUMERIC(18, 2),
                    entry_reason VARCHAR(2048),
                    exit_reason VARCHAR(2048)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE quote_snapshots (
                    id INTEGER PRIMARY KEY,
                    exchange VARCHAR(12),
                    tradingsymbol VARCHAR(64),
                    instrument_token INTEGER,
                    exchange_timestamp DATETIME,
                    received_at DATETIME,
                    last_price NUMERIC(18, 4),
                    best_bid NUMERIC(18, 4),
                    best_ask NUMERIC(18, 4),
                    bid_quantity INTEGER,
                    ask_quantity INTEGER,
                    volume INTEGER,
                    open_interest INTEGER,
                    source VARCHAR(32),
                    quality_flags VARCHAR(512)
                )
                """
            )
        )

    create_schema(engine)
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("quote_snapshots")
    }
    assert "bid_depth_json" in columns
    assert "ask_depth_json" in columns
    trade_columns = {
        column["name"]
        for column in inspect(engine).get_columns("paper_trades")
    }
    assert "entry_charges_json" in trade_columns
    assert "exit_charges_json" in trade_columns
    engine.dispose()
