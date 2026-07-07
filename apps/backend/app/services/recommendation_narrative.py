import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.ai_logging import extract_chat_completion_usage_from_body, log_ai_call
from app.core.config import settings
from app.core.performance_logging import current_time, elapsed_ms
from app.schemas.common import ApiError
from app.schemas.recommendation import (
    RecommendationNarrative,
    RecommendationNarrativeCard,
    RecommendationNarrativeDetailSection,
    RecommendationNarrativeOverview,
    RecommendationNarrativeProduct,
    RecommendationNarrativeRequest,
    RecommendationNarrativeResponse,
    RecommendationResponse,
    RecommendedProduct,
)
from app.services.recommendation_pipeline import MAX_PAGE_SIZE, get_recommendation_response


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 30


class RecommendationNarrativeError(RuntimeError):
    pass


class RecommendationNarrativeGenerator(Protocol):
    def generate(
        self,
        recommendation: RecommendationResponse,
        *,
        mode: str,
        view: str,
        product_id: str | None,
    ) -> RecommendationNarrative:
        ...


@dataclass(frozen=True)
class RuleBasedRecommendationNarrativeGenerator:
    def generate(
        self,
        recommendation: RecommendationResponse,
        *,
        mode: str,
        view: str,
        product_id: str | None,
    ) -> RecommendationNarrative:
        if not recommendation.products:
            return _build_no_result_narrative(recommendation)

        products = _select_products_for_view(recommendation, view=view, product_id=product_id)
        include_detail = view in {"detail", "full"}
        return RecommendationNarrative(
            generation_source="rule_based",
            overview=_build_fallback_overview(recommendation),
            product_explanations=[
                _build_fallback_product_explanation(
                    product,
                    recommendation,
                    mode=mode,
                    include_detail=include_detail,
                )
                for product in products
            ],
            selection_guide=_build_fallback_selection_guide(products) if view == "full" else None,
        )


