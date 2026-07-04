from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models.catalog import (
    Brand,
    Product,
    ProductImage as ProductImageRow,
    ProductIngredient as ProductIngredientRow,
    ProductPrice as ProductPriceRow,
)
from app.db.models.commerce import Inventory, Seller
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
    ProductPurchaseInfo,
    ProductPrice,
    SourceInfo,
)
from app.schemas.recommendation import CartHandoff
from app.services.recommendation_pipeline import (
    load_recommendation_run,
    score_breakdown_to_api,
)


@dataclass(frozen=True)
class _ProductRow:
    product: Product
    brand: Brand
    seller: Seller
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
    price_rows = _load_product_price_rows(session, product_row.product.id)
    prices = [_to_product_price(row) for row in price_rows]
    purchase_info = _build_purchase_info(session, product_row, price_rows)
    ingredients = _load_product_ingredients(session, product_row.product.id)
    ingredient_evidence = _load_ingredient_evidence(session, product_row.product.id)
    sources = _build_sources(ingredient_evidence)

    return ProductDetailResponse(
        product=ProductInfo(
            product_id=product_row.product.product_code,
            brand=product_row.brand.name,
            name=product_row.product.product_name,
            thumbnail_url=_thumbnail_url(images),
            lowest_price=product_row.lowest_price,
            total_score=_result_total_score(recommendation_result),
            reason_summary=recommendation_result.reason_summary if recommendation_result else None,
            score_breakdown=(
                score_breakdown_to_api(recommendation_result.score_breakdown)
                if recommendation_result
                else None
            ),
            cart_handoff=(
                CartHandoff(
                    product_id=product_row.product.product_code,
                    recommendation_id=recommendation_id,
                    recommendation_rank=recommendation_result.rank_order,
                )
                if recommendation_result and recommendation_id
                else None
            ),
        ),
        images=images,
        prices=prices,
        purchase_info=purchase_info,
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
        select(Product, Brand, Seller, lowest_prices.c.lowest_price)
        .join(Brand, Product.brand_id == Brand.id)
        .join(Seller, Product.seller_id == Seller.id)
        .outerjoin(lowest_prices, lowest_prices.c.product_id == Product.id)
        .where(Product.product_code == product_code)
    ).one_or_none()

    if row is None:
        raise ApiError(404, "NOT_FOUND", "상품을 찾을 수 없습니다.")

    product, brand, seller, lowest_price = row
    return _ProductRow(
        product=product,
        brand=brand,
        seller=seller,
        lowest_price=int(lowest_price or 0),
    )


def _thumbnail_url(images: list[ProductImage]) -> str:
    for image in images:
        if image.image_type == "thumbnail":
            return image.storage_key
    if images:
        return images[0].storage_key
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
        .order_by(
            case((ProductImageRow.image_type == "thumbnail", 0), else_=1),
            ProductImageRow.display_order.asc(),
            ProductImageRow.id.asc(),
        )
    ).scalars()
    return [
        ProductImage(
            image_type=row.image_type,
            storage_key=row.storage_key,
            display_order=row.display_order,
            alt=f"{product_db_id.product_name} 이미지",
        )
        for row in rows
    ]


def _load_product_price_rows(session: Session, product_db_id: int) -> list[ProductPriceRow]:
    return list(
        session.execute(
            select(ProductPriceRow)
            .where(ProductPriceRow.product_id == product_db_id)
            .order_by(ProductPriceRow.is_lowest.desc(), ProductPriceRow.price.asc())
        ).scalars()
    )


def _to_product_price(row: ProductPriceRow) -> ProductPrice:
    return ProductPrice(
        mall_name=row.mall_name,
        price=row.price,
        product_url=row.product_url,
        is_lowest=row.is_lowest,
    )


def _build_purchase_info(
    session: Session,
    product_row: _ProductRow,
    price_rows: list[ProductPriceRow],
) -> ProductPurchaseInfo:
    inventory = _load_inventory(session, product_row.product.id)
    primary_price = price_rows[0] if price_rows else None
    available_quantity = _available_quantity(inventory)
    stock_status = _stock_status(inventory, available_quantity)
    sales_status = inventory.sales_status if inventory else "UNKNOWN"
    can_purchase = (
        product_row.product.is_active
        and product_row.seller.status == "ACTIVE"
        and primary_price is not None
        and sales_status == "ON_SALE"
        and available_quantity is not None
        and available_quantity > 0
    )

    return ProductPurchaseInfo(
        seller_code=product_row.seller.seller_code,
        seller_name=product_row.seller.display_name,
        seller_type=product_row.seller.seller_type,
        price=primary_price.price if primary_price else None,
        currency=primary_price.currency if primary_price else None,
        purchase_url=(
            primary_price.product_url if primary_price else product_row.product.product_url
        ),
        can_purchase=can_purchase,
        sales_status=sales_status,
        stock_status=stock_status,
        available_quantity=available_quantity,
    )


def _load_inventory(session: Session, product_db_id: int) -> Inventory | None:
    return session.execute(
        select(Inventory).where(Inventory.product_id == product_db_id)
    ).scalar_one_or_none()


def _available_quantity(inventory: Inventory | None) -> int | None:
    if inventory is None:
        return None
    return max(
        inventory.stock_quantity - inventory.reserved_quantity - inventory.safety_stock,
        0,
    )


def _stock_status(inventory: Inventory | None, available_quantity: int | None) -> str:
    if inventory is None:
        return "UNKNOWN"
    if inventory.sales_status == "HIDDEN":
        return "HIDDEN"
    if (
        inventory.sales_status == "SOLD_OUT"
        or available_quantity is None
        or available_quantity <= 0
    ):
        return "SOLD_OUT"
    if available_quantity <= 5:
        return "LOW_STOCK"
    return "IN_STOCK"


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
