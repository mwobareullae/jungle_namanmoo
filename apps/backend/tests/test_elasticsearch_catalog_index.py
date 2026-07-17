from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.catalog import Product, ProductPrice
from app.db.models.commerce import Inventory, ProductPopularityMetric
from app.db.models.review import ProductReviewMetric
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.elasticsearch_catalog_index import (
    CATALOG_PRODUCT_INDEX_MAPPING,
    build_catalog_products_index_name,
    count_catalog_search_products,
    index_catalog_products_to_elasticsearch,
    iter_catalog_product_document_batches,
    reindex_catalog_product_to_elasticsearch,
)
from tests.test_data_loader import EXAMPLES_DIR


def test_catalog_mapping_uses_nori_and_strict_fields() -> None:
    analysis = CATALOG_PRODUCT_INDEX_MAPPING["settings"]["analysis"]

    assert analysis["tokenizer"]["catalog_nori_tokenizer"]["type"] == "nori_tokenizer"
    assert CATALOG_PRODUCT_INDEX_MAPPING["mappings"]["dynamic"] == "strict"
    assert "product_name_chosung" in CATALOG_PRODUCT_INDEX_MAPPING["mappings"]["properties"]
    assert "aliases_compact" in CATALOG_PRODUCT_INDEX_MAPPING["mappings"]["properties"]
    assert "aliases_chosung" in CATALOG_PRODUCT_INDEX_MAPPING["mappings"]["properties"]
    assert CATALOG_PRODUCT_INDEX_MAPPING["mappings"]["properties"]["ingredient_codes"] == {
        "type": "keyword"
    }
    assert (
        CATALOG_PRODUCT_INDEX_MAPPING["mappings"]["properties"]["ingredient_names"][
            "fields"
        ]["exact"]["type"]
        == "keyword"
    )


def test_build_catalog_products_index_name_uses_separate_prefix() -> None:
    assert build_catalog_products_index_name("v1").endswith("_catalog_products_v1")


def test_catalog_document_batches_use_keyset_and_include_search_fields() -> None:
    session = _seed_example_session()

    batches = list(iter_catalog_product_document_batches(session, batch_size=1))

    assert [len(batch) for batch in batches] == [1, 1]
    documents = [document for batch in batches for document in batch]
    assert [document["product_db_id"] for document in documents] == sorted(
        document["product_db_id"] for document in documents
    )
    assert all(document["product_name_compact"] for document in documents)
    assert all(document["product_name_chosung"] for document in documents)
    assert all(document["category_group"] for document in documents)
    assert all("aliases_compact" in document for document in documents)
    assert all("aliases_chosung" in document for document in documents)
    assert all("ingredient_codes" in document for document in documents)
    assert all("feature_codes" in document for document in documents)
    assert all("skin_type_codes" in document for document in documents)
    first_document = next(document for document in documents if document["product_id"] == "prod_001")
    assert first_document["ingredient_codes"]
    assert "moisturizing_calming" in first_document["feature_codes"]
    assert "dehydrated_oily" in first_document["skin_type_codes"]
    assert "normal" in first_document["skin_type_codes"]


def test_catalog_document_uses_review_metrics_for_rating_fields() -> None:
    session = _seed_example_session()
    product = session.scalar(select(Product).where(Product.product_code == "prod_001"))
    assert product is not None
    session.add_all(
        [
            ProductPopularityMetric(
                product_id=product.id,
                window_days=7,
                review_count=999,
                average_rating=1.0,
                popularity_score=65,
            ),
            ProductReviewMetric(
                product_id=product.id,
                review_count=24,
                rating_count=24,
                average_rating=4.75,
            ),
        ]
    )
    session.flush()

    document = next(
        document
        for batch in iter_catalog_product_document_batches(session)
        for document in batch
        if document["product_id"] == "prod_001"
    )

    assert document["rating"] == 4.75
    assert document["review_count"] == 24
    assert document["popularity_score"] == 65.0


def test_catalog_index_includes_product_without_price() -> None:
    session = _seed_example_session()
    product = session.execute(select(Product).order_by(Product.id.asc())).scalars().first()
    assert product is not None
    session.execute(delete(ProductPrice).where(ProductPrice.product_id == product.id))
    session.commit()

    documents = [
        document
        for batch in iter_catalog_product_document_batches(session)
        for document in batch
    ]
    target = next(document for document in documents if document["product_db_id"] == product.id)

    assert target["lowest_price"] is None
    assert count_catalog_search_products(session) == 2


def test_catalog_index_excludes_hidden_but_keeps_non_recommendable() -> None:
    session = _seed_example_session()
    products = session.execute(select(Product).order_by(Product.id.asc())).scalars().all()
    first, second = products
    first.is_recommendable = False
    inventory = session.execute(
        select(Inventory).where(Inventory.product_id == second.id)
    ).scalar_one_or_none()
    if inventory is None:
        inventory = Inventory(
            product_id=second.id,
            stock_quantity=10,
            reserved_quantity=0,
            safety_stock=0,
            sales_status="HIDDEN",
        )
        session.add(inventory)
    else:
        inventory.sales_status = "HIDDEN"
    session.commit()

    documents = [
        document
        for batch in iter_catalog_product_document_batches(session)
        for document in batch
    ]

    assert [document["product_db_id"] for document in documents] == [first.id]
    assert documents[0]["is_recommendable"] is False


def test_catalog_index_dry_run_counts_without_loading_client() -> None:
    session = _seed_example_session()

    result = index_catalog_products_to_elasticsearch(
        session,
        index_suffix="dry-run",
        dry_run=True,
    )

    assert result.expected == 2
    assert result.scanned == 0
    assert result.validation_passed is True
    assert result.alias_swapped is False


