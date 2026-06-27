from copy import deepcopy
from itertools import count
from typing import Any

from app.schemas.common import ApiError, dump_model
from app.schemas.product import ProductDetailResponse
from app.schemas.recommendation import (
    MatchedBrandConstraint,
    MatchedCategoryConstraint,
    PurchaseConstraints,
    RecommendedProduct,
    RecommendationRequest,
    RecommendationResponse,
    RecommendationSummary,
)
from app.services.purchase_conditions import ParsedPurchaseConditions
from app.services.recommendation_intent import build_recommendation_intent


ALLOWED_SKIN_TYPES = {"건성", "지성", "복합성", "중성", "수부지"}
ALLOWED_SENSITIVITIES = {"낮음", "보통", "높음", "민감"}

DEFAULT_SKIN_TYPE = "중성"
DEFAULT_SENSITIVITY = "보통"

_id_sequence = count(1)
_recommendations: dict[str, RecommendationResponse] = {}

_RECOMMENDED_PRODUCTS: list[dict[str, Any]] = [
    {
        "product_id": "mock-calming-cream",
        "brand_code": "닥터지",
        "category_code": "cream",
        "rank": 1,
        "total_score": 92,
        "reason_summary": "판테놀과 세라마이드 조합으로 건조감과 자극 완화 근거가 가장 잘 맞습니다.",
        "brand": "닥터지",
        "name": "판테놀 카밍 수분 크림",
        "thumbnail_url": "https://placehold.co/320x320/f6f8fa/111827?text=Calming+Cream",
        "lowest_price": 18900,
        "evidence_tags": ["진정", "장벽", "보습"],
        "key_ingredients": ["판테놀", "세라마이드엔피", "글리세린"],
        "score_breakdown": {
            "ingredient_effect_score": 32,
            "ingredient_evidence_score": 24,
            "skin_type_score": 17,
            "price_score": 12,
            "search_match_score": 9,
            "risk_penalty": -2,
        },
    },
    {
        "product_id": "mock-pore-serum",
        "brand_code": "스킨푸드",
        "category_code": "serum",
        "rank": 2,
        "total_score": 86,
        "reason_summary": "나이아신아마이드와 녹차추출물이 모공, 피지 고민 키워드와 잘 연결됩니다.",
        "brand": "스킨푸드",
        "name": "나이아신아마이드 포어 세럼",
        "thumbnail_url": "https://placehold.co/320x320/f3fbf7/111827?text=Pore+Serum",
        "lowest_price": 21900,
        "evidence_tags": ["피지", "모공", "결 정돈"],
        "key_ingredients": ["나이아신아마이드", "녹차추출물", "알란토인"],
        "score_breakdown": {
            "ingredient_effect_score": 30,
            "ingredient_evidence_score": 22,
            "skin_type_score": 15,
            "price_score": 10,
            "search_match_score": 11,
            "risk_penalty": -2,
        },
    },
    {
        "product_id": "mock-aha-toner",
        "brand_code": "라운드랩",
        "category_code": "toner",
        "rank": 3,
        "total_score": 78,
        "reason_summary": "저농도 AHA/PHA 조합으로 각질과 좁쌀 고민에 대한 보조 후보입니다.",
        "brand": "라운드랩",
        "name": "PHA 데일리 토너",
        "thumbnail_url": "https://placehold.co/320x320/f8f5ff/111827?text=PHA+Toner",
        "lowest_price": 15400,
        "evidence_tags": ["각질", "결 정돈", "저자극"],
        "key_ingredients": ["글루코노락톤", "락틱애씨드", "베타인"],
        "score_breakdown": {
            "ingredient_effect_score": 26,
            "ingredient_evidence_score": 19,
            "skin_type_score": 14,
            "price_score": 13,
            "search_match_score": 8,
            "risk_penalty": -2,
        },
    },
]

