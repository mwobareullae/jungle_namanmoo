from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import aggregate_order_by, insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models.catalog import Product, ProductIngredient
from app.db.models.recommendation import (
    ProductEffectRecommendationFeature,
    ProductRecommendationFeature,
)
from app.db.models.taxonomy import Effect, Ingredient, IngredientEffect
from app.services.recommendation_feature_versions import (
    PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION,
    PRODUCT_RECOMMENDATION_FEATURE_VERSION,
)
from app.services.scoring import (
    ProductRecommendationFeatureSource,
    ProductRecommendationFeatureValues,
    build_product_effect_recommendation_feature_values,
    build_product_recommendation_feature_values,
    load_all_product_ingredient_effects,
)


@dataclass(frozen=True)
class ProductRecommendationFeatureRollupResult:
    requested_product_count: int
    product_count: int
    product_feature_count: int
    effect_feature_count: int
    stale_effect_feature_count: int
    batch_count: int
    computed_at: datetime
    product_feature_version: str = PRODUCT_RECOMMENDATION_FEATURE_VERSION
    effect_feature_version: str = PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION


def rollup_product_recommendation_features(
    session: Session,
    *,
    product_ids: tuple[int, ...] | None = None,
    batch_size: int = 500,
    computed_at: datetime | None = None,
) -> ProductRecommendationFeatureRollupResult:
    normalized_batch_size = max(1, int(batch_size))
    normalized_product_ids = _load_target_product_ids(session, product_ids)
    now = computed_at or datetime.now(UTC)
    product_feature_count = 0
    effect_feature_count = 0
    stale_effect_feature_count = 0
    batch_count = 0
    effect_ids_by_code = _load_effect_ids_by_code(session)

    for start in range(0, len(normalized_product_ids), normalized_batch_size):
        batch_count += 1
        batch_product_ids = normalized_product_ids[start : start + normalized_batch_size]
        product_values = _load_product_recommendation_feature_values(
            session,
            batch_product_ids,
        )
        product_rows = [
            {
                "product_id": product_id,
                "top_ingredient_codes": list(values.top_ingredient_codes),
                "top_effect_codes": list(values.top_effect_codes),
                "feature_version": PRODUCT_RECOMMENDATION_FEATURE_VERSION,
                "source_updated_at": source_updated_at,
                "computed_at": now,
            }
            for product_id, values, source_updated_at in product_values
        ]
        _upsert_rows(
            session,
            ProductRecommendationFeature,
            product_rows,
            conflict_columns=("product_id",),
            update_columns=(
                "top_ingredient_codes",
                "top_effect_codes",
                "feature_version",
                "source_updated_at",
                "computed_at",
            ),
        )
        product_feature_count += len(product_rows)

        ingredients_by_product = load_all_product_ingredient_effects(
            session,
            batch_product_ids,
        )
        effect_rows: list[dict[str, object]] = []
        current_pairs: list[tuple[int, int]] = []
        for product_id in batch_product_ids:
            feature_values = build_product_effect_recommendation_feature_values(
                ingredients_by_product.get(product_id, ())
            )
            for effect_code, values in feature_values.items():
                effect_id = effect_ids_by_code.get(effect_code)
                if effect_id is None:
                    continue
                current_pairs.append((product_id, effect_id))
                effect_rows.append(
                    {
                        "product_id": product_id,
                        "effect_id": effect_id,
                        "ingredient_effect_score": Decimal(str(values.ingredient_effect_score)),
                        "ingredient_evidence_score": Decimal(str(values.ingredient_evidence_score)),
                        "concentration_score": Decimal(str(values.concentration_score)),
                        "concentration_context": values.concentration_context,
                        "top_ingredient_ids": list(values.top_ingredient_ids),
                        "best_evidence_ids": list(values.best_evidence_ids),
                        "feature_version": PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION,
                        "computed_at": now,
                    }
                )

        stale_effect_feature_count += _delete_stale_effect_features(
            session,
            batch_product_ids,
            current_pairs,
        )
        _upsert_rows(
            session,
            ProductEffectRecommendationFeature,
            effect_rows,
            conflict_columns=("product_id", "effect_id"),
            update_columns=(
                "ingredient_effect_score",
                "ingredient_evidence_score",
                "concentration_score",
                "concentration_context",
                "top_ingredient_ids",
                "best_evidence_ids",
                "feature_version",
                "computed_at",
            ),
        )
        effect_feature_count += len(effect_rows)
        session.flush()

    return ProductRecommendationFeatureRollupResult(
        requested_product_count=(
            len(product_ids) if product_ids is not None else len(normalized_product_ids)
        ),
        product_count=len(normalized_product_ids),
        product_feature_count=product_feature_count,
        effect_feature_count=effect_feature_count,
        stale_effect_feature_count=stale_effect_feature_count,
        batch_count=batch_count,
        computed_at=now,
    )


