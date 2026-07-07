from datetime import UTC, datetime, timedelta

from app.services.elasticsearch_client import ElasticsearchClientProvider


def test_postgres_mode_disables_elasticsearch_client_attempts() -> None:
    provider = ElasticsearchClientProvider(mode="postgres")

    assert provider.enabled is False
    assert provider.should_attempt() is False
    assert provider.get_client() is None

    status = provider.status()
    assert status.enabled is False
    assert status.available is False
    assert status.mode == "postgres"


def test_invalid_mode_falls_back_to_auto() -> None:
    provider = ElasticsearchClientProvider(mode="unexpected")

    assert provider.mode == "auto"
    assert provider.enabled is True


def test_client_is_created_lazily_without_connecting_to_server() -> None:
    provider = ElasticsearchClientProvider(
        mode="auto",
        url="http://localhost:9200",
        timeout_seconds=0.01,
        max_retries=0,
    )

    client = provider.get_client()

    assert client is not None
    assert provider.status().available is True


def test_failure_opens_temporary_circuit_breaker() -> None:
    provider = ElasticsearchClientProvider(mode="auto", circuit_breaker_seconds=60)
    now = datetime(2026, 7, 6, tzinfo=UTC)

    provider.mark_failure("connection refused", now=now)

    assert provider.should_attempt(now + timedelta(seconds=30)) is False
    assert provider.should_attempt(now + timedelta(seconds=61)) is True

    status = provider.status(now + timedelta(seconds=30))
    assert status.enabled is True
    assert status.available is False
    assert status.failure_reason == "connection refused"
    assert status.disabled_until == now + timedelta(seconds=60)


def test_success_closes_circuit_breaker() -> None:
    provider = ElasticsearchClientProvider(mode="auto", circuit_breaker_seconds=60)
    now = datetime(2026, 7, 6, tzinfo=UTC)

    provider.mark_failure("timeout", now=now)
    provider.mark_success()

    status = provider.status(now + timedelta(seconds=30))
    assert status.available is True
    assert status.failure_reason is None
    assert status.disabled_until is None