def test_catalog_index_swaps_alias_only_after_validation(monkeypatch) -> None:
    session = _seed_example_session()
    client = _FakeElasticsearchClient()
    provider = _FakeClientProvider(client)

    def fake_bulk(client, index_name, documents, **kwargs):
        client.documents[index_name].update(
            {document["product_id"]: document for document in documents}
        )
        return len(documents), []

    monkeypatch.setattr(
        "app.services.elasticsearch_catalog_index._bulk_index_documents",
        fake_bulk,
    )

    result = index_catalog_products_to_elasticsearch(
        session,
        client_provider=provider,
        index_suffix="publish",
        cleanup_old_indices=False,
    )

    assert result.validation_passed is True
    assert result.alias_swapped is True
    assert result.indexed_document_count == 2
    assert client.alias_actions[-1]["add"]["alias"].endswith("_catalog_products_current")
    assert provider.success_count == 1


def test_catalog_index_does_not_swap_alias_when_bulk_validation_fails(monkeypatch) -> None:
    session = _seed_example_session()
    client = _FakeElasticsearchClient()
    provider = _FakeClientProvider(client)

    def fake_bulk(client, index_name, documents, **kwargs):
        first = documents[0]
        client.documents[index_name][first["product_id"]] = first
        return 1, [{"index": {"status": 500}}]

    monkeypatch.setattr(
        "app.services.elasticsearch_catalog_index._bulk_index_documents",
        fake_bulk,
    )

    result = index_catalog_products_to_elasticsearch(
        session,
        client_provider=provider,
        index_suffix="failed",
        cleanup_old_indices=False,
    )

    assert result.validation_passed is False
    assert result.alias_swapped is False
    assert result.failed == 1
    assert client.alias_actions == []


def test_single_catalog_product_reindex_updates_alias_document() -> None:
    session = _seed_example_session()
    client = _FakeElasticsearchClient()
    provider = _FakeClientProvider(client)
    client.documents["test_catalog_current"] = {}

    result = reindex_catalog_product_to_elasticsearch(
        session,
        product_id="prod_001",
        client_provider=provider,
        index_alias="test_catalog_current",
        refresh=True,
    )

    assert result.action == "INDEXED"
    assert client.documents["test_catalog_current"]["prod_001"]["lowest_price"] == 19900
    assert client.index_refreshes[-1] == "wait_for"


def test_single_catalog_product_reindex_removes_hidden_document() -> None:
    session = _seed_example_session()
    product = session.execute(select(Product).where(Product.product_code == "prod_001")).scalar_one()
    session.add(
        Inventory(
            product_id=product.id,
            stock_quantity=0,
            reserved_quantity=0,
            safety_stock=0,
            sales_status="HIDDEN",
        )
    )
    session.commit()
    client = _FakeElasticsearchClient()
    client.documents["test_catalog_current"] = {"prod_001": {"product_id": "prod_001"}}
    provider = _FakeClientProvider(client)

    result = reindex_catalog_product_to_elasticsearch(
        session,
        product_id="prod_001",
        client_provider=provider,
        index_alias="test_catalog_current",
    )

    assert result.action == "DELETED_OR_MISSING"
    assert "prod_001" not in client.documents["test_catalog_current"]


class _FakeIndicesClient:
    def __init__(self, parent) -> None:
        self.parent = parent

    def exists(self, *, index: str) -> bool:
        return index in self.parent.documents

    def create(self, *, index: str, **kwargs) -> None:
        self.parent.documents[index] = {}

    def refresh(self, *, index: str) -> None:
        assert index in self.parent.documents

    def get_alias(self, *, name: str):
        if not self.parent.alias_indices:
            raise RuntimeError("alias missing")
        return {index_name: {} for index_name in self.parent.alias_indices}

    def update_aliases(self, *, actions) -> None:
        self.parent.alias_actions = list(actions)
        self.parent.alias_indices = {
            action["add"]["index"]
            for action in actions
            if "add" in action
        }

    def get(self, *, index: str, allow_no_indices: bool = True):
        return {index_name: {} for index_name in self.parent.documents}

    def delete(self, *, index: str) -> None:
        self.parent.documents.pop(index, None)


class _FakeElasticsearchClient:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, dict]] = {}
        self.alias_actions: list[dict] = []
        self.alias_indices: set[str] = set()
        self.index_refreshes: list[object] = []
        self.indices = _FakeIndicesClient(self)

    def index(self, *, index: str, id: str, document: dict, refresh=False):
        self.documents[index][id] = document
        self.index_refreshes.append(refresh)
        return {"result": "updated"}

    def delete(self, *, index: str, id: str, refresh=False):
        if id not in self.documents[index]:
            error = RuntimeError("not found")
            error.status_code = 404
            raise error
        del self.documents[index][id]
        return {"result": "deleted"}

    def count(self, *, index: str):
        return {"count": len(self.documents[index])}

    def mget(self, *, index: str, ids, source: bool = False):
        return {
            "docs": [
                {"_id": product_id, "found": product_id in self.documents[index]}
                for product_id in ids
            ]
        }


class _FakeClientProvider:
    def __init__(self, client) -> None:
        self.client = client
        self.success_count = 0
        self.failure_reasons: list[str] = []

    def get_client(self):
        return self.client

    def mark_success(self) -> None:
        self.success_count += 1

    def mark_failure(self, reason: str) -> None:
        self.failure_reasons.append(reason)


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    session.commit()
    return session
