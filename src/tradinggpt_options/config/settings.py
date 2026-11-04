from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TradingGPT Options"
    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "sqlite:///./data/tradinggpt_options.db"

    trading_mode: Literal["PAPER"] = "PAPER"
    paper_initial_capital: Decimal = Field(default=Decimal("100000"), gt=0)
    live_trading_enabled: Literal[False] = False

    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""
    kite_underlying_spot_instruments: str = ""
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("DATABASE_URL cannot be empty")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