_PRODUCT_DETAILS: dict[str, dict[str, Any]] = {
    "mock-calming-cream": {
        "product": {
            "product_id": "mock-calming-cream",
            "brand": "닥터지",
            "name": "판테놀 카밍 수분 크림",
            "thumbnail_url": "https://placehold.co/320x320/f6f8fa/111827?text=Calming+Cream",
            "lowest_price": 18900,
        },
        "images": [
            {
                "url": "https://placehold.co/720x720/f6f8fa/111827?text=Calming+Cream",
                "alt": "판테놀 카밍 수분 크림 대표 이미지",
            }
        ],
        "prices": [
            {
                "mall_name": "Mock Store",
                "price": 18900,
                "product_url": "https://example.com/mock/products/mock-calming-cream",
                "is_lowest": True,
            },
            {
                "mall_name": "Sample Mall",
                "price": 20500,
                "product_url": "https://example.com/mock/products/mock-calming-cream/sample",
                "is_lowest": False,
            },
        ],
        "ingredients": [
            {"name": "판테놀", "purpose": "피부 진정과 보습 보조"},
            {"name": "세라마이드엔피", "purpose": "피부 장벽 보조"},
            {"name": "글리세린", "purpose": "보습"},
        ],
        "evidence": {
            "ingredient_evidence": [
                {
                    "ingredient": "판테놀",
                    "effect": "진정/보습",
                    "description": "건조감과 일시적 자극 완화 후보 성분으로 분류했습니다.",
                    "source_title": "Mock ingredient evidence",
                },
                {
                    "ingredient": "세라마이드엔피",
                    "effect": "장벽",
                    "description": "피부 장벽 보조 후보 성분으로 분류했습니다.",
                    "source_title": "Mock ingredient evidence",
                },
            ]
        },
        "sources": [
            {
                "title": "Mock ingredient evidence",
                "url": "https://example.com/mock/sources/ingredient-evidence",
                "source_type": "mock",
            }
        ],
    },
    "mock-pore-serum": {
        "product": {
            "product_id": "mock-pore-serum",
            "brand": "스킨푸드",
            "name": "나이아신아마이드 포어 세럼",
            "thumbnail_url": "https://placehold.co/320x320/f3fbf7/111827?text=Pore+Serum",
            "lowest_price": 21900,
        },
        "images": [
            {
                "url": "https://placehold.co/720x720/f3fbf7/111827?text=Pore+Serum",
                "alt": "나이아신아마이드 포어 세럼 대표 이미지",
            }
        ],
        "prices": [
            {
                "mall_name": "Mock Store",
                "price": 21900,
                "product_url": "https://example.com/mock/products/mock-pore-serum",
                "is_lowest": True,
            }
        ],
        "ingredients": [
            {"name": "나이아신아마이드", "purpose": "피지/피부결 보조"},
            {"name": "녹차추출물", "purpose": "진정 보조"},
            {"name": "알란토인", "purpose": "피부 진정 보조"},
        ],
        "evidence": {
            "ingredient_evidence": [
                {
                    "ingredient": "나이아신아마이드",
                    "effect": "피지/피부결",
                    "description": "피지와 모공 고민 후보 성분으로 분류했습니다.",
                    "source_title": "Mock ingredient evidence",
                }
            ]
        },
        "sources": [
            {
                "title": "Mock ingredient evidence",
                "url": "https://example.com/mock/sources/ingredient-evidence",
                "source_type": "mock",
            }
        ],
    },
    "mock-aha-toner": {
        "product": {
            "product_id": "mock-aha-toner",
            "brand": "라운드랩",
            "name": "PHA 데일리 토너",
            "thumbnail_url": "https://placehold.co/320x320/f8f5ff/111827?text=PHA+Toner",
            "lowest_price": 15400,
        },
        "images": [
            {
                "url": "https://placehold.co/720x720/f8f5ff/111827?text=PHA+Toner",
                "alt": "PHA 데일리 토너 대표 이미지",
            }
        ],
        "prices": [
            {
                "mall_name": "Mock Store",
                "price": 15400,
                "product_url": "https://example.com/mock/products/mock-aha-toner",
                "is_lowest": True,
            }
        ],
        "ingredients": [
            {"name": "글루코노락톤", "purpose": "각질 케어 보조"},
            {"name": "락틱애씨드", "purpose": "피부결 정돈 보조", "risk_note": "민감도가 높으면 주의"},
            {"name": "베타인", "purpose": "보습"},
        ],
        "evidence": {
            "ingredient_evidence": [
                {
                    "ingredient": "글루코노락톤",
                    "effect": "각질",
                    "description": "저자극 각질 케어 후보 성분으로 분류했습니다.",
                    "source_title": "Mock ingredient evidence",
                }
            ]
        },
        "sources": [
            {
                "title": "Mock ingredient evidence",
                "url": "https://example.com/mock/sources/ingredient-evidence",
                "source_type": "mock",
            }
        ],
    },
}