def _load_target_product_ids(
    session: Session,
    product_ids: tuple[int, ...] | None,
) -> list[int]:
    statement = select(Product.id).order_by(Product.id.asc())
    if product_ids is not None:
        normalized_ids = sorted({int(product_id) for product_id in product_ids})
        if not normalized_ids:
            return []
        statement = statement.where(Product.id.in_(normalized_ids))
    return [int(product_id) for product_id in session.execute(statement).scalars()]


def _load_product_recommendation_feature_values(
    session: Session,
    product_ids: list[int],
) -> list[tuple[int, ProductRecommendationFeatureValues, datetime]]:
    if not product_ids:
        return []
    if session.get_bind().dialect.name == "postgresql":
        return _load_product_recommendation_feature_values_postgresql(
            session,
            product_ids,
        )
    return _load_product_recommendation_feature_values_portable(session, product_ids)


def _load_product_recommendation_feature_values_postgresql(
    session: Session,
    product_ids: list[int],
) -> list[tuple[int, ProductRecommendationFeatureValues, datetime]]:
    ingredient_ranked = (
        select(
            ProductIngredient.product_id.label("product_id"),
            Ingredient.ingredient_code.label("ingredient_code"),
            func.row_number()
            .over(
                partition_by=ProductIngredient.product_id,
                order_by=(
                    func.coalesce(ProductIngredient.display_order, 999),
                    ProductIngredient.id,
                ),
            )
            .label("rank_order"),
        )
        .join(Ingredient, ProductIngredient.ingredient_id == Ingredient.id)
        .where(ProductIngredient.product_id.in_(product_ids))
        .cte("recommendation_ingredient_ranked")
    )
    ingredient_aggregated = (
        select(
            ingredient_ranked.c.product_id,
            func.array_agg(
                aggregate_order_by(
                    ingredient_ranked.c.ingredient_code,
                    ingredient_ranked.c.rank_order.asc(),
                )
            ).label("top_ingredient_codes"),
        )
        .where(ingredient_ranked.c.rank_order <= 8)
        .group_by(ingredient_ranked.c.product_id)
        .cte("recommendation_ingredient_aggregated")
    )
    effect_max = (
        select(
            ProductIngredient.product_id.label("product_id"),
            Effect.effect_code.label("effect_code"),
            func.max(IngredientEffect.effect_score).label("effect_score"),
        )
        .join(IngredientEffect, ProductIngredient.ingredient_id == IngredientEffect.ingredient_id)
        .join(Effect, IngredientEffect.effect_id == Effect.id)
        .where(ProductIngredient.product_id.in_(product_ids))
        .group_by(ProductIngredient.product_id, Effect.effect_code)
        .cte("recommendation_effect_max")
    )
    effect_ranked = select(
        effect_max.c.product_id,
        effect_max.c.effect_code,
        func.row_number()
        .over(
            partition_by=effect_max.c.product_id,
            order_by=(effect_max.c.effect_score.desc(), effect_max.c.effect_code.asc()),
        )
        .label("rank_order"),
    ).cte("recommendation_effect_ranked")
    effect_aggregated = (
        select(
            effect_ranked.c.product_id,
            func.array_agg(
                aggregate_order_by(
                    effect_ranked.c.effect_code,
                    effect_ranked.c.rank_order.asc(),
                )
            ).label("top_effect_codes"),
        )
        .where(effect_ranked.c.rank_order <= 8)
        .group_by(effect_ranked.c.product_id)
        .cte("recommendation_effect_aggregated")
    )
    rows = session.execute(
        select(
            Product.id,
            Product.updated_at,
            ingredient_aggregated.c.top_ingredient_codes,
            effect_aggregated.c.top_effect_codes,
        )
        .outerjoin(
            ingredient_aggregated,
            Product.id == ingredient_aggregated.c.product_id,
        )
        .outerjoin(effect_aggregated, Product.id == effect_aggregated.c.product_id)
        .where(Product.id.in_(product_ids))
        .order_by(Product.id.asc())
    ).all()
    return [
        (
            int(product_id),
            ProductRecommendationFeatureValues(
                top_ingredient_codes=tuple(top_ingredient_codes or ()),
                top_effect_codes=tuple(top_effect_codes or ()),
            ),
            source_updated_at,
        )
        for product_id, source_updated_at, top_ingredient_codes, top_effect_codes in rows
    ]


