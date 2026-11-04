from __future__ import annotations

import argparse
from decimal import Decimal

from tradinggpt_options.config.settings import get_settings
from tradinggpt_options.execution.paper_broker import PaperBroker, PaperExecutionConfig
from tradinggpt_options.storage.database import build_engine, build_session_factory, create_schema


def initialize_paper_account() -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    create_schema(engine)
    factory = build_session_factory(engine)
    with factory() as session:
        broker = PaperBroker(
            session,
            account_name="default",
            config=PaperExecutionConfig(
                initial_capital=Decimal(str(settings.paper_initial_capital))
            ),
        )
        print("Paper account initialized.")
        print(f"Account: default")
        print(f"Cash balance: INR {broker.cash_balance():,.2f}")
        print("Trading mode: PAPER (no live order functionality)")
    engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="tradinggpt-options")
    parser.add_argument(
        "command",
        choices=("init-paper-account",),
        help="Initialize the persistent local paper account",
    )
    args = parser.parse_args()
    if args.command == "init-paper-account":
        initialize_paper_account()


if __name__ == "__main__":
    main()
