from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TradingGPT Options"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = "sqlite:///./data/tradinggpt_options.db"

    trading_mode: Literal["PAPER"] = "PAPER"
    paper_initial_capital: float = Field(default=100_000, gt=0)
    live_trading_enabled: Literal[False] = False

    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