def create_recommendation(request: RecommendationRequest) -> RecommendationResponse:
    concern_text = _normalize_concern_text(request.concern_text)
    skin_type = _normalize_choice(
        request.skin_type,
        DEFAULT_SKIN_TYPE,
        ALLOWED_SKIN_TYPES,
        "피부 타입 값이 올바르지 않습니다.",
    )
    sensitivity = _normalize_choice(
        request.sensitivity,
        DEFAULT_SENSITIVITY,
        ALLOWED_SENSITIVITIES,
        "민감도 값이 올바르지 않습니다.",
    )
    avoid_ingredients = _normalize_avoid_ingredients(request.avoid_ingredients)

    intent = build_recommendation_intent(concern_text)
    products = _build_recommended_products(avoid_ingredients, intent.purchase_conditions)

    recommendation_id = f"rec_{next(_id_sequence):06d}"
    response = RecommendationResponse(
        recommendation_id=recommendation_id,
        summary=RecommendationSummary(
            concern_text=concern_text,
            skin_type=skin_type,
            sensitivity=sensitivity,
            avoid_ingredients=avoid_ingredients,
            matched_concerns=list(intent.matched_concern_names),
            expected_effects=list(intent.expected_effect_names),
            purchase_constraints=_build_purchase_constraints(intent.purchase_conditions),
        ),
        unmatched_terms=list(intent.unmatched_terms),
        products=products,
    )
    _recommendations[recommendation_id] = response
    return response


def get_recommendation(recommendation_id: str) -> RecommendationResponse:
    recommendation = _recommendations.get(recommendation_id)
    if recommendation is None:
        raise ApiError(404, "NOT_FOUND", "추천 결과를 찾을 수 없습니다.")
    return recommendation


def get_product_detail(
    product_id: str,
    recommendation_id: str | None = None,
) -> ProductDetailResponse:
    detail = _PRODUCT_DETAILS.get(product_id)
    if detail is None:
        raise ApiError(404, "NOT_FOUND", "상품을 찾을 수 없습니다.")

    recommendation = None
    if recommendation_id:
        recommendation = get_recommendation(recommendation_id)

    payload = deepcopy(detail)
    if recommendation is not None:
        recommended_product = _find_recommended_product(recommendation, product_id)
        if recommended_product is not None:
            payload["product"].update(
                {
                    "total_score": recommended_product.total_score,
                    "reason_summary": recommended_product.reason_summary,
                    "score_breakdown": dump_model(recommended_product.score_breakdown),
                }
            )
            payload["evidence"]["recommendation_reason"] = recommended_product.reason_summary

    return ProductDetailResponse(**payload)


def _normalize_concern_text(value: str | None) -> str:
    concern_text = (value or "").strip()
    if not concern_text:
        raise ApiError(400, "INVALID_INPUT", "고민 텍스트는 필수입니다.")
    if len(concern_text) > 100:
        raise ApiError(400, "INVALID_INPUT", "고민 텍스트는 100자 이하로 입력해 주세요.")
    return concern_text