@dataclass(frozen=True)
class OpenAIRecommendationNarrativeGenerator:
    api_key: str = settings.openai_api_key
    model: str = settings.openai_model
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS

    def generate(
        self,
        recommendation: RecommendationResponse,
        *,
        mode: str,
        view: str,
        product_id: str | None,
    ) -> RecommendationNarrative:
        if not recommendation.products:
            return _build_no_result_narrative(recommendation)
        if not self.api_key:
            raise RecommendationNarrativeError("OPENAI_API_KEY is required for recommendation narrative generation.")
        if not self.model:
            raise RecommendationNarrativeError("OPENAI_MODEL is required for recommendation narrative generation.")

        payload = self._request_structured_output(
            recommendation=recommendation,
            mode=mode,
            view=view,
            product_id=product_id,
        )
        if view == "cards":
            return _build_cards_narrative_from_payload(payload, recommendation)
        if view == "detail":
            return _build_detail_narrative_from_payload(payload, recommendation)

        narrative = _NarrativePayload.model_validate(payload)
        _validate_product_ids([product.product_id for product in narrative.product_explanations], recommendation)
        return RecommendationNarrative(
            generation_source="llm",
            overview=RecommendationNarrativeOverview(
                headline=_polish_overview_headline(narrative.overview.headline, recommendation),
                summary=_polish_overview_summary(narrative.overview.summary, recommendation),
                key_points=[_soften_claim(item) for item in narrative.overview.key_points],
            ),
            product_explanations=[
                _build_llm_product_narrative(product)
                for product in narrative.product_explanations
            ],
            selection_guide=_soften_claim(narrative.selection_guide) if narrative.selection_guide else None,
        )

    def _request_structured_output(
        self,
        *,
        recommendation: RecommendationResponse,
        mode: str,
        view: str,
        product_id: str | None,
    ) -> object:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": _system_prompt_for_view(view)},
                    {
                        "role": "user",
                        "content": json.dumps(
                            _build_llm_input(
                                recommendation,
                                mode=mode,
                                view=view,
                                product_id=product_id,
                            ),
                            ensure_ascii=False,
                        ),
                    },
                ],
                "temperature": 0.45,
                "seed": 42,
                "max_completion_tokens": _max_completion_tokens_for_view(view),
                "response_format": {
                    "type": "json_schema",
                    "json_schema": _schema_for_view(view),
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            OPENAI_CHAT_COMPLETIONS_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        started_at = current_time()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            log_ai_call(
                "recommendation_narrative",
                model=self.model,
                duration_ms=elapsed_ms(started_at),
                success=False,
                error="HTTPError",
                metadata={
                    "status_code": exc.code,
                    "view": view,
                    "mode": mode,
                },
            )
            raise RecommendationNarrativeError(
                f"OpenAI recommendation narrative request failed with status {exc.code}: "
                f"{_shorten(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            log_ai_call(
                "recommendation_narrative",
                model=self.model,
                duration_ms=elapsed_ms(started_at),
                success=False,
                error=type(exc.reason).__name__ if getattr(exc, "reason", None) is not None else "URLError",
                metadata={"view": view, "mode": mode},
            )
            raise RecommendationNarrativeError(f"OpenAI recommendation narrative request failed: {exc}") from exc

        log_ai_call(
            "recommendation_narrative",
            model=self.model,
            duration_ms=elapsed_ms(started_at),
            usage=extract_chat_completion_usage_from_body(body),
            metadata={
                "view": view,
                "mode": mode,
                "product_count": len(recommendation.products),
                "has_product_focus": product_id is not None,
            },
        )
        return _extract_chat_completion_json(body)


@dataclass(frozen=True)
class FallbackAwareRecommendationNarrativeGenerator:
    llm_generator: RecommendationNarrativeGenerator
    fallback_generator: RecommendationNarrativeGenerator

    def generate(
        self,
        recommendation: RecommendationResponse,
        *,
        mode: str,
        use_llm: bool,
        view: str,
        product_id: str | None,
    ) -> RecommendationNarrative:
        if not recommendation.products:
            return _build_no_result_narrative(recommendation)
        if use_llm:
            try:
                return self.llm_generator.generate(
                    recommendation,
                    mode=mode,
                    view=view,
                    product_id=product_id,
                )
            except Exception as exc:
                fallback = self.fallback_generator.generate(
                    recommendation,
                    mode=mode,
                    view=view,
                    product_id=product_id,
                )
                return _copy_narrative(
                    fallback,
                    fallback_reason=_shorten(str(exc), limit=240),
                )
        return self.fallback_generator.generate(
            recommendation,
            mode=mode,
            view=view,
            product_id=product_id,
        )


def create_recommendation_narrative_response(
    session: Session,
    recommendation_id: str,
    request: RecommendationNarrativeRequest | None = None,
) -> RecommendationNarrativeResponse:
    normalized_request = request or RecommendationNarrativeRequest()
    page_size = MAX_PAGE_SIZE if normalized_request.view == "detail" else normalized_request.product_limit
    recommendation = get_recommendation_response(
        session,
        recommendation_id,
        page=1,
        page_size=page_size,
    )
    narrative = get_default_recommendation_narrative_generator().generate(
        recommendation,
        mode=normalized_request.mode,
        use_llm=normalized_request.use_llm,
        view=normalized_request.view,
        product_id=normalized_request.product_id,
    )
    return RecommendationNarrativeResponse(
        recommendation_id=recommendation.recommendation_id,
        narrative=narrative,
    )


@lru_cache(maxsize=1)
def get_default_recommendation_narrative_generator() -> FallbackAwareRecommendationNarrativeGenerator:
    return FallbackAwareRecommendationNarrativeGenerator(
        llm_generator=OpenAIRecommendationNarrativeGenerator(),
        fallback_generator=RuleBasedRecommendationNarrativeGenerator(),
    )


def _select_products_for_view(
    recommendation: RecommendationResponse,
    *,
    view: str,
    product_id: str | None,
) -> list[RecommendedProduct]:
    if view != "detail":
        return recommendation.products

    if not product_id:
        raise ApiError(400, "INVALID_INPUT", "상세 설명을 만들 상품 id가 필요합니다.")

    for product in recommendation.products:
        if product.product_id == product_id:
            return [product]

    raise ApiError(404, "NOT_FOUND", "추천 결과에서 상품을 찾을 수 없습니다.")


def _build_cards_narrative_from_payload(
    payload: object,
    recommendation: RecommendationResponse,
) -> RecommendationNarrative:
    narrative = _NarrativeCardsPayload.model_validate(payload)
    _validate_product_ids([product.product_id for product in narrative.product_explanations], recommendation)
    actual_products = {product.product_id: product for product in recommendation.products}

    return RecommendationNarrative(
        generation_source="llm",
        overview=RecommendationNarrativeOverview(
            headline=_polish_overview_headline(narrative.overview.headline, recommendation),
            summary=_polish_overview_summary(narrative.overview.summary, recommendation),
            key_points=[_soften_claim(item) for item in narrative.overview.key_points],
        ),
        product_explanations=[
            _build_llm_card_narrative_product(product, actual_products[product.product_id])
            for product in narrative.product_explanations
        ],
        selection_guide=None,
    )


def _build_detail_narrative_from_payload(
    payload: object,
    recommendation: RecommendationResponse,
) -> RecommendationNarrative:
    narrative = _NarrativeDetailPayload.model_validate(payload)
    product = narrative.product_explanation
    _validate_product_ids([product.product_id], recommendation)
    actual_product = {item.product_id: item for item in recommendation.products}[product.product_id]

    return RecommendationNarrative(
        generation_source="llm",
        overview=_build_fallback_overview(recommendation),
        product_explanations=[
            _build_llm_product_narrative(
                product,
                actual_rank=actual_product.rank,
                actual_product=actual_product,
            )
        ],
        selection_guide=None,
    )


def _build_llm_card_narrative_product(
    product: "_NarrativeCardProductPayload",
    actual_product: RecommendedProduct,
) -> RecommendationNarrativeProduct:
    role = _polish_role(product.role)
    return RecommendationNarrativeProduct(
        product_id=product.product_id,
        rank=actual_product.rank,
        role=role,
        card=RecommendationNarrativeCard(
            headline=_polish_card_headline(product.card.headline, role),
            reason=_soften_claim(product.card.reason),
            chips=_clean_chips(product.card.chips, product=actual_product)
            or _fallback_chips_from_product(actual_product),
        ),
        detail_sections=[],
        caution=None,
    )


def _build_llm_product_narrative(
    product: "_NarrativeProductPayload",
    *,
    actual_rank: int | None = None,
    actual_product: RecommendedProduct | None = None,
) -> RecommendationNarrativeProduct:
    role = _polish_role(product.role)
    return RecommendationNarrativeProduct(
        product_id=product.product_id,
        rank=actual_rank or product.rank,
        role=role,
        card=RecommendationNarrativeCard(
            headline=_polish_card_headline(product.card.headline, role),
            reason=_soften_claim(product.card.reason),
            chips=_clean_chips(product.card.chips, product=actual_product)
            or _fallback_chips_from_product(actual_product),
        ),
        detail_sections=_clean_detail_sections(product.detail_sections),
        caution=_soften_claim(product.caution) if product.caution else None,
    )


def _build_no_result_narrative(recommendation: RecommendationResponse) -> RecommendationNarrative:
    constraints = recommendation.summary.purchase_constraints
    suggested_changes: list[str] = []
    if constraints.brands:
        suggested_changes.append("브랜드 조건을 잠깐 빼고 보기")
    if constraints.categories:
        suggested_changes.append("제품군을 넓혀서 보기")
    if constraints.price_max is not None:
        suggested_changes.append("가격 상한을 조금 올려 보기")
    if not suggested_changes:
        suggested_changes.append("고민 표현을 조금 더 구체적으로 적어 보기")

    return RecommendationNarrative(
        generation_source="rule_based",
        overview=RecommendationNarrativeOverview(
            headline="조건에 딱 맞는 후보가 아직 없어요",
            summary=(
                "입력한 조건을 그대로 지키면 보여줄 만한 상품이 없습니다. "
                "조건을 조금 넓히면 추천 후보를 다시 찾을 수 있어요."
            ),
            key_points=suggested_changes[:3],
        ),
        product_explanations=[],
        selection_guide="먼저 브랜드, 제품군, 가격 중 하나만 완화해서 다시 검색해보는 걸 추천해요.",
    )


def _build_fallback_overview(recommendation: RecommendationResponse) -> RecommendationNarrativeOverview:
    summary = recommendation.summary
    effects = ", ".join(summary.expected_effects[:3])
    concerns = ", ".join(summary.matched_concerns[:2])
    total_items = recommendation.pagination.total_items

    if concerns and effects:
        headline = f"{concerns} 고민은 {effects} 중심으로 봤어요"
    elif effects:
        headline = f"{effects} 근거가 있는 후보를 먼저 봤어요"
    else:
        headline = "입력 조건에 맞는 후보를 비교했어요"

    key_points: list[str] = []
    if effects:
        key_points.append(f"{effects}와 연결되는 성분 근거를 우선 반영")
    if summary.skin_type or summary.sensitivity:
        key_points.append(f"{summary.skin_type}/{summary.sensitivity} 기준 적합도 반영")
    if _has_purchase_constraints(summary.purchase_constraints):
        key_points.append("브랜드, 제품군, 가격 조건은 먼저 지키도록 처리")
    key_points.append(f"총 {total_items}개 후보 중 상위 상품을 먼저 설명")

    return RecommendationNarrativeOverview(
        headline=headline,
        summary=(
            f"총 {total_items}개 후보를 성분 근거, 피부 타입, 구매 조건 기준으로 정렬했어요. "
            "아래 설명은 그중 상위 후보를 빠르게 비교하기 위한 요약입니다."
        ),
        key_points=key_points[:4],
    )


def _build_fallback_product_explanation(
    product: RecommendedProduct,
    recommendation: RecommendationResponse,
    *,
    mode: str,
    include_detail: bool = True,
) -> RecommendationNarrativeProduct:
    effects = _effect_names_from_tags(product.evidence_tags)
    ingredients = product.key_ingredients[:3]
    role = _fallback_role(product, effects)
    chips = _build_fallback_chips(product, recommendation, effects)
    card_reason = _build_card_reason(product, effects, ingredients)
    detail_sections = (
        _build_detail_sections(product, recommendation, effects, ingredients)
        if include_detail
        else []
    )

    return RecommendationNarrativeProduct(
        product_id=product.product_id,
        rank=product.rank,
        role=role,
        card=RecommendationNarrativeCard(
            headline=_build_card_headline(product, role),
            reason=card_reason,
            chips=chips,
        ),
        detail_sections=detail_sections,
        caution=_fallback_caution(product, recommendation, mode=mode) if include_detail else None,
    )


def _build_fallback_selection_guide(products: list[RecommendedProduct]) -> str | None:
    if not products:
        return None
    if len(products) == 1:
        return "우선 이 후보의 핵심 성분과 주의 문구를 확인해보면 좋아요."
    return (
        "첫 상품은 전체 균형이 좋은 후보로 보고, "
        "두 번째 상품은 성분 구성과 사용감 조건을 비교해보면 좋아요."
    )


def _fallback_role(product: RecommendedProduct, effects: list[str]) -> str:
    if product.score_breakdown.concentration_bucket in {"optimal", "meaningful"}:
        return "함량 근거형"
    if product.score_breakdown.skin_type_score >= 80:
        return "피부 타입 적합형"
    if product.score_breakdown.price_score >= 90:
        return "가격 조건형"
    if effects:
        return f"{effects[0]} 집중형"
    return "균형형 후보"


def _build_card_headline(product: RecommendedProduct, role: str) -> str:
    if product.rank == 1:
        return f"가장 먼저 볼 만한 {role}"
    return f"비교해볼 만한 {role}"


def _build_card_reason(
    product: RecommendedProduct,
    effects: list[str],
    ingredients: list[str],
) -> str:
    if effects and ingredients:
        return f"{ingredients[0]} 중심으로 {effects[0]} 근거가 잡힌 후보예요."
    if ingredients:
        return f"{ingredients[0]} 성분 구성이 추천 점수에 반영됐어요."
    return "입력 조건과 상품 정보를 종합해 추천 후보로 골랐어요."


def _build_detail_sections(
    product: RecommendedProduct,
    recommendation: RecommendationResponse,
    effects: list[str],
    ingredients: list[str],
) -> list[RecommendationNarrativeDetailSection]:
    sections: list[RecommendationNarrativeDetailSection] = []
    concern_text = recommendation.summary.concern_text

    sections.append(
        RecommendationNarrativeDetailSection(
            title="고민과의 연결",
            body=(
                f"'{concern_text}' 입력에서 필요한 방향을 보고, "
                f"{', '.join(effects[:2]) if effects else '상품 조건'} 쪽 근거를 우선 확인했어요."
            ),
        )
    )

    if ingredients:
        sections.append(
            RecommendationNarrativeDetailSection(
                title="성분 근거",
                body=(
                    f"{', '.join(ingredients)} 성분이 추천 점수에 크게 반영됐어요. "
                    "성분명만 보고 고른 것이 아니라 효능 근거와 점수 기여도를 함께 봤어요."
                ),
            )
        )

    concentration_text = _concentration_reason(product)
    if concentration_text:
        sections.append(
            RecommendationNarrativeDetailSection(
                title="함량 체크",
                body=concentration_text,
            )
        )

    skin_text = _skin_reason(product, recommendation)
    if skin_text:
        sections.append(
            RecommendationNarrativeDetailSection(
                title="피부 타입",
                body=skin_text,
            )
        )

    return sections[:4]


def _build_fallback_chips(
    product: RecommendedProduct,
    recommendation: RecommendationResponse,
    effects: list[str],
) -> list[str]:
    chips: list[str] = []
    chips.extend(effects[:2])
    if product.score_breakdown.concentration_bucket in {"optimal", "meaningful"}:
        chips.append("함량 확인")
    if product.score_breakdown.skin_type_score >= 70:
        chips.append(f"{recommendation.summary.skin_type} 기준")
    if product.score_breakdown.price_score >= 90:
        chips.append("가격 조건")
    if product.score_breakdown.vector_score > 0:
        chips.append("의미 매칭")
    return _dedupe(chips)[:5]


def _fallback_chips_from_product(product: RecommendedProduct | None) -> list[str]:
    if product is None:
        return []
    chips = _effect_names_from_tags(product.evidence_tags)[:2]
    if product.score_breakdown.concentration_bucket in {"optimal", "meaningful"}:
        chips.append("함량 확인")
    if product.score_breakdown.skin_type_score >= 70:
        chips.append("피부타입")
    if product.score_breakdown.vector_score > 0:
        chips.append("의미 매칭")
    return _dedupe(chips)[:3]


def _concentration_reason(product: RecommendedProduct) -> str | None:
    bucket = product.score_breakdown.concentration_bucket
    if bucket == "optimal":
        return "공개 함량이 가장 보기 좋은 범위로 해석되어 더 높게 반영했어요."
    if bucket == "meaningful":
        return "공개 함량이 의미 있는 범위로 해석되어 성분명만 있는 제품보다 좋게 반영했어요."
    if bucket == "above_optimal":
        return "공개 함량이 적정 범위를 넘는 쪽이라 점수에는 보수적으로 반영했어요."
    if bucket == "excessive":
        return "공개 함량이 높은 편으로 해석되어 민감 피부라면 더 조심해서 보는 게 좋아요."
    return None


def _skin_reason(
    product: RecommendedProduct,
    recommendation: RecommendationResponse,
) -> str | None:
    score = product.score_breakdown.skin_type_score
    if score >= 80:
        return f"{recommendation.summary.skin_type} 피부 기준에서도 잘 맞는 후보로 봤어요."
    if score >= 60:
        return f"{recommendation.summary.skin_type} 피부 기준에서 무난한 후보로 봤어요."
    return None


def _fallback_caution(
    product: RecommendedProduct,
    recommendation: RecommendationResponse,
    *,
    mode: str,
) -> str | None:
    warning = product.score_breakdown.concentration_warning
    if warning:
        return warning
    if recommendation.summary.sensitivity == "민감":
        return "민감 피부라면 전성분 확인과 소량 테스트를 먼저 권장해요."
    if mode == "community_beta":
        return "개인 피부 상태에 따라 사용감은 다를 수 있어요. 구매 전 전성분을 한 번 더 확인해주세요."
    return None


def _build_llm_input(
    recommendation: RecommendationResponse,
    *,
    mode: str,
    view: str,
    product_id: str | None,
) -> dict:
    products = _select_products_for_view(recommendation, view=view, product_id=product_id)
    summary = recommendation.summary
    constraints = summary.purchase_constraints

    return {
        "mode": mode,
        "view": view,
        "user_context": {
            "concern_text": summary.concern_text,
            "skin_type": summary.skin_type,
            "sensitivity": summary.sensitivity,
            "matched_concerns": summary.matched_concerns[:4],
            "expected_effects": summary.expected_effects[:5],
            "avoid_ingredients": summary.avoid_ingredients[:5],
            "purchase_constraints": {
                "categories": [category.name for category in constraints.categories[:3]],
                "brands": [brand.name for brand in constraints.brands[:3]],
                "price_min": constraints.price_min,
                "price_max": constraints.price_max,
            },
        },
        "result_context": {
            "total_items": recommendation.pagination.total_items,
            "visible_items": len(products),
            "ranking_basis": ["성분 근거", "피부 타입", "구매 조건", "검색 매칭"],
        },
        "products": [_build_llm_product_fact(product) for product in products],
    }


def _build_llm_product_fact(product: RecommendedProduct) -> dict:
    score = product.score_breakdown
    return {
        "product_id": product.product_id,
        "rank": product.rank,
        "brand": product.brand,
        "name": product.name,
        "total_score": product.total_score,
        "lowest_price": product.lowest_price,
        "matched_effects": _effect_names_from_tags(product.evidence_tags)[:4],
        "key_ingredients": product.key_ingredients[:4],
        "reason_summary": _shorten(product.reason_summary, limit=120),
        "score_facts": {
            "ingredient_effect_score": score.ingredient_effect_score,
            "ingredient_evidence_score": score.ingredient_evidence_score,
            "functional_claim_score": score.functional_claim_score,
            "concentration_fit_score": score.concentration_fit_score,
            "concentration_bucket": score.concentration_bucket,
            "concentration_warning": score.concentration_warning,
            "skin_type_score": score.skin_type_score,
            "sensitivity_score": score.sensitivity_score,
            "price_score": score.price_score,
            "search_match_score": score.search_match_score,
            "risk_warnings": score.risk_warnings[:3],
        },
    }


def _has_purchase_constraints(constraints) -> bool:
    return bool(
        constraints.categories
        or constraints.brands
        or constraints.price_min is not None
        or constraints.price_max is not None
    )


def _effect_names_from_tags(tags: list[str]) -> list[str]:
    return _dedupe([tag.split(":", 1)[0] for tag in tags if tag])


def _polish_overview_headline(headline: str, recommendation: RecommendationResponse) -> str:
    normalized = _soften_claim(headline.strip())
    generic_keywords = ("추천 목록", "추천 제품", "제품 추천", "추천 크림 목록", "후보 목록")
    if normalized and not any(keyword in normalized for keyword in generic_keywords) and not normalized.endswith("추천"):
        return normalized

    summary = recommendation.summary
    concern = summary.matched_concerns[0] if summary.matched_concerns else ""
    effect = summary.expected_effects[0] if summary.expected_effects else ""
    category = summary.purchase_constraints.categories[0].name if summary.purchase_constraints.categories else "후보"

    if concern and effect:
        return f"{concern}에는 {effect} 기준으로 먼저 골랐어요"
    if effect:
        return f"{effect} 근거가 보이는 {category}를 먼저 골랐어요"
    return f"조건에 맞는 {category}를 먼저 추려봤어요"


def _polish_overview_summary(summary: str, recommendation: RecommendationResponse) -> str:
    normalized = _soften_claim(summary.strip())
    visible_count = len(recommendation.products)
    total_count = recommendation.pagination.total_items
    if total_count and visible_count and total_count != visible_count:
        wrong_count_phrases = (
            f"총 {visible_count}개의 제품",
            f"총 {visible_count}개 제품",
            f"총 {visible_count}개의 상품",
            f"총 {visible_count}개 상품",
            f"총 {visible_count}개의 후보",
            f"총 {visible_count}개 후보",
        )
        for phrase in wrong_count_phrases:
            normalized = normalized.replace(phrase, f"총 {total_count}개 후보")
    if total_count:
        normalized = normalized.replace(f"총 {total_count}개의 제품", f"총 {total_count}개 후보")
        normalized = normalized.replace(f"총 {total_count}개 제품", f"총 {total_count}개 후보")
        normalized = normalized.replace(f"총 {total_count}개의 상품", f"총 {total_count}개 후보")
        normalized = normalized.replace(f"총 {total_count}개 상품", f"총 {total_count}개 후보")
    if total_count and f"총 {total_count}개" not in normalized:
        normalized = f"총 {total_count}개 후보를 기준으로 봤어요. {normalized}"
    return normalized


def _polish_role(role: str) -> str:
    normalized = _soften_claim(role.strip())
    product_name_markers = (
        "크림",
        "세럼",
        "앰플",
        "토너",
        "스킨",
        "로션",
        "에센스",
        "밀크",
        "젤",
        "밤",
        "팩",
        "마스크",
    )
    generic_fragments = (
        "추천 제품",
        "추천 상품",
        "주요 추천",
        "좋은 제품",
        "좋은 상품",
        "먼저 볼 제품",
        "먼저 볼 상품",
    )
    looks_like_product_type = any(marker in normalized for marker in product_name_markers)
    looks_generic = any(fragment in normalized for fragment in generic_fragments)
    if not normalized or looks_like_product_type or looks_generic:
        return "근거 확인형"
    return normalized


def _polish_card_headline(headline: str, role: str) -> str:
    normalized = _soften_claim(headline.strip())
    polished_role = _polish_role(role) or "균형형 후보"
    product_name_markers = (
        "크림",
        "세럼",
        "앰플",
        "토너",
        "스킨",
        "로션",
        "에센스",
        "밀크",
        "젤",
        "밤",
        "팩",
        "마스크",
    )
    generic_keywords = ("추천", "제품", "상품")
    generic_fragments = ("추천 제품", "추천 상품", "주요 추천", "제품 추천", "상품 추천")
    looks_like_product_name = len(normalized) > 22 or any(marker in normalized for marker in product_name_markers)
    looks_generic = (
        normalized in generic_keywords
        or normalized.endswith("추천")
        or normalized.endswith("제품")
        or normalized.endswith("상품")
        or any(fragment in normalized for fragment in generic_fragments)
    )
    if not normalized or looks_like_product_name or looks_generic:
        return f"{polished_role}, 먼저 볼 만해요"
    return normalized


def _clean_chips(chips: list[str], *, product: RecommendedProduct | None = None) -> list[str]:
    cleaned: list[str] = []
    product_markers = (
        "크림",
        "세럼",
        "앰플",
        "토너",
        "스킨",
        "로션",
        "에센스",
        "밀크",
        "젤",
        "밤",
        "팩",
        "마스크",
    )
    for chip in chips:
        normalized = chip.split(":", 1)[0].strip()
        normalized = normalized.replace(" 효과", "").replace("효과", "").strip()
        has_unit_or_number = any(char.isdigit() for char in normalized) or any(
            unit in normalized.lower()
            for unit in ("ml", "g", "%", "호", "매", "개입")
        )
        looks_like_product = len(normalized) > 12 or any(marker in normalized for marker in product_markers)
        if product is not None:
            looks_like_product = (
                looks_like_product
                or normalized == product.brand
                or normalized in product.name
                or product.brand in normalized
            )
        if (
            normalized
            and normalized not in {"배지", "badge", "tag"}
            and not has_unit_or_number
            and not looks_like_product
        ):
            cleaned.append(normalized)
    return _dedupe(cleaned)[:5]


def _clean_detail_sections(
    sections: list["_NarrativeDetailSectionPayload"],
) -> list[RecommendationNarrativeDetailSection]:
    cleaned: list[RecommendationNarrativeDetailSection] = []
    skip_title_keywords = ("사용 방법", "사용법", "바르는 법", "루틴")
    for section in sections:
        title = _soften_claim(section.title)
        body = _soften_claim(section.body)
        if any(keyword in title for keyword in skip_title_keywords):
            continue
        cleaned.append(RecommendationNarrativeDetailSection(title=title, body=body))
    return cleaned


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _soften_claim(value: str) -> str:
    replacements = {
        "최적의": "먼저 볼 만한",
        "최적": "우선순위가 높은",
        "강력한": "주요",
        "해결해줄": "덜어내는 데 도움을 줄 수 있는",
        "해결할 수 있는": "덜어내는 데 도움을 줄 수 있는",
        "해결할": "신경 써볼 만한",
        "해결하고 싶다면": "신경 쓰인다면",
        "해결하는": "덜어내는 데 도움을 줄 수 있는",
        "해결하기 위해": "덜어내는 데 도움을 줄 수 있도록",
        "해결": "케어",
        "완화하는": "덜어내는 데 도움을 줄 수 있는",
        "완화할": "덜어내는 데 도움을 줄 수 있는",
        "완화에": "케어에",
        "완화": "케어",
        "효능이 뛰어난": "효능 근거가 보이는",
        "뛰어난": "근거가 보이는",
        "높은 점수를 기록": "상위 점수 후보로 확인",
        "즉각적인": "",
        "개선에": "케어에",
        "개선을": "케어를",
        "개선 을": "케어를",
        "개선이": "케어가",
        "개선할": "케어할",
        "개선하고": "케어하고",
        "개선하는": "케어하는",
        "개선": "케어",
        "효과적입니다": "도움을 줄 수 있는 근거로 봤어요",
        "효과적인": "도움을 줄 수 있는",
        "효과가 뛰어납니다": "도움을 줄 수 있는 근거로 봤어요",
        "효과로 잘 알려져 있으며": "근거로 반영되어",
        "효과를 제공합니다": "도움을 줄 수 있는 근거로 봤어요",
        "효과를 제공할 수 있습니다": "도움을 줄 수 있는 후보로 봤어요",
        "효과를 기대할 수 있습니다": "도움을 줄 수 있는 후보로 봤어요",
        "효과를 기대할 수 있어요": "도움을 줄 수 있는 후보로 봤어요",
        "효과도 기대할 수 있습니다": "근거도 함께 봤어요",
        "효과를 동시에 제공하여": "근거가 함께 반영되어",
        "효과적일 수 있습니다": "도움이 될 수 있는 근거로 봤어요",
        "효과에 도움": "케어에 도움",
        "진정 효과": "진정 근거",
        "보습 효과": "보습 근거",
        "성분과 효과": "성분 근거",
        "강화합니다": "강화에 도움을 줄 수 있는 근거로 봤어요",
        "피부 장벽을 강화하고 싶은": "피부 장벽 케어가 필요한",
        "강화에": "케어에",
        "강화": "케어",
        "강화하고": "케어하고",
        "진정시킵니다": "진정 쪽 근거로 봤어요",
        "진정시키는": "진정에 도움을 줄 수 있는",
        "진정시키고": "진정 쪽 근거가 있고",
        "진정시켜주며": "진정 쪽 근거가 있고",
        "피부를 진정 쪽 근거가 있고 수분을 도움을 줄 수 있어요": "피부 진정과 수분 유지 근거를 함께 봤어요",
        "피부를 진정 쪽 근거가 있고": "피부 진정 근거가 있고",
        "수분을 도움을": "수분 유지에 도움을",
        "공급하는 데 도움": "수분 공급에 도움",
        "피부 장벽을 장벽 케어 근거로 반영되고 싶은": "피부 장벽 케어가 필요한",
        "피부 장벽을 장벽 케어도 함께 보고": "피부 장벽 케어와",
        "피부의 장벽을 장벽 케어 근거로 반영되고": "피부 장벽 케어 근거가 반영되고",
        "추천된 제품": "추천 후보",
        "선정했습니다": "우선순위에 올렸어요",
        "선정되었습니다": "우선순위에 올렸어요",
        "추천합니다": "후보로 봤어요",
        "기여했습니다": "반영됐어요",
        "가장 크게": "크게",
        "효과적으로 유지할 수 있도록": "유지하는 데 도움을 줄 수 있도록",
        "기여합니다": "기여한 것으로 반영했어요",
        "작용합니다": "관련 근거로 반영했어요",
        "제공하는": "도움을 줄 수 있는",
        "제공합니다": "도움을 줄 수 있어요",
        "제공하여": "도움을 줄 수 있어",
        "깊은 보습을 제공하여": "보습에 도움을 줄 수 있어",
        "공급합니다": "공급 쪽 근거도 반영했어요",
        "수분을 공급 쪽 근거도 반영했어요": "수분 공급 근거도 함께 반영됐어요",
        "개선합니다": "개선 쪽 후보로 봤어요",
        "속건조를 케어합니다": "속건조 케어에 도움을 줄 수 있어요",
        "케어합니다": "케어에 도움을 줄 수 있어요",
        "도움을 줍니다": "도움을 줄 수 있어요",
        "도움을 줄 수 있습니다": "도움을 줄 수 있어요",
        "도움을 줄 수 있는 데 도움을 줄 수 있습니다": "도움이 될 수 있어요",
        "도움을 줄 수 있는 데 도움을 줄 수 있어요": "도움이 될 수 있어요",
        "도와줍니다": "도움을 줄 수 있어요",
        "줄여줍니다": "줄이는 데 도움을 줄 수 있어요",
        "강화하여": "케어하는 데 도움을 줄 수 있어",
        "보호합니다": "보호에 도움을 줄 수 있어요",
        "소개합니다": "정리했어요",
        "동시에 도움을": "함께 도움을",
        "보습을 도움을": "보습에 도움을",
        "진정 도움": "진정에 도움",
        "보습 도움": "보습에 도움",
        "효능 강조": "효능 근거 반영",
        "더해줍니다": "더해주는 근거로 봤어요",
        "해줍니다": "도움을 줄 수 있어요",
        "더도움을": "도움을",
        "성분 함량이 높아": "성분 정보가 반영되어",
        "함량이 높아": "함량 정보가 반영되어",
        "농도가 높은": "함량 정보가 있는",
        "자극이 적은 편입니다": "자극 가능성은 개인차가 있어요",
        "자극이 적은 편": "자극 가능성은 개인차가 있음",
        "함량은 확인되지 않았습니다": "공개 함량 정보는 제한적이에요",
        "속건조를 효과적으로 케어하는": "속건조 케어에 도움을 줄 수 있는",
        "효과적으로": "도움이 되도록",
        "권장합니다": "권장해요",
    }
    softened = value
    for source, target in replacements.items():
        softened = softened.replace(source, target)
    return softened.replace("!", "")


def _validate_product_ids(product_ids: list[str], recommendation: RecommendationResponse) -> None:
    allowed_product_ids = {product.product_id for product in recommendation.products}
    unknown_product_ids = [
        product_id
        for product_id in product_ids
        if product_id not in allowed_product_ids
    ]
    if unknown_product_ids:
        raise RecommendationNarrativeError(
            f"LLM recommendation narrative returned unknown product ids: {sorted(set(unknown_product_ids))}"
        )


def _extract_chat_completion_json(body: str) -> object:
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RecommendationNarrativeError("OpenAI recommendation narrative response was not valid JSON.") from exc

    choices = decoded.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RecommendationNarrativeError("OpenAI recommendation narrative response did not include choices.")

    message = choices[0].get("message", {})
    if isinstance(message, dict) and message.get("refusal"):
        raise RecommendationNarrativeError("OpenAI recommendation narrative refused the request.")

    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RecommendationNarrativeError("OpenAI recommendation narrative response did not include content.")

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RecommendationNarrativeError("OpenAI recommendation narrative content was not valid JSON.") from exc


def _shorten(value: str, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _copy_narrative(
    narrative: RecommendationNarrative,
    *,
    fallback_reason: str | None,
) -> RecommendationNarrative:
    update = {"fallback_reason": fallback_reason}
    if hasattr(narrative, "model_copy"):
        return narrative.model_copy(update=update)
    return narrative.copy(update=update)


class _NarrativeOverviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    summary: str
    key_points: list[str] = Field(min_length=1, max_length=4)


class _NarrativeCardPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    reason: str
    chips: list[str] = Field(max_length=5)


class _NarrativeCardProductPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    rank: int
    role: str
    card: _NarrativeCardPayload


class _NarrativeDetailSectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    body: str


class _NarrativeProductPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    rank: int
    role: str
    card: _NarrativeCardPayload
    detail_sections: list[_NarrativeDetailSectionPayload] = Field(min_length=2, max_length=4)
    caution: str


class _NarrativeCardsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overview: _NarrativeOverviewPayload
    product_explanations: list[_NarrativeCardProductPayload] = Field(min_length=1, max_length=10)


class _NarrativeDetailPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_explanation: _NarrativeProductPayload


class _NarrativePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overview: _NarrativeOverviewPayload
    product_explanations: list[_NarrativeProductPayload] = Field(min_length=1, max_length=10)
    selection_guide: str


def _system_prompt_for_view(view: str) -> str:
    if view == "cards":
        return _CARDS_SYSTEM_PROMPT
    if view == "detail":
        return _DETAIL_SYSTEM_PROMPT
    return _SYSTEM_PROMPT


def _schema_for_view(view: str) -> dict:
    if view == "cards":
        return _OPENAI_CARDS_SCHEMA
    if view == "detail":
        return _OPENAI_DETAIL_SCHEMA
    return _OPENAI_NARRATIVE_SCHEMA


def _max_completion_tokens_for_view(view: str) -> int:
    if view == "cards":
        return 900
    if view == "detail":
        return 700
    return 1800


_CARDS_SYSTEM_PROMPT = """
너는 화장품 추천 결과를 짧게 다듬는 UX 카피라이터다.
입력 facts에 없는 성분, 함량, 효능, 논문은 만들지 않는다.
치료/완치/보장/반드시/최적/강력한/효과적 같은 단정·과장 표현은 쓰지 않는다.
각 상품은 카드에 바로 보일 문구만 쓴다.
headline은 18자 이하, reason은 60자 이하, chips는 3개 이하로 쓴다.
role은 "추천 제품", "좋은 크림"처럼 쓰지 말고 "보습·장벽 집중형"처럼 선택 역할로 쓴다.
chips에는 용량(ml/g), 가격, 제품명 조각, "효과", "배지", "태그"를 쓰지 않는다.
상세 설명과 선택 가이드는 만들지 않는다.
한국어로 선명하고 자연스럽게 쓴다.
""".strip()


_DETAIL_SYSTEM_PROMPT = """
너는 화장품 추천 상세 화면의 설명을 쓰는 UX 카피라이터다.
입력 facts에 없는 성분, 함량, 효능, 논문은 만들지 않는다.
치료/완치/보장/반드시/최적/강력한/효과적 같은 단정·과장 표현은 쓰지 않는다.
상품 1개에 대해서만 상세 설명을 만든다.
detail_sections는 2~3개만 만들고, 각 body는 90자 이하로 쓴다.
role은 "추천 제품", "좋은 크림"처럼 쓰지 말고 "보습·장벽 집중형"처럼 선택 역할로 쓴다.
chips에는 용량(ml/g), 가격, 제품명 조각, "효과", "배지", "태그"를 쓰지 않는다.
입력 facts에 없는 사용 방법, 바르는 법, 루틴 설명은 만들지 않는다.
사용자 고민 연결, 성분 근거, 함량/피부타입/주의 중 입력 facts에 있는 내용만 쓴다.
한국어로 믿음직하지만 과장 없이 쓴다.
""".strip()


_SYSTEM_PROMPT = """
너는 화장품 추천 결과를 사용자가 믿고 고를 수 있게 설명하는 UX 카피라이터다.
추천 상품을 새로 판단하지 말고, 입력으로 받은 추천 결과와 점수 근거만 설명한다.

응답은 세 영역을 분리한다.
1. overview: 검색 결과 전체를 한눈에 이해시키는 설명. "총 후보를 어떤 기준으로 정렬했는지"를 말한다.
2. product.card: 결과 목록 바깥 카드에서 바로 보이는 짧고 눈에 띄는 설명. 1문장 중심으로 쓴다.
3. product.detail_sections: 상세 페이지에서 보여줄 깊은 설명. 고민 연결, 성분 근거, 함량/피부타입/주의를 나눠 쓴다.

overview 규칙:
- 전체 후보 수는 products 배열 길이가 아니라 pagination.total_items를 기준으로 말한다.
- "총 3개 제품"처럼 현재 설명 대상 개수만 전체 결과처럼 말하지 않는다.

금지:
- 없는 성분, 없는 함량, 없는 논문, 없는 효능을 만들지 않는다.
- 입력에 명시된 concentration_bucket 또는 concentration_warning이 없으면 "함량이 높다", "고농도"라고 말하지 않는다.
- "치료", "완치", "보장", "반드시 효과" 같은 의학적 단정 표현을 쓰지 않는다.
- "효과적입니다", "효과가 뛰어납니다"처럼 단정하지 않는다.
- "최적", "강력한", "확실한"처럼 과장된 표현을 쓰지 않는다.
- "배지"라는 단어를 사용자 문구에 쓰지 않는다.
- overview.headline에 "추천 목록", "추천 제품", "제품 추천"처럼 밋밋한 제목을 쓰지 않는다.
- product.card.headline에는 제품명을 그대로 쓰지 않는다. 사용자가 클릭하고 싶게 역할/강점을 제목으로 쓴다.

표현:
- "도움을 줄 수 있는 성분으로 반영했어요", "후보로 봤어요", "근거로 봤어요"처럼 부드럽게 쓴다.
- "효과", "제공", "개선"보다 "근거", "반영", "도움"을 우선 사용한다.
- chips는 화면에 작게 붙일 짧은 라벨이다. 예: "보습·장벽", "함량 확인", "건성 기준".
- chips에는 "효과", "배지", "태그"라는 말을 붙이지 않는다.
- role은 상품의 선택 역할이다. 예: "보습·장벽 집중형", "함량 근거형", "민감 피부 고려형".
- 한국어로 짧고 선명하게 쓴다.
""".strip()


_OPENAI_CARDS_SCHEMA = {
    "name": "recommendation_card_narrative",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "overview": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "headline": {"type": "string"},
                    "summary": {"type": "string"},
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                    },
                },
                "required": ["headline", "summary", "key_points"],
            },
            "product_explanations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "product_id": {"type": "string"},
                        "rank": {"type": "integer"},
                        "role": {"type": "string"},
                        "card": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "headline": {"type": "string"},
                                "reason": {"type": "string"},
                                "chips": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "maxItems": 3,
                                },
                            },
                            "required": ["headline", "reason", "chips"],
                        },
                    },
                    "required": ["product_id", "rank", "role", "card"],
                },
            },
        },
        "required": ["overview", "product_explanations"],
    },
}