def _load_product_recommendation_feature_values_portable(
    session: Session,
    product_ids: list[int],
) -> list[tuple[int, ProductRecommendationFeatureValues, datetime]]:
    source_rows = session.execute(
        select(
            ProductIngredient.product_id,
            ProductIngredient.id,
            ProductIngredient.display_order,
            Ingredient.ingredient_code,
            Effect.effect_code,
            IngredientEffect.effect_score,
        )
        .join(Ingredient, ProductIngredient.ingredient_id == Ingredient.id)
        .outerjoin(IngredientEffect, IngredientEffect.ingredient_id == Ingredient.id)
        .outerjoin(Effect, IngredientEffect.effect_id == Effect.id)
        .where(ProductIngredient.product_id.in_(product_ids))
    ).all()
    values_by_product = build_product_recommendation_feature_values(
        tuple(
            ProductRecommendationFeatureSource(
                product_db_id=int(product_id),
                product_ingredient_id=int(product_ingredient_id),
                display_order=display_order,
                ingredient_code=str(ingredient_code) if ingredient_code else None,
                effect_code=str(effect_code) if effect_code else None,
                effect_score=float(effect_score or 0.0),
            )
            for (
                product_id,
                product_ingredient_id,
                display_order,
                ingredient_code,
                effect_code,
                effect_score,
            ) in source_rows
        )
    )
    products = session.execute(
        select(Product.id, Product.updated_at)
        .where(Product.id.in_(product_ids))
        .order_by(Product.id.asc())
    ).all()
    return [
        (
            int(product_id),
            values_by_product.get(
                int(product_id),
                ProductRecommendationFeatureValues((), ()),
            ),
            source_updated_at,
        )
        for product_id, source_updated_at in products
    ]


def _load_effect_ids_by_code(session: Session) -> dict[str, int]:
    return {
        str(effect_code): int(effect_id)
        for effect_id, effect_code in session.execute(
            select(Effect.id, Effect.effect_code)
        ).all()
    }


def _delete_stale_effect_features(
    session: Session,
    product_ids: list[int],
    current_pairs: list[tuple[int, int]],
) -> int:
    statement = delete(ProductEffectRecommendationFeature).where(
        ProductEffectRecommendationFeature.product_id.in_(product_ids)
    )
    if current_pairs:
        statement = statement.where(
            tuple_(
                ProductEffectRecommendationFeature.product_id,
                ProductEffectRecommendationFeature.effect_id,
            ).not_in(current_pairs)
        )
    result = session.execute(statement)
    return max(0, int(result.rowcount or 0))


def _upsert_rows(
    session: Session,
    model: type,
    rows: list[dict[str, object]],
    *,
    conflict_columns: tuple[str, ...],
    update_columns: tuple[str, ...],
) -> None:
    if not rows:
        return
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        statement = postgresql_insert(model).values(rows)
    elif dialect_name == "sqlite":
        statement = sqlite_insert(model).values(rows)
    else:
        for row in rows:
            session.merge(model(**row))
        return
    statement = statement.on_conflict_do_update(
        index_elements=[getattr(model, column) for column in conflict_columns],
        set_={column: getattr(statement.excluded, column) for column in update_columns},
    )
    session.execute(statement)
