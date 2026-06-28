from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.catalog import (
    Brand,
    Product,
    ProductImage as ProductImageRow,
    ProductIngredient as ProductIngredientRow,
    ProductPrice as ProductPriceRow,
)
from app.db.models.recommendation import RecommendationResult
from app.db.models.taxonomy import Effect, Ingredient, IngredientEvidence, RiskFlag
from app.schemas.common import ApiError
from app.schemas.product import (
    IngredientEvidence as IngredientEvidenceSchema,
    ProductDetailResponse,
    ProductEvidence,
    ProductImage,
    ProductInfo,
    ProductIngredient,
    ProductPrice,
    SourceInfo,
)
from app.services.recommendation_pipeline import (
    load_recommendation_run,
    score_breakdown_to_api,
)


@dataclass(frozen=True)
class _ProductRow:
    product: Product
    brand: Brand
    lowest_price: int


def get_product_detail_response(
    session: Session,
    product_id: str,
    recommendation_id: str | None = None,
) -> ProductDetailResponse:
    product_row = _load_product_row(session, product_id)
    recommendation_result = _load_recommendation_result(
        session,
        product_row.product.id,
        recommendation_id,
    )

    images = _load_product_images(session, product_row.product)
    prices = _load_product_prices(session, product_row.product.id)
    ingredients = _load_product_ingredients(session, product_row.product.id)
    ingredient_evidence = _load_ingredient_evidence(session, product_row.product.id)
    sources = _build_sources(ingredient_evidence)

    return ProductDetailResponse(
        product=ProductInfo(
            product_id=product_row.product.product_code,
            brand=product_row.brand.name,
            name=product_row.product.product_name,
            thumbnail_url=_thumbnail_url(product_row.product, images),
            lowest_price=product_row.lowest_price,
            total_score=_result_total_score(recommendation_result),
            reason_summary=recommendation_result.reason_summary if recommendation_result else None,
            score_breakdown=(
                score_breakdown_to_api(recommendation_result.score_breakdown)
                if recommendation_result
                else None
            ),
        ),
        images=images,
        prices=prices,
        ingredients=ingredients,
        evidence=ProductEvidence(
            ingredient_evidence=[
                IngredientEvidenceSchema(
                    ingredient=evidence.ingredient_name,
                    effect=evidence.effect_name,
                    description=evidence.summary,
                    source_title=evidence.source_title,
                )
                for evidence in ingredient_evidence
            ],
            recommendation_reason=(
                recommendation_result.reason_summary if recommendation_result else None
            ),
        ),
        sources=sources,
    )


def _load_product_row(session: Session, product_code: str) -> _ProductRow:
    lowest_prices = (
        select(
            ProductPriceRow.product_id.label("product_id"),
            func.min(ProductPriceRow.price).label("lowest_price"),
        )
        .group_by(ProductPriceRow.product_id)
        .subquery()
    )

    row = session.execute(
        select(Product, Brand, lowest_prices.c.lowest_price)
        .join(Brand, Product.brand_id == Brand.id)
        .outerjoin(lowest_prices, lowest_prices.c.product_id == Product.id)
        .where(Product.product_code == product_code)
    ).one_or_none()

    if row is None:
        raise ApiError(404, "NOT_FOUND", "상품을 찾을 수 없습니다.")

    product, brand, lowest_price = row
    return _ProductRow(
        product=product,
        brand=brand,
        lowest_price=int(lowest_price or 0),
    )


def _thumbnail_url(product: Product, images: list[ProductImage]) -> str:
    if product.thumbnail_url:
        return product.thumbnail_url
    if images:
        return images[0].url
    return ""


def _load_recommendation_result(
    session: Session,
    product_db_id: int,
    recommendation_id: str | None,
) -> RecommendationResult | None:
    if not recommendation_id:
        return None

    run = load_recommendation_run(session, recommendation_id)
    return session.execute(
        select(RecommendationResult).where(
            RecommendationResult.recommendation_run_id == run.id,
            RecommendationResult.product_id == product_db_id,
        )
    ).scalar_one_or_none()


