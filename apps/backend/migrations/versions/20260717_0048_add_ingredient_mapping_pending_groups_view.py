"""add ingredient mapping pending groups materialized view

Revision ID: 20260717_0048
Revises: 20260717_0047
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260717_0048"
down_revision: str | None = "20260717_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


VIEW_NAME = "ingredient_mapping_pending_groups"


def upgrade() -> None:
    # M2-A 목록의 pending 그룹은 product_ingredients가 바뀔 때만 달라진다.
    # 최초 migration에서는 현재 데이터를 채우고, 이후 갱신은 별도 AUTOCOMMIT
    # refresh CLI가 CONCURRENTLY로 수행한다.
    op.execute(
        f"""
        create materialized view {VIEW_NAME} as
        with variants as (
            select
                i.id as source_ingredient_id,
                i.ingredient_code as pending_code,
                lower(regexp_replace(coalesce(pi.ingredient_name, ''), '\\s+', '', 'g'))
                    as normalized_source_name,
                pi.ingredient_name as raw_name,
                count(*) as variant_count
            from product_ingredients pi
            join ingredients i on i.id = pi.ingredient_id
            where i.ingredient_code like 'ing_pending_%'
               or i.ingredient_code like 'foreign_pending_%'
            group by
                i.id,
                i.ingredient_code,
                lower(regexp_replace(coalesce(pi.ingredient_name, ''), '\\s+', '', 'g')),
                pi.ingredient_name
        )
        select distinct on (source_ingredient_id, normalized_source_name)
            source_ingredient_id,
            pending_code,
            normalized_source_name,
            raw_name,
            cast(
                sum(variant_count) over (
                    partition by source_ingredient_id, normalized_source_name
                ) as bigint
            ) as connection_count
        from variants
        order by
            source_ingredient_id,
            normalized_source_name,
            variant_count desc,
            raw_name asc
        with data
        """
    )
    # CONCURRENTLY refresh에는 모든 행을 식별하는 UNIQUE 인덱스가 필요하다.
    # review JOIN 키와도 동일하다.
    op.execute(
        f"""
        create unique index uq_ing_mapping_pending_groups_source_nsn
        on {VIEW_NAME} (source_ingredient_id, normalized_source_name)
        """
    )
    op.execute(
        f"""
        create index ix_ing_mapping_pending_groups_cursor
        on {VIEW_NAME} (pending_code, normalized_source_name)
        """
    )


def downgrade() -> None:
    op.execute(f"drop materialized view if exists {VIEW_NAME}")
