from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.auth import AuthAccount, User
from app.db.models.catalog import Brand, Product, ProductImage, ProductPrice
from app.db.models.commerce import Cart, CartItem, Order, OrderFulfillmentEvent, OrderItem, RecentView, Seller, Wishlist
from app.db.models.events import EventLog
from app.db.models.review import FIRST_PARTY_REVIEW_SOURCE, ProductReview, ProductReviewProfileLabel
from app.db.models.skin import BaumannTypeProfile, SkinProfile, SkinTestAnswer, SkinTestResult, SkinTestVersion
from app.db.session import SessionLocal
from app.services.auth_security import hash_password
from app.services.review_mutation_service import FIRST_PARTY_PROFILE_MAPPING_VERSION
from app.services.review_rollup import rollup_product_review_metrics


DEFAULT_COUNT = 10
DEFAULT_EMAIL_PREFIX = "benchmark_full"
DEFAULT_EMAIL_DOMAIN = "example.test"
DEFAULT_PASSWORD_ENV = "BENCHMARK_FULL_PERSONALIZED_USER_PASSWORD"

SKIN_DRY = "\uac74\uc131"
SKIN_OILY = "\uc9c0\uc131"
SKIN_COMBINATION = "\ubcf5\ud569\uc131"
SKIN_NORMAL = "\uc911\uc131"
SKIN_DEHYDRATED_OILY = "\uc218\ubd80\uc9c0"
SENS_LOW = "\ub0ae\uc74c"
SENS_MEDIUM = "\ubcf4\ud1b5"
SENS_HIGH = "\ub192\uc74c"

SKIN_TYPE_CODES = {
    SKIN_DRY: "dry",
    SKIN_OILY: "oily",
    SKIN_COMBINATION: "combination",
    SKIN_NORMAL: "normal",
    SKIN_DEHYDRATED_OILY: "combination",
}
SENSITIVITY_CODES = {
    SENS_LOW: "low",
    SENS_MEDIUM: "medium",
    SENS_HIGH: "high",
}

