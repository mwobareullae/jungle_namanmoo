"""add seller shipping policies

Revision ID: 20260705_0022
Revises: 20260705_0021
Create Date: 2026-07-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260705_0022"
down_revision: str | None = "20260705_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seller_shipping_policies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("seller_id", sa.BigInteger(), nullable=False),
        sa.Column("policy_name", sa.String(length=80), server_default="default", nullable=False),
        sa.Column("base_shipping_fee", sa.Integer(), server_default="3000", nullable=False),
        sa.Column("free_shipping_threshold", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "base_shipping_fee >= 0",
            name="ck_seller_shipping_policies_base_fee_non_negative",
        ),
        sa.CheckConstraint(
            "free_shipping_threshold is null or free_shipping_threshold >= 0",
            name="ck_seller_shipping_policies_free_threshold_non_negative",
        ),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "policy_name", name="uq_seller_shipping_policies_seller_policy_name"),
    )
    op.create_index("ix_seller_shipping_policies_seller_id", "seller_shipping_policies", ["seller_id"])
    op.create_index(
        "ix_seller_shipping_policies_seller_active",
        "seller_shipping_policies",
        ["seller_id", "is_active"],
    )
    op.execute(
        """
        insert into seller_shipping_policies (seller_id, policy_name, base_shipping_fee, is_active)
        select sellers.id, 'default', 3000, true
        from sellers
        where not exists (
            select 1
            from seller_shipping_policies
            where seller_shipping_policies.seller_id = sellers.id
              and seller_shipping_policies.policy_name = 'default'
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_seller_shipping_policies_seller_active", table_name="seller_shipping_policies")
    op.drop_index("ix_seller_shipping_policies_seller_id", table_name="seller_shipping_policies")
    op.drop_table("seller_shipping_policies")