_OPENAI_DETAIL_SCHEMA = {
    "name": "recommendation_detail_narrative",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "product_explanation": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "product_id": {"type": "string"},
                    "rank": {"type": "integer"},
                    "role": {"type": "string"},
                    "card": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "headline": {"type": "string"},
                            "reason": {"type": "string"},
                            "chips": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 3,
                            },
                        },
                        "required": ["headline", "reason", "chips"],
                    },
                    "detail_sections": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "body": {"type": "string"},
                            },
                            "required": ["title", "body"],
                        },
                    },
                    "caution": {"type": "string"},
                },
                "required": ["product_id", "rank", "role", "card", "detail_sections", "caution"],
            },
        },
        "required": ["product_explanation"],
    },
}


_OPENAI_NARRATIVE_SCHEMA = {
    "name": "recommendation_narrative",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "overview": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "headline": {"type": "string"},
                    "summary": {"type": "string"},
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 4,
                    },
                },
                "required": ["headline", "summary", "key_points"],
            },
            "product_explanations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "product_id": {"type": "string"},
                        "rank": {"type": "integer"},
                        "role": {"type": "string"},
                        "card": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "headline": {"type": "string"},
                                "reason": {"type": "string"},
                                "chips": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "maxItems": 5,
                                },
                            },
                            "required": ["headline", "reason", "chips"],
                        },
                        "detail_sections": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "title": {"type": "string"},
                                    "body": {"type": "string"},
                                },
                                "required": ["title", "body"],
                            },
                        },
                        "caution": {"type": "string"},
                    },
                    "required": [
                        "product_id",
                        "rank",
                        "role",
                        "card",
                        "detail_sections",
                        "caution",
                    ],
                },
            },
            "selection_guide": {"type": "string"},
        },
        "required": [
            "overview",
            "product_explanations",
            "selection_guide",
        ],
    },
}