def _normalize_choice(
    value: str | None,
    default: str,
    allowed_values: set[str],
    error_message: str,
) -> str:
    if value is None or not value.strip():
        return default

    normalized = value.strip()
    if normalized not in allowed_values:
        raise ApiError(400, "INVALID_INPUT", error_message)
    return normalized


def _normalize_avoid_ingredients(value: list[str] | None) -> list[str]:
    if value is None:
        return []
    return [ingredient.strip() for ingredient in value if ingredient.strip()]


def _analyze_concern(concern_text: str) -> tuple[list[str], list[str], list[str]]:
    rules = [
        (("건조", "속건조", "당김"), "건조", ["보습", "장벽"]),
        (("민감", "따가움", "자극"), "민감", ["진정", "저자극"]),
        (("모공", "피지", "번들"), "모공/피지", ["피지 조절", "피부결"]),
        (("좁쌀", "여드름", "트러블"), "트러블", ["진정", "각질 케어"]),
    ]

    matched_concerns: list[str] = []
    expected_effects: list[str] = []
    for keywords, concern, effects in rules:
        if any(keyword in concern_text for keyword in keywords):
            matched_concerns.append(concern)
            expected_effects.extend(effects)

    if not matched_concerns:
        return ["기본 추천"], ["보습", "진정"], [concern_text]

    return matched_concerns, list(dict.fromkeys(expected_effects)), []


def _build_recommended_products(
    avoid_ingredients: list[str],
    purchase_conditions: ParsedPurchaseConditions,
) -> list[RecommendedProduct]:
    normalized_avoid = {ingredient.lower() for ingredient in avoid_ingredients}
    products = []
    for product in _RECOMMENDED_PRODUCTS:
        key_ingredients = {ingredient.lower() for ingredient in product["key_ingredients"]}
        if normalized_avoid.intersection(key_ingredients):
            continue
        if not _matches_purchase_conditions(product, purchase_conditions):
            continue
        products.append(RecommendedProduct(**product))

    for rank, product in enumerate(products, start=1):
        product.rank = rank
    return products


def _matches_purchase_conditions(
    product: dict[str, Any],
    purchase_conditions: ParsedPurchaseConditions,
) -> bool:
    if purchase_conditions.categories:
        allowed_categories = {category.category_code for category in purchase_conditions.categories}
        if product.get("category_code") not in allowed_categories:
            return False

    if purchase_conditions.brands:
        allowed_brands = {brand.brand_code for brand in purchase_conditions.brands}
        if product.get("brand_code") not in allowed_brands:
            return False

    lowest_price = int(product["lowest_price"])
    if purchase_conditions.price_min is not None and lowest_price < purchase_conditions.price_min:
        return False
    if purchase_conditions.price_max is not None and lowest_price > purchase_conditions.price_max:
        return False

    return True


def _build_purchase_constraints(parsed: ParsedPurchaseConditions) -> PurchaseConstraints:
    return PurchaseConstraints(
        categories=[
            MatchedCategoryConstraint(
                category_code=category.category_code,
                name=category.name,
                matched_text=category.matched_text,
            )
            for category in parsed.categories
        ],
        brands=[
            MatchedBrandConstraint(
                brand_code=brand.brand_code,
                name=brand.name,
                matched_text=brand.matched_text,
            )
            for brand in parsed.brands
        ],
        price_min=parsed.price_min,
        price_max=parsed.price_max,
        price_text=parsed.price_text,
        price_max_text=parsed.price_max_text,
    )


def _find_recommended_product(
    recommendation: RecommendationResponse,
    product_id: str,
) -> RecommendedProduct | None:
    for product in recommendation.products:
        if product.product_id == product_id:
            return product
    return None