def _load_product_images(session: Session, product_db_id: Product) -> list[ProductImage]:
    rows = session.execute(
        select(ProductImageRow)
        .where(ProductImageRow.product_id == product_db_id.id)
        .order_by(ProductImageRow.display_order.asc(), ProductImageRow.id.asc())
    ).scalars()
    return [
        ProductImage(
            url=row.image_url,
            alt=f"{product_db_id.product_name} 이미지",
        )
        for row in rows
    ]


def _load_product_prices(session: Session, product_db_id: int) -> list[ProductPrice]:
    rows = session.execute(
        select(ProductPriceRow)
        .where(ProductPriceRow.product_id == product_db_id)
        .order_by(ProductPriceRow.is_lowest.desc(), ProductPriceRow.price.asc())
    ).scalars()
    return [
        ProductPrice(
            mall_name=row.mall_name,
            price=row.price,
            product_url=row.product_url,
            is_lowest=row.is_lowest,
        )
        for row in rows
    ]


def _load_product_ingredients(session: Session, product_db_id: int) -> list[ProductIngredient]:
    rows = session.execute(
        select(ProductIngredientRow, Ingredient)
        .join(Ingredient, ProductIngredientRow.ingredient_id == Ingredient.id)
        .where(ProductIngredientRow.product_id == product_db_id)
        .order_by(ProductIngredientRow.display_order.asc(), ProductIngredientRow.id.asc())
    ).all()
    risk_notes_by_ingredient_id = _load_risk_notes(
        session,
        [ingredient.id for _, ingredient in rows],
    )

    return [
        ProductIngredient(
            name=product_ingredient.ingredient_name or ingredient.name_ko,
            purpose=ingredient.description or product_ingredient.content_confidence or "성분 정보",
            risk_note=risk_notes_by_ingredient_id.get(ingredient.id),
        )
        for product_ingredient, ingredient in rows
    ]


@dataclass(frozen=True)
class _IngredientEvidencePayload:
    ingredient_name: str
    effect_name: str
    summary: str
    source_title: str
    source_url: str | None


def _load_ingredient_evidence(
    session: Session,
    product_db_id: int,
) -> list[_IngredientEvidencePayload]:
    rows = session.execute(
        select(
            Ingredient.name_ko,
            Effect.name,
            IngredientEvidence.summary,
            IngredientEvidence.source_title,
            IngredientEvidence.source_url,
            IngredientEvidence.evidence_score,
        )
        .join(
            ProductIngredientRow,
            ProductIngredientRow.ingredient_id == IngredientEvidence.ingredient_id,
        )
        .join(Ingredient, IngredientEvidence.ingredient_id == Ingredient.id)
        .outerjoin(Effect, IngredientEvidence.effect_id == Effect.id)
        .where(ProductIngredientRow.product_id == product_db_id)
        .order_by(IngredientEvidence.evidence_score.desc(), IngredientEvidence.id.asc())
    ).all()

    return [
        _IngredientEvidencePayload(
            ingredient_name=ingredient_name,
            effect_name=effect_name or "근거",
            summary=summary,
            source_title=source_title or "근거 자료",
            source_url=source_url,
        )
        for ingredient_name, effect_name, summary, source_title, source_url, _ in rows
    ]


def _load_risk_notes(session: Session, ingredient_ids: list[int]) -> dict[int, str]:
    if not ingredient_ids:
        return {}

    rows = session.execute(
        select(RiskFlag.ingredient_id, RiskFlag.display_text)
        .where(RiskFlag.ingredient_id.in_(ingredient_ids))
        .order_by(RiskFlag.id.asc())
    ).all()
    notes_by_ingredient_id: dict[int, list[str]] = {}
    for ingredient_id, display_text in rows:
        notes_by_ingredient_id.setdefault(int(ingredient_id), []).append(display_text)

    return {
        ingredient_id: "; ".join(notes)
        for ingredient_id, notes in notes_by_ingredient_id.items()
    }


def _build_sources(evidence: list[_IngredientEvidencePayload]) -> list[SourceInfo]:
    sources: list[SourceInfo] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        url = item.source_url or ""
        key = (item.source_title, url)
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            SourceInfo(
                title=item.source_title,
                url=url,
                source_type="ingredient_evidence",
            )
        )
    return sources


def _result_total_score(result: RecommendationResult | None) -> int | None:
    if result is None:
        return None
    value = result.total_score
    if isinstance(value, Decimal):
        value = float(value)
    return int(round(float(value)))
