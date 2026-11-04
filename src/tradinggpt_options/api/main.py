from fastapi import FastAPI

from tradinggpt_options import __version__
from tradinggpt_options.config.settings import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version=__version__)


@app.get("/health", tags=["system"])
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "application": settings.app_name,
        "version": __version__,
        "trading_mode": settings.trading_mode,
        "live_trading_enabled": settings.live_trading_enabled,
    }
