from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///"):
        db_path = database_url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            future=True,
        )
    return create_engine(database_url, future=True, pool_pre_ping=True)


def create_schema(engine: Engine) -> None:
    # Import models here so SQLAlchemy has registered every table.
    from tradinggpt_options.storage import tables  # noqa: F401

    Base.metadata.create_all(engine)
    # create_all does not evolve existing tables. Keep local SQLite databases
    # created by earlier versions compatible with the quote-depth schema.
    if engine.dialect.name == "sqlite":
        columns = {
            column["name"]
            for column in inspect(engine).get_columns("quote_snapshots")
        }
        with engine.begin() as connection:
            if "bid_depth_json" not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE quote_snapshots "
                        "ADD COLUMN bid_depth_json TEXT NOT NULL DEFAULT '[]'"
                    )
                )
            if "ask_depth_json" not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE quote_snapshots "
                        "ADD COLUMN ask_depth_json TEXT NOT NULL DEFAULT '[]'"
                    )
                )


def build_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
