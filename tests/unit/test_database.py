from sqlalchemy import create_engine, inspect, text

from tradinggpt_options.storage.database import create_schema


def test_create_schema_adds_quote_depth_columns_to_legacy_sqlite_database() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
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
    engine.dispose()
