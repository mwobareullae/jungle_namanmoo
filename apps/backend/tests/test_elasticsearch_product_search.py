from app.services.elasticsearch_product_search import search_elasticsearch_product_candidates
from app.services.recommendation_intent import build_recommendation_intent


def test_search_elasticsearch_product_candidates_builds_keyword_query_with_hard_filters() -> None:
    client = _FakeElasticsearchClient(
        {
            "hits": {
                "hits": [
                    {"_source": {"product_db_id": 2}},
                    {"_source": {"product_db_id": 1}},
                    {"_source": {"product_db_id": 2}},
                ]
            }
        }
    )
    provider = _FakeElasticsearchProvider(client)
    intent = build_recommendation_intent("크림 2만원 이하 추천")

    result = search_elasticsearch_product_candidates(
        intent,
        limit=10,
        client_provider=provider,
        index_alias="products_current",
    )

    assert result.product_db_ids == (2, 1)
    assert result.raw_hit_count == 3
    assert result.failure_reason is None
    assert provider.success_marked is True

    call = client.search_calls[0]
    assert call["index"] == "products_current"
    assert call["size"] == 10
    assert call["query"]["bool"]["must"][0]["multi_match"]["fields"] == [
        "title^4",
        "keywords^3",
        "brand_name^2",
        "category_name^2",
        "content",
    ]
    filters = call["query"]["bool"]["filter"]
    assert {"terms": {"category_code": ["cream"]}} in filters
    assert {"range": {"lowest_price": {"lte": 20000}}} in filters


def test_search_elasticsearch_product_candidates_returns_failure_result_on_exception() -> None:
    client = _FailingElasticsearchClient()
    provider = _FakeElasticsearchProvider(client)
    intent = build_recommendation_intent("수분 진정 추천")

    result = search_elasticsearch_product_candidates(
        intent,
        limit=10,
        client_provider=provider,
        index_alias="products_current",
    )

    assert result.product_db_ids == ()
    assert result.raw_hit_count == 0
    assert "boom" in (result.failure_reason or "")
    assert provider.failure_reason == "boom"


def test_search_elasticsearch_product_candidates_skips_when_provider_disabled() -> None:
    provider = _FakeElasticsearchProvider(None, enabled=False)
    intent = build_recommendation_intent("수분 진정 추천")

    result = search_elasticsearch_product_candidates(
        intent,
        limit=10,
        client_provider=provider,
        index_alias="products_current",
    )

    assert result.attempted is False
    assert result.skipped_reason == "search backend mode is postgres"


def test_search_elasticsearch_product_candidates_uses_provider_timeout_for_reachability(
    monkeypatch,
) -> None:
    captured_timeout = None

    class _SocketContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_create_connection(address, timeout):
        nonlocal captured_timeout
        captured_timeout = timeout
        return _SocketContext()

    monkeypatch.setattr(
        "app.services.elasticsearch_product_search.socket.create_connection",
        fake_create_connection,
    )
    client = _FakeElasticsearchClient({"hits": {"hits": []}})
    provider = _FakeElasticsearchProvider(
        client,
        url="http://elasticsearch:9200",
        timeout_seconds=2.0,
    )
    intent = build_recommendation_intent("수분 크림")

    result = search_elasticsearch_product_candidates(
        intent,
        limit=10,
        client_provider=provider,
        index_alias="products_current",
    )

    assert result.failure_reason is None
    assert captured_timeout == 2.0


class _FakeElasticsearchProvider:
    def __init__(
        self,
        client,
        *,
        enabled: bool = True,
        url: str | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        self.client = client
        self.enabled = enabled
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.success_marked = False
        self.failure_reason = None

    def get_client(self):
        return self.client

    def mark_success(self) -> None:
        self.success_marked = True
        self.failure_reason = None

    def mark_failure(self, reason: str) -> None:
        self.failure_reason = reason

    def status(self):
        return _FakeStatus(self.failure_reason)


class _FakeStatus:
    def __init__(self, failure_reason: str | None) -> None:
        self.failure_reason = failure_reason


class _FakeElasticsearchClient:
    def __init__(self, response) -> None:
        self.response = response
        self.search_calls = []

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return self.response


class _FailingElasticsearchClient:
    def search(self, **kwargs):
        raise RuntimeError("boom")