SKIN_VARIANTS = (
    {
        "type_code": "DSPW",
        "skin_type": SKIN_DRY,
        "sensitivity": SENS_HIGH,
        "category_preference": "ampoule_serum_essence",
        "buying_criteria": "ingredient",
        "price_investment": "functional_investment",
        "decision_trigger": "clinical_evidence",
        "concerns": ("hydration", "barrier", "wrinkle"),
    },
    {
        "type_code": "OSNW",
        "skin_type": SKIN_OILY,
        "sensitivity": SENS_HIGH,
        "category_preference": "toner_pad",
        "buying_criteria": "review",
        "price_investment": "daily_repeat_value",
        "decision_trigger": "similar_review",
        "concerns": ("sebum", "trouble", "brightening"),
    },
    {
        "type_code": "ORPT",
        "skin_type": SKIN_OILY,
        "sensitivity": SENS_LOW,
        "category_preference": "lotion_cream",
        "buying_criteria": "value",
        "price_investment": "value_volume",
        "decision_trigger": "similar_review",
        "concerns": ("sebum", "pore", "elasticity"),
    },
    {
        "type_code": "DSNT",
        "skin_type": SKIN_DRY,
        "sensitivity": SENS_MEDIUM,
        "category_preference": "lotion_cream",
        "buying_criteria": "ingredient",
        "price_investment": "premium_effect",
        "decision_trigger": "clinical_evidence",
        "concerns": ("hydration", "barrier", "calming"),
    },
    {
        "type_code": "OSPT",
        "skin_type": SKIN_DEHYDRATED_OILY,
        "sensitivity": SENS_HIGH,
        "category_preference": "ampoule_serum_essence",
        "buying_criteria": "review",
        "price_investment": "functional_investment",
        "decision_trigger": "similar_review",
        "concerns": ("hydration", "trouble", "pore"),
    },
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed full-personalized benchmark users.")
    parser.add_argument(
        "--count",
        type=int,
        default=int(os.getenv("BENCHMARK_FULL_PERSONALIZED_USER_COUNT", DEFAULT_COUNT)),
    )
    parser.add_argument(
        "--email-prefix",
        default=os.getenv("BENCHMARK_FULL_PERSONALIZED_USER_EMAIL_PREFIX", DEFAULT_EMAIL_PREFIX),
    )
    parser.add_argument(
        "--email-domain",
        default=os.getenv("BENCHMARK_FULL_PERSONALIZED_USER_EMAIL_DOMAIN", DEFAULT_EMAIL_DOMAIN),
    )
    parser.add_argument("--password", default=os.getenv(DEFAULT_PASSWORD_ENV, ""))
    args = parser.parse_args()

    if args.count < 1:
        raise SystemExit("--count must be greater than 0")
    if not args.password:
        raise SystemExit(f"--password or {DEFAULT_PASSWORD_ENV} is required")

    with SessionLocal() as session:
        result = seed_benchmark_users(
            session,
            count=args.count,
            email_prefix=args.email_prefix,
            email_domain=args.email_domain,
            password=args.password,
        )
        session.commit()

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def seed_benchmark_users(
    session: Session,
    *,
    count: int,
    email_prefix: str,
    email_domain: str,
    password: str,
) -> dict:
    now = datetime.now(UTC)
    emails = _benchmark_emails(count, email_prefix, email_domain)
    _clear_global_fixture_context(session)
    existing_users = list(session.scalars(select(User).where(User.email.in_(emails))))
    _clear_user_context(session, [int(user.id) for user in existing_users])

    products = _load_products(session, count)
    metadata = _load_product_metadata(session, products)
    version = _ensure_skin_test_version(session, now)

    reviewed_product_ids: set[int] = set()
    users: list[User] = []
    for index, email in enumerate(emails, start=1):
        user = _upsert_user(session, email=email, index=index, password=password, now=now)
        users.append(user)
        variant = SKIN_VARIANTS[(index - 1) % len(SKIN_VARIANTS)]
        baumann_profile = _ensure_baumann_profile(session, variant, index=index, now=now)
        _create_skin_context(
            session,
            user=user,
            variant=variant,
            version=version,
            baumann_profile=baumann_profile,
            index=index,
            now=now,
        )
        reviewed_product_ids.update(
            _create_behavior_context(
                session,
                user=user,
                products=_pick_products(products, index=index, size=18),
                metadata=metadata,
                variant=variant,
                index=index,
                now=now,
            )
        )

    session.flush()
    for product_id in sorted(reviewed_product_ids):
        rollup_product_review_metrics(session, product_id=product_id, computed_at=now)

    return {
        "seeded_user_count": len(users),
        "emails": emails,
        "skin_profiles": len(users),
        "skin_test_results": len(users),
        "behavior_sources": ["wishlist", "cart", "purchase", "recent_view", "click", "review"],
    }


def _benchmark_emails(count: int, email_prefix: str, email_domain: str) -> list[str]:
    return [f"{email_prefix}_{index:02d}@{email_domain}" for index in range(1, count + 1)]


def _clear_user_context(session: Session, user_ids: list[int]) -> None:
    if not user_ids:
        return

    order_ids = select(Order.id).where(Order.user_id.in_(user_ids), Order.order_code.like("bench_full_%"))
    cart_ids = select(Cart.id).where(Cart.user_id.in_(user_ids))
    result_ids = select(SkinTestResult.id).where(
        SkinTestResult.user_id.in_(user_ids),
        SkinTestResult.result_code.like("bench_full_%"),
    )
    review_ids = select(ProductReview.id).where(
        ProductReview.user_id.in_(user_ids),
        ProductReview.review_code.like("bench_full_review_%"),
    )

    session.execute(delete(EventLog).where(EventLog.user_id.in_(user_ids)))
    session.execute(delete(ProductReviewProfileLabel).where(ProductReviewProfileLabel.review_id.in_(review_ids)))
    session.execute(
        delete(ProductReview).where(
            ProductReview.user_id.in_(user_ids),
            ProductReview.review_code.like("bench_full_review_%"),
        )
    )
    session.execute(delete(OrderFulfillmentEvent).where(OrderFulfillmentEvent.order_id.in_(order_ids)))
    session.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    session.execute(delete(Order).where(Order.id.in_(order_ids)))
    session.execute(delete(CartItem).where(CartItem.cart_id.in_(cart_ids)))
    session.execute(delete(Cart).where(Cart.id.in_(cart_ids)))
    session.execute(delete(Wishlist).where(Wishlist.user_id.in_(user_ids)))
    session.execute(delete(RecentView).where(RecentView.user_id.in_(user_ids)))
    session.execute(delete(SkinTestAnswer).where(SkinTestAnswer.result_id.in_(result_ids)))
    session.execute(delete(SkinTestResult).where(SkinTestResult.id.in_(result_ids)))
    session.execute(delete(SkinProfile).where(SkinProfile.user_id.in_(user_ids)))


def _clear_global_fixture_context(session: Session) -> None:
    order_ids = select(Order.id).where(Order.order_code.like("bench_full_%"))
    result_ids = select(SkinTestResult.id).where(SkinTestResult.result_code.like("bench_full_%"))
    review_ids = select(ProductReview.id).where(ProductReview.review_code.like("bench_full_review_%"))

    session.execute(delete(EventLog).where(EventLog.event_id.like("bench_full_%")))
    session.execute(delete(ProductReviewProfileLabel).where(ProductReviewProfileLabel.review_id.in_(review_ids)))
    session.execute(delete(ProductReview).where(ProductReview.review_code.like("bench_full_review_%")))
    session.execute(delete(OrderFulfillmentEvent).where(OrderFulfillmentEvent.order_id.in_(order_ids)))
    session.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    session.execute(delete(Order).where(Order.id.in_(order_ids)))
    session.execute(delete(SkinTestAnswer).where(SkinTestAnswer.result_id.in_(result_ids)))
    session.execute(delete(SkinTestResult).where(SkinTestResult.id.in_(result_ids)))


def _upsert_user(session: Session, *, email: str, index: int, password: str, now: datetime) -> User:
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        session.add(user)

    user.display_name = f"benchmark_full_{index:02d}"
    user.status = "ACTIVE"
    user.role = "USER"
    user.updated_at = now
    session.flush()

    account = session.scalar(
        select(AuthAccount).where(
            AuthAccount.provider == "email",
            AuthAccount.provider_account_id == email,
        )
    )
    if account is None:
        account = AuthAccount(
            user_id=int(user.id),
            provider="email",
            provider_account_id=email,
        )
        session.add(account)

    account.user_id = int(user.id)
    account.provider_email = email
    account.password_hash = hash_password(password)
    account.password_updated_at = now
    account.is_verified = True
    account.updated_at = now
    return user


def _load_products(session: Session, count: int) -> list[Product]:
    limit = max(count * 24, 60)
    products = list(
        session.scalars(
            select(Product)
            .where(Product.is_active.is_(True), Product.is_recommendable.is_(True))
            .order_by(Product.id.asc())
            .limit(limit)
        )
    )
    if len(products) < 18:
        products = list(
            session.scalars(
                select(Product)
                .where(Product.is_active.is_(True))
                .order_by(Product.id.asc())
                .limit(limit)
            )
        )
    if len(products) < 18:
        raise SystemExit("At least 18 active products are required to seed benchmark users")
    return products


def _load_product_metadata(session: Session, products: list[Product]) -> dict[str, dict[int, str | int | None]]:
    product_ids = [int(product.id) for product in products]
    brand_ids = sorted({int(product.brand_id) for product in products})
    seller_ids = sorted({int(product.seller_id) for product in products})

    brand_names = {
        int(brand_id): name
        for brand_id, name in session.execute(select(Brand.id, Brand.name).where(Brand.id.in_(brand_ids)))
    }
    seller_names = {
        int(seller_id): display_name
        for seller_id, display_name in session.execute(
            select(Seller.id, Seller.display_name).where(Seller.id.in_(seller_ids))
        )
    }

    prices: dict[int, int] = {}
    for product_id, price in session.execute(
        select(ProductPrice.product_id, ProductPrice.price)
        .where(ProductPrice.product_id.in_(product_ids))
        .order_by(ProductPrice.product_id.asc(), ProductPrice.is_lowest.desc(), ProductPrice.price.asc())
    ):
        prices.setdefault(int(product_id), int(price))

    thumbnails: dict[int, str | None] = {}
    for product_id, storage_key in session.execute(
        select(ProductImage.product_id, ProductImage.storage_key)
        .where(ProductImage.product_id.in_(product_ids), ProductImage.image_type == "thumbnail")
        .order_by(ProductImage.product_id.asc(), ProductImage.display_order.asc())
    ):
        thumbnails.setdefault(int(product_id), storage_key)

    return {
        "brand_names": brand_names,
        "seller_names": seller_names,
        "prices": prices,
        "thumbnails": thumbnails,
    }


def _pick_products(products: list[Product], *, index: int, size: int) -> list[Product]:
    start = (index - 1) * 13
    return [products[(start + offset) % len(products)] for offset in range(size)]


def _ensure_skin_test_version(session: Session, now: datetime) -> SkinTestVersion:
    version = session.scalar(
        select(SkinTestVersion)
        .where(SkinTestVersion.status == "active")
        .order_by(SkinTestVersion.id.desc())
        .limit(1)
    )
    if version is not None:
        return version

    version = SkinTestVersion(
        version_code="benchmark_skin_test_v1",
        title="Benchmark skin test",
        description="Fixture version for full-personalized recommendation benchmarks.",
        question_count=8,
        scoring_version="benchmark_v1",
        status="active",
        published_at=now,
    )
    session.add(version)
    session.flush()
    return version


def _ensure_baumann_profile(
    session: Session,
    variant: dict,
    *,
    index: int,
    now: datetime,
) -> BaumannTypeProfile:
    type_code = str(variant["type_code"])
    profile = session.scalar(select(BaumannTypeProfile).where(BaumannTypeProfile.type_code == type_code))
    if profile is None:
        profile = BaumannTypeProfile(type_code=type_code)
        session.add(profile)

    profile.object_name = f"benchmark_{type_code.lower()}"
    profile.title = f"Benchmark {type_code}"
    profile.subtitle = "Full-personalized benchmark profile"
    profile.description = "Fixture profile for performance benchmark users."
    profile.mapped_skin_type = str(variant["skin_type"])
    profile.mapped_sensitivity = str(variant["sensitivity"])
    profile.concern_tags = list(variant["concerns"])
    profile.recommended_effect_ids = []
    profile.avoid_hints = []
    profile.keywords = [type_code.lower(), *variant["concerns"]]
    profile.display_order = index
    profile.is_active = True
    profile.updated_at = now
    session.flush()
    return profile


def _create_skin_context(
    session: Session,
    *,
    user: User,
    variant: dict,
    version: SkinTestVersion,
    baumann_profile: BaumannTypeProfile,
    index: int,
    now: datetime,
) -> None:
    axis_scores = _axis_scores(str(variant["type_code"]))
    commerce_profile = {
        "category_preference": {"code": variant["category_preference"]},
        "buying_criteria": {"code": variant["buying_criteria"]},
        "price_investment": {"code": variant["price_investment"]},
        "decision_trigger": {"code": variant["decision_trigger"]},
    }

    result = SkinTestResult(
        result_code=f"bench_full_result_{index:02d}",
        user_id=int(user.id),
        version_id=int(version.id),
        baumann_type_profile_id=int(baumann_profile.id),
        type_code=str(variant["type_code"]),
        mapped_skin_type=str(variant["skin_type"]),
        mapped_sensitivity=str(variant["sensitivity"]),
        axis_scores=axis_scores,
        commerce_profile=commerce_profile,
        recommended_effect_ids=[],
        avoid_hints=[],
        raw_score_payload={"source": "benchmark_full_personalized", "question_count": 8},
        applied_weight=Decimal("0.2500"),
        created_at=now,
        applied_at=now,
    )
    session.add(result)
    session.flush()

    profile = SkinProfile(
        user_id=int(user.id),
        skin_type=str(variant["skin_type"]),
        sensitivity=str(variant["sensitivity"]),
        skin_type_source="manual",
        sensitivity_source="manual",
        skin_type_confidence=Decimal("1.0000"),
        sensitivity_confidence=Decimal("1.0000"),
        explicit_skin_type=str(variant["skin_type"]),
        explicit_sensitivity=str(variant["sensitivity"]),
        avoid_ingredients=[],
        baumann_type_profile_id=int(baumann_profile.id),
        baumann_type_code=str(variant["type_code"]),
        baumann_inferred_skin_type=str(variant["skin_type"]),
        baumann_inferred_sensitivity=str(variant["sensitivity"]),
        baumann_signal_weight=Decimal("0.2500"),
        latest_skin_test_result_id=int(result.id),
        commerce_profile=commerce_profile,
        concern_profile_json={"concerns": list(variant["concerns"])},
        source="mixed",
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    session.flush()
    result.applied_profile_id = int(profile.id)


def _axis_scores(type_code: str) -> dict[str, dict[str, str]]:
    return {
        "OD": {"winner": type_code[0], "strength": "strong"},
        "SR": {"winner": type_code[1], "strength": "strong"},
        "PN": {"winner": type_code[2], "strength": "medium"},
        "WT": {"winner": type_code[3], "strength": "medium"},
    }


def _create_behavior_context(
    session: Session,
    *,
    user: User,
    products: list[Product],
    metadata: dict[str, dict[int, str | int | None]],
    variant: dict,
    index: int,
    now: datetime,
) -> set[int]:
    reviewed_product_ids: set[int] = set()

    for offset, product in enumerate(products[:6], start=1):
        session.add(Wishlist(user_id=int(user.id), product_id=int(product.id), added_at=now - timedelta(days=offset)))

    cart = Cart(user_id=int(user.id), status="ACTIVE", created_at=now - timedelta(hours=6), updated_at=now)
    session.add(cart)
    session.flush()
    for rank, product in enumerate(products[6:10], start=1):
        session.add(
            CartItem(
                cart_id=int(cart.id),
                product_id=int(product.id),
                seller_id=int(product.seller_id),
                quantity=1,
                unit_price_snapshot=_price(metadata, product),
                source="benchmark_full_personalized",
                recommendation_rank=rank,
                created_at=now - timedelta(hours=rank),
                updated_at=now - timedelta(hours=rank),
            )
        )

    for offset, product in enumerate(products[:14], start=1):
        viewed_at = now - timedelta(days=offset)
        session.add(
            RecentView(
                user_id=int(user.id),
                product_id=int(product.id),
                viewed_at=viewed_at,
                created_at=viewed_at,
                updated_at=viewed_at,
            )
        )

    order = _create_delivered_order(
        session,
        user=user,
        products=products[10:14],
        metadata=metadata,
        index=index,
        now=now,
    )
    session.flush()
    order_items = list(
        session.scalars(select(OrderItem).where(OrderItem.order_id == int(order.id)).order_by(OrderItem.id.asc()))
    )
    for review_index, order_item in enumerate(order_items[:2], start=1):
        reviewed_product_ids.add(int(order_item.product_id))
        _create_review(
            session,
            user=user,
            order_item=order_item,
            variant=variant,
            user_index=index,
            review_index=review_index,
            now=now,
        )

    _create_event_logs(session, user=user, products=products, cart=cart, order=order, index=index, now=now)
    return reviewed_product_ids


def _create_delivered_order(
    session: Session,
    *,
    user: User,
    products: list[Product],
    metadata: dict[str, dict[int, str | int | None]],
    index: int,
    now: datetime,
) -> Order:
    subtotal = sum(_price(metadata, product) for product in products)
    ordered_at = now - timedelta(days=21 + index)
    order = Order(
        order_code=f"bench_full_{index:02d}_01",
        user_id=int(user.id),
        idempotency_key=f"bench-full-{index:02d}-01",
        status="DELIVERED",
        subtotal_amount=subtotal,
        shipping_fee=0,
        discount_amount=0,
        total_amount=subtotal,
        item_count=len(products),
        total_quantity=len(products),
        ordered_at=ordered_at,
        paid_at=ordered_at + timedelta(minutes=1),
        shipped_at=ordered_at + timedelta(days=1),
        delivered_at=ordered_at + timedelta(days=3),
        created_at=ordered_at,
        updated_at=ordered_at + timedelta(days=3),
    )
    session.add(order)
    session.flush()

    for rank, product in enumerate(products, start=1):
        price = _price(metadata, product)
        session.add(
            OrderItem(
                order_id=int(order.id),
                product_id=int(product.id),
                seller_id=int(product.seller_id),
                product_name_snapshot=product.product_name,
                brand_name_snapshot=_brand_name(metadata, product),
                seller_name_snapshot=_seller_name(metadata, product),
                thumbnail_storage_key_snapshot=_thumbnail(metadata, product),
                unit_price=price,
                quantity=1,
                line_subtotal=price,
                line_discount_amount=0,
                line_total=price,
                status="DELIVERED",
                source="benchmark_full_personalized",
                recommendation_rank=rank,
                created_at=ordered_at,
                updated_at=ordered_at + timedelta(days=3),
            )
        )
    return order


def _create_review(
    session: Session,
    *,
    user: User,
    order_item: OrderItem,
    variant: dict,
    user_index: int,
    review_index: int,
    now: datetime,
) -> None:
    review_code = f"bench_full_review_{user_index:02d}_{review_index:02d}"
    review = ProductReview(
        review_code=review_code,
        product_id=int(order_item.product_id),
        user_id=int(user.id),
        order_item_id=int(order_item.id),
        source=FIRST_PARTY_REVIEW_SOURCE,
        source_review_id=review_code,
        status="PUBLISHED",
        review_type="MONTH_USE" if review_index == 2 else "GENERAL",
        rating=5 if review_index == 1 else 4,
        review_text="Benchmark review for full personalized recommendation performance.",
        reviewed_at=now - timedelta(days=review_index),
        option_text=None,
        is_repurchase_review=review_index == 2,
        verified_purchase=True,
        helpful_count=review_index,
        source_has_photo=False,
        profile_mapping_version=FIRST_PARTY_PROFILE_MAPPING_VERSION,
        published_at=now - timedelta(days=review_index),
        created_at=now - timedelta(days=review_index),
        updated_at=now - timedelta(days=review_index),
    )
    session.add(review)
    session.flush()
    session.add_all(_review_profile_labels(review_id=int(review.id), variant=variant))


def _review_profile_labels(*, review_id: int, variant: dict) -> list[ProductReviewProfileLabel]:
    labels: list[ProductReviewProfileLabel] = []
    skin_type = str(variant["skin_type"])
    sensitivity = str(variant["sensitivity"])
    skin_type_code = SKIN_TYPE_CODES.get(skin_type)
    sensitivity_code = SENSITIVITY_CODES.get(sensitivity)
    if skin_type_code:
        labels.append(_profile_label(review_id, "SKIN_TYPE", skin_type_code, skin_type, Decimal("1.0000")))
    if sensitivity_code:
        labels.append(_profile_label(review_id, "SENSITIVITY", sensitivity_code, sensitivity, Decimal("1.0000")))
    for concern in variant["concerns"][:2]:
        labels.append(_profile_label(review_id, "SKIN_CONCERN", str(concern), str(concern), Decimal("0.7500")))
    return labels


def _profile_label(
    review_id: int,
    dimension: str,
    value_code: str,
    source_label: str,
    confidence: Decimal,
) -> ProductReviewProfileLabel:
    return ProductReviewProfileLabel(
        review_id=review_id,
        dimension=dimension,
        value_code=value_code,
        source_label=source_label,
        mapping_source="benchmark_seed",
        mapping_confidence=confidence,
    )


def _create_event_logs(
    session: Session,
    *,
    user: User,
    products: list[Product],
    cart: Cart,
    order: Order,
    index: int,
    now: datetime,
) -> None:
    event_names = [
        "recommendation_product_click",
        "search_result_click",
        "home_product_click",
    ]
    for offset, product in enumerate(products[:12], start=1):
        session.add(
            EventLog(
                event_id=f"bench_full_{index:02d}_click_{offset:02d}",
                event_name=event_names[offset % len(event_names)],
                occurred_at=now - timedelta(hours=offset),
                user_id=int(user.id),
                session_id=f"bench-full-session-{index:02d}",
                request_id=f"bench-full-request-{index:02d}-{offset:02d}",
                recommendation_id=f"bench-full-rec-{index:02d}",
                product_id=product.product_code,
                rank=offset,
                source="benchmark_full_personalized",
                page="/recommendations",
                cart_id=int(cart.id) if offset <= 4 else None,
                order_id=int(order.id) if offset > 10 else None,
                metadata_json={"fixture": "full-personalized", "dataset_user_index": index},
            )
        )

    for offset, product in enumerate(products[14:16], start=1):
        session.add(
            EventLog(
                event_id=f"bench_full_{index:02d}_negative_{offset:02d}",
                event_name="wishlist_removed" if offset == 1 else "cart_removed",
                occurred_at=now - timedelta(days=offset),
                user_id=int(user.id),
                session_id=f"bench-full-session-{index:02d}",
                product_id=product.product_code,
                rank=offset,
                source="benchmark_full_personalized",
                page="/products",
                metadata_json={"fixture": "full-personalized", "negative": True},
            )
        )


def _price(metadata: dict[str, dict[int, str | int | None]], product: Product) -> int:
    return int(metadata["prices"].get(int(product.id)) or 10000)


def _brand_name(metadata: dict[str, dict[int, str | int | None]], product: Product) -> str:
    return str(metadata["brand_names"].get(int(product.brand_id)) or "Unknown brand")


def _seller_name(metadata: dict[str, dict[int, str | int | None]], product: Product) -> str:
    return str(metadata["seller_names"].get(int(product.seller_id)) or "Mubarelle")


def _thumbnail(metadata: dict[str, dict[int, str | int | None]], product: Product) -> str | None:
    value = metadata["thumbnails"].get(int(product.id))
    return str(value) if value else None


if __name__ == "__main__":
    main()
