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


def _normalize_search_backend_mode(value: str) -> str:
    normalized = value.strip().lower() or "auto"
    if normalized in {"auto", "postgres", "elasticsearch"}:
        return normalized
    return "auto"


def _normalize_recommendation_scoring_read_path(value: str) -> str:
    normalized = value.strip().lower() or "legacy_bulk"
    if normalized in {"legacy_bulk", "compact_v2", "coarse_top50_v1"}:
        return normalized
    raise ValueError(
        "RECOMMENDATION_SCORING_READ_PATH must be legacy_bulk, compact_v2, "
        "or coarse_top50_v1"
    )


def _parse_bool(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _default_elasticsearch_products_alias() -> str:
    index_prefix = os.getenv("ELASTICSEARCH_INDEX_PREFIX", "mubarelle_dev")
    return f"{index_prefix}_products_current"


def _default_elasticsearch_catalog_products_alias() -> str:
    index_prefix = os.getenv("ELASTICSEARCH_INDEX_PREFIX", "mubarelle_dev")
    return f"{index_prefix}_catalog_products_current"


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
    app_env: str = os.getenv("APP_ENV", "local")
    agent_release: str = os.getenv("AGENT_RELEASE", "local")
    openai_model: str = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    openai_agent_model: str = os.getenv("OPENAI_AGENT_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.5"
    openai_agent_timeout_seconds: float = float(os.getenv("OPENAI_AGENT_TIMEOUT_SECONDS", "15"))
    openai_agent_max_retries: int = int(os.getenv("OPENAI_AGENT_MAX_RETRIES", "1"))
    # Three concurrent calls is the midpoint of the initial 2-4 safety range:
    # enough for a small demo burst without flooding one shared provider key.
    openai_agent_max_concurrency: int = int(os.getenv("OPENAI_AGENT_MAX_CONCURRENCY", "3"))
    openai_agent_queue_timeout_seconds: float = float(
        os.getenv("OPENAI_AGENT_QUEUE_TIMEOUT_SECONDS", "10")
    )
    openai_agent_busy_retry_after_seconds: int = int(
        os.getenv("OPENAI_AGENT_BUSY_RETRY_AFTER_SECONDS", "2")
    )
    # The runtime enforces a 45s floor so one 15s workflow plus a bounded
    # retry can never leave a live Redis lease behind.
    openai_agent_global_lease_ttl_seconds: int = max(
        int(os.getenv("OPENAI_AGENT_GLOBAL_LEASE_TTL_SECONDS", "45")),
        45,
    )
    openai_agent_authenticated_rate_limit_per_minute: int = max(
        int(os.getenv("OPENAI_AGENT_AUTHENTICATED_RATE_LIMIT_PER_MINUTE", "30")),
        1,
    )
    openai_agent_anonymous_rate_limit_per_minute: int = max(
        int(os.getenv("OPENAI_AGENT_ANONYMOUS_RATE_LIMIT_PER_MINUTE", "20")),
        1,
    )
    openai_agent_circuit_failure_threshold: int = int(
        os.getenv("OPENAI_AGENT_CIRCUIT_FAILURE_THRESHOLD", "3")
    )
    openai_agent_circuit_cooldown_seconds: float = float(
        os.getenv("OPENAI_AGENT_CIRCUIT_COOLDOWN_SECONDS", "30")
    )
    openai_embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
    hybrid_keyword_weight: float = float(os.getenv("HYBRID_KEYWORD_WEIGHT", "0.5"))
    hybrid_vector_weight: float = float(os.getenv("HYBRID_VECTOR_WEIGHT", "0.5"))
    recommendation_candidate_pool_limit: int = int(
        os.getenv("RECOMMENDATION_CANDIDATE_POOL_LIMIT", "500")
    )
    recommendation_scoring_read_path: str = _normalize_recommendation_scoring_read_path(
        os.getenv("RECOMMENDATION_SCORING_READ_PATH", "legacy_bulk")
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    redis_key_prefix: str = os.getenv("REDIS_KEY_PREFIX", "mubarelle:dev:")
    recommendation_candidate_cache_enabled: bool = _parse_bool(
        os.getenv("RECOMMENDATION_CANDIDATE_CACHE_ENABLED", "false")
    )
    recommendation_candidate_cache_ttl_seconds: int = int(
        os.getenv("RECOMMENDATION_CANDIDATE_CACHE_TTL_SECONDS", "300")
    )
    recommendation_candidate_price_cache_ttl_seconds: int = int(
        os.getenv("RECOMMENDATION_CANDIDATE_PRICE_CACHE_TTL_SECONDS", "60")
    )
    recommendation_candidate_cache_socket_connect_timeout_seconds: float = float(
        os.getenv("RECOMMENDATION_CANDIDATE_CACHE_SOCKET_CONNECT_TIMEOUT_SECONDS", "0.05")
    )
    recommendation_candidate_cache_socket_timeout_seconds: float = float(
        os.getenv("RECOMMENDATION_CANDIDATE_CACHE_SOCKET_TIMEOUT_SECONDS", "0.05")
    )
    search_backend_mode: str = _normalize_search_backend_mode(
        os.getenv("SEARCH_BACKEND_MODE", "auto")
    )
    elasticsearch_url: str = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")
    elasticsearch_index_prefix: str = os.getenv("ELASTICSEARCH_INDEX_PREFIX", "mubarelle_dev")
    elasticsearch_products_alias: str = os.getenv(
        "ELASTICSEARCH_PRODUCTS_ALIAS",
        _default_elasticsearch_products_alias(),
    )
    elasticsearch_catalog_products_alias: str = os.getenv(
        "ELASTICSEARCH_CATALOG_PRODUCTS_ALIAS",
        _default_elasticsearch_catalog_products_alias(),
    )
    elasticsearch_timeout_seconds: float = float(
        os.getenv("ELASTICSEARCH_TIMEOUT_SECONDS", "2.0")
    )
    elasticsearch_max_retries: int = int(os.getenv("ELASTICSEARCH_MAX_RETRIES", "0"))
    elasticsearch_circuit_breaker_seconds: int = int(
        os.getenv("ELASTICSEARCH_CIRCUIT_BREAKER_SECONDS", "60")
    )
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
    evidence_ingest_token: str = os.getenv("EVIDENCE_INGEST_TOKEN", "")


settings = Settings()
