import os
from pathlib import Path

from pydantic import BaseModel


def _normalize_api_base_path(value: str) -> str:
    normalized = value.strip() or "/api"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized.rstrip("/") or "/api"


def _parse_cors_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def _default_data_dir() -> str:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data"
        if candidate.exists():
            return str(candidate)
    return "/data"


class Settings(BaseModel):
    app_name: str = os.getenv("APP_NAME", "mwobareullae")
    api_base_path: str = _normalize_api_base_path(os.getenv("API_BASE_PATH", "/api"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    enable_request_logging: bool = os.getenv("ENABLE_REQUEST_LOGGING", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    backend_cors_origins: list[str] = _parse_cors_origins(
        os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:5173")
    )
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://mwobareullae:change-me@postgres:5432/mwobareullae",
    )
    data_dir: str = os.getenv("DATA_DIR") or _default_data_dir()


settings = Settings()
