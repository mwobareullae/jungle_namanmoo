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
    enable_performance_logging: bool = os.getenv("ENABLE_PERFORMANCE_LOGGING", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    enable_db_slow_query_logging: bool = os.getenv("ENABLE_DB_SLOW_QUERY_LOGGING", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    db_slow_query_threshold_ms: float = float(os.getenv("DB_SLOW_QUERY_THRESHOLD_MS", "100"))
    backend_cors_origins: list[str] = _parse_cors_origins(
        os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:5173")
    )
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://mwobareullae:change-me@postgres:5432/mwobareullae",
    )
    data_dir: str = os.getenv("DATA_DIR") or _default_data_dir()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    openai_agent_model: str = os.getenv("OPENAI_AGENT_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.5"
    openai_embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
    hybrid_keyword_weight: float = float(os.getenv("HYBRID_KEYWORD_WEIGHT", "0.5"))
    hybrid_vector_weight: float = float(os.getenv("HYBRID_VECTOR_WEIGHT", "0.5"))
    recommendation_candidate_pool_limit: int = int(
        os.getenv("RECOMMENDATION_CANDIDATE_POOL_LIMIT", "500")
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    redis_key_prefix: str = os.getenv("REDIS_KEY_PREFIX", "mubarelle:dev:")
    elasticsearch_url: str = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")
    elasticsearch_index_prefix: str = os.getenv("ELASTICSEARCH_INDEX_PREFIX", "mubarelle_dev")
    auth_jwt_secret_key: str = os.getenv("AUTH_JWT_SECRET_KEY", "change-me-local-secret")
    auth_session_cookie_name: str = os.getenv("AUTH_SESSION_COOKIE_NAME", "mwbl_session")
    auth_session_ttl_days: int = int(os.getenv("AUTH_SESSION_TTL_DAYS", "14"))
    auth_cookie_secure: bool = os.getenv("AUTH_COOKIE_SECURE", "false").lower() not in {
        "0",
        "false",
        "no",
    }
    auth_cookie_samesite: str = os.getenv("AUTH_COOKIE_SAMESITE", "lax").lower()
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from_email: str = os.getenv("SMTP_FROM_EMAIL", "no-reply@mubarelle.com")
    smtp_use_tls: bool = os.getenv("SMTP_USE_TLS", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    kakao_client_id: str = os.getenv("KAKAO_CLIENT_ID", "")
    kakao_client_secret: str = os.getenv("KAKAO_CLIENT_SECRET", "")
    toss_secret_key: str = os.getenv("TOSS_SECRET_KEY", "")


settings = Settings()
