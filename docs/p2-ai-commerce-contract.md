# P2 AI-Commerce Handoff Contract

이 문서는 P2 1P 자사몰에서 규태 담당 FastAPI AI 추천/검색 영역과 원우 담당 Spring Commerce 영역이 맞물리는 최소 계약입니다.

## P2 목표

| 항목 | 결정 |
| --- | --- |
| 한 문장 | AI 추천 결과를 실제 구매 행동으로 연결할 수 있는 Spring 기반 1P 자사몰을 완성한다. |
| AI 책임 | 피부 고민/프로필을 받아 추천 결과, 추천 이유, 상품 상세 근거를 제공한다. |
| Commerce 책임 | 회원, 찜, 장바구니, checkout, 결제 mock, 주문, 재고, 관리자 출고를 처리한다. |
| 핵심 경계 | FastAPI는 추천을 계산하고, Spring은 구매 상태를 변경한다. |

## 현재 FastAPI 계약

| 흐름 | Endpoint | P2 용도 |
| --- | --- | --- |
| 추천 생성 | `POST /api/recommendations?page={page}&page_size={page_size}` | 피부 고민과 프로필로 추천 결과 생성 |
| 추천 조회 | `GET /api/recommendations/{recommendation_id}` | 생성된 추천 결과 재조회 |
| 추천 서사 | `POST /api/recommendations/{recommendation_id}/narrative` | `cards`, `detail`, `full` 뷰별 AI 설명 생성 |
| 상품 상세 | `GET /api/products/{product_id}?recommendation_id={recommendation_id}` | 추천 맥락이 포함된 상품 상세 근거 조회 |
| 홈 섹션 | `GET /api/home/sections` | P2 홈/탐색용 상품 섹션 |

## 공통 ID 계약

| ID | 소유 | 규칙 | P2 사용처 |
| --- | --- | --- | --- |
| `product_id` | 공통 데이터 | `data/products.csv`의 상품 고유 ID를 그대로 사용한다. | 추천 결과, 상품 상세, 찜, 장바구니 |
| `recommendation_id` | FastAPI | 추천 실행 1회당 생성되는 추적 ID다. | 추천 조회, 상품 상세 맥락, 장바구니 유입 출처 |
| `rank` | FastAPI | 추천 결과 내 순위다. | 카드 노출, 전환 추적 |
| `member_id` | Spring | 인증 사용자 ID다. FastAPI는 P2에서 직접 회원 상태를 소유하지 않는다. | 프로필 저장, 찜, 주문 |

## 추천 생성 요청

FastAPI는 P2에서 회원 DB를 직접 보지 않고, Spring 또는 프론트가 저장된 피부 프로필의 snapshot을 넘기는 방식으로 시작한다.

```json
{
  "concern_text": "모공이랑 속건조가 고민이에요",
  "skin_type": "수부지",
  "sensitivity": "보통",
  "avoid_ingredients": ["티트리"]
}
```

| 필드 | 필수 | 설명 |
| --- | --- | --- |
| `concern_text` | Y | 사용자 자연어 고민. 100자 이하 |
| `skin_type` | N | `건성`, `지성`, `복합성`, `중성`, `수부지` |
| `sensitivity` | N | `낮음`, `보통`, `높음`, `민감` |
| `avoid_ingredients` | N | 사용자가 피하고 싶은 성분명 목록 |

## 추천 결과 응답

Spring Commerce와 프론트는 추천 결과의 `product_id`, `recommendation_id`, `rank`만으로 상품 상세와 찜을 이어간다. 장바구니 추가는 각 상품의 `cart_handoff` 객체를 그대로 Spring에 전달한다.

```json
{
  "recommendation_id": "rec_000001",
  "products": [
    {
      "product_id": "prod_oy_a000000144918",
      "rank": 1,
      "total_score": 86,
      "reason_summary": "속건조와 장벽 고민에 맞는 성분 근거가 있습니다.",
      "brand": "브랜드명",
      "name": "상품명",
      "thumbnail_url": "https://...",
      "lowest_price": 12600,
      "evidence_tags": ["보습장벽", "진정"],
      "key_ingredients": ["나이아신아마이드", "판테놀"],
      "score_breakdown": {
        "ingredient_effect_score": 80,
        "ingredient_evidence_score": 70,
        "functional_claim_score": 0,
        "concentration_fit_score": 50,
        "concentration_bucket": null,
        "concentration_warning": null,
        "skin_profile_score": 0,
        "skin_type_score": 65,
        "sensitivity_score": 0,
        "price_score": 90,
        "keyword_score": 10,
        "vector_score": 0,
        "search_match_score": 20,
        "market_signal_score": 50,
        "skin_test_context_score": 50,
        "skin_test_context_applied": false,
        "skin_test_context_axes": {},
        "skin_test_context_matched_axes": [],
        "skin_test_context_query_conflict_axes": [],
        "skin_test_context_manual_conflict_axes": [],
        "base_weights": {
          "ingredient_effect": 0.32,
          "ingredient_evidence": 0.23,
          "skin_profile": 0.14,
          "concentration_fit": 0.08,
          "functional_claim": 0.05,
          "search_match": 0.07,
          "price": 0.04,
          "market_signal": 0.02,
          "skin_test_context": 0
        },
        "adjusted_weights": {
          "ingredient_effect": 0.336842,
          "ingredient_evidence": 0.242105,
          "skin_profile": 0.147368,
          "concentration_fit": 0.084211,
          "functional_claim": 0.052632,
          "search_match": 0.073684,
          "price": 0.042105,
          "market_signal": 0.021053,
          "skin_test_context": 0
        },
        "applied_multipliers": {
          "ingredient_effect": 1,
          "ingredient_evidence": 1,
          "skin_profile": 1,
          "concentration_fit": 1,
          "functional_claim": 1,
          "search_match": 1,
          "price": 1,
          "market_signal": 1,
          "skin_test_context": 1
        },
        "risk_penalty": 0,
        "risk_flag_count": 0,
        "risk_warnings": [],
        "risk_policy": null
      },
      "cart_handoff": {
        "product_id": "prod_oy_a000000144918",
        "quantity": 1,
        "source": "ai_recommendation",
        "recommendation_id": "rec_000001",
        "recommendation_rank": 1
      }
    }
  ]
}
```

| 필드 | Commerce 사용 여부 | 설명 |
| --- | --- | --- |
| `recommendation_id` | 사용 | 장바구니/주문 유입 출처 추적 |
| `product_id` | 사용 | Spring 상품/offer 조회 key |
| `rank` | 사용 | 추천 순위별 전환 분석 |
| `lowest_price` | 참고만 | 최종 가격은 Spring offer/재고 기준으로 다시 계산 |
| `total_score` | 표시/분석 | 구매 가격 계산에는 사용하지 않음 |
| `reason_summary` | 표시 | 추천 카드/상세 설명 |
| `score_breakdown` | 표시/디버그 | 관리자/발표용 근거 |
| `cart_handoff` | 사용 | 장바구니 추가 API로 넘길 추천 유입 payload |

## 상품 상세 연결

프론트는 추천 카드 클릭 시 추천 맥락을 보존해 상품 상세를 호출한다.

```text
GET /api/products/{product_id}?recommendation_id={recommendation_id}
```

FastAPI는 같은 상품이라도 추천 맥락이 있으면 `total_score`, `reason_summary`, `score_breakdown`, `cart_handoff`, `recommendation_reason`을 포함한다. 추천 맥락이 없는 일반 상품 상세에서는 `cart_handoff`를 `null`로 둔다.

## AI 설명 연결

추천 설명 생성은 같은 endpoint를 쓰되, 화면 위치에 따라 `view`를 나눈다.

```json
{
  "view": "cards",
  "product_limit": 5,
  "use_llm": true
}
```

```json
{
  "view": "detail",
  "product_id": "prod_oy_a000000144918",
  "use_llm": true
}
```

| `view` | P2 사용처 | 규칙 |
| --- | --- | --- |
| `cards` | 추천 결과 목록 | 여러 상품 카드용 짧은 설명 |
| `detail` | 상품 상세 | 선택한 `product_id` 1개에 대한 깊은 설명 |
| `full` | 호환/발표용 | 전체 설명을 한 번에 생성하는 호환 모드 |

프론트는 목록 카드에서는 `cards`, 상품 상세에서는 `detail`을 사용한다. Spring Commerce는 설명을 재생성하지 않고 FastAPI 응답을 표시/로그에 활용한다.

## 장바구니 handoff 계약

장바구니 추가는 Spring Commerce가 처리한다. FastAPI는 장바구니를 직접 변경하지 않고, 추천 응답에 `cart_handoff` 객체만 내려준다.

```json
{
  "product_id": "prod_oy_a000000144918",
  "quantity": 1,
  "source": "ai_recommendation",
  "recommendation_id": "rec_000001",
  "recommendation_rank": 1
}
```

프론트는 추천 결과 카드 또는 추천 맥락이 있는 상품 상세의 장바구니 버튼에서 `cart_handoff`를 그대로 Spring 장바구니 API에 전달한다.

| 필드 | 필수 | 소유 | 설명 |
| --- | --- | --- | --- |
| `product_id` | Y | 공통 | 추천 결과에서 받은 상품 ID |
| `quantity` | Y | Spring | P2 기본값은 1 |
| `source` | Y | Spring | `ai_recommendation`, `product_detail`, `wishlist` 중 하나 |
| `recommendation_id` | N | FastAPI | AI 추천 유입이면 포함 |
| `recommendation_rank` | N | FastAPI | AI 추천 유입이면 포함 |

Spring은 이 payload를 받은 뒤 `product_id` 기준으로 현재 판매 가능한 기본 offer, 가격, 재고를 다시 확인한다. 추천 시점 가격과 checkout 가격이 다르면 Spring 기준이 최종값이다.

## 상태와 이벤트 계약

| 이벤트 | 발생 주체 | 최소 payload |
| --- | --- | --- |
| `recommendation_submit` | Frontend/Spring | `member_id`, `concern_tags` |
| `recommendation_result_view` | Frontend/Spring | `member_id`, `recommendation_id` |
| `recommendation_product_impression` | Frontend/Spring | `member_id`, `recommendation_id`, `product_id`, `rank` |
| `recommendation_product_click` | Frontend/Spring | `member_id`, `recommendation_id`, `product_id`, `rank` |
| `product_detail_view` | Frontend/Spring | `member_id`, `product_id`, `recommendation_id` |
| `wishlist_added` | Spring | `member_id`, `product_id`, `source`, `recommendation_id` |
| `cart_item_added` | Spring | `member_id`, `product_id`, `quantity`, `source`, `recommendation_id` |
| `checkout_started` | Spring | `member_id`, `cart_id`, `order_draft_id` |
| `payment_mock_completed` | Spring | `member_id`, `order_id`, `payment_status` |
| `order_completed` | Spring | `member_id`, `order_id`, `order_status` |

## 에러 경계

| 상황 | 담당 | 권장 응답 |
| --- | --- | --- |
| 고민 텍스트 비어 있음 | FastAPI | `400 INVALID_INPUT` |
| 추천 결과 없음/만료 | FastAPI | `404 NOT_FOUND` 또는 `410 EXPIRED` |
| 상품 없음 | FastAPI/Spring | `404 NOT_FOUND` |
| 추천 상품이 판매 불가 | Spring | `409 PRODUCT_UNAVAILABLE` |
| 재고 부족 | Spring | `409 OUT_OF_STOCK` |
| mock 결제 실패 | Spring | `402 PAYMENT_FAILED` 또는 `409 PAYMENT_REJECTED` |

## 침범 금지선

| 역할 | 하지 않는 일 |
| --- | --- |
| FastAPI AI | 장바구니, 주문, 결제, 재고를 직접 생성/수정하지 않는다. |
| Spring Commerce | 성분 효능 점수, 추천 순위, 추천 이유를 다시 계산하지 않는다. |
| Frontend | 최종 가격, 재고, 주문 상태를 클라이언트에서 확정하지 않는다. |
| Data | 운영 DB에 직접 SQL을 넣지 않고 CSV/seed 경로를 우선한다. |

## 1주차 합의 체크리스트

| 항목 | 결정 필요자 | 결정 |
| --- | --- | --- |
| `product_id`를 Spring 상품 key로 그대로 쓸지 | 원우, 세민, 규태 | P2 기본값: 그대로 사용 |
| Spring 기본 offer 해석 기준 | 원우, 지현 | P2 기본값: Spring 내부에서 `product_id` 기준으로 처리 |
| 피부 프로필 전달 방식 | 원우, 지현, 규태 | Spring 저장 후 FastAPI 요청에는 snapshot 전달 |
| 추천 유입 장바구니 payload | 원우, 지현, 규태 | 이 문서의 handoff payload 사용 |
| 추천 결과 만료 정책 | 원우, 규태 | P2 기본값: 조회 가능하되 checkout 가격은 Spring 기준 |
| 이벤트 로그 최소 범위 | 지운, 원우, 규태 | `docs/analytics-event-roadmap.md`의 1차 이벤트와 이 문서의 구매 이벤트를 맞춘다. |

## P3 이후로 미룰 것

| 항목 | 미루는 이유 |
| --- | --- |
| AI agent가 직접 장바구니에 담기 | P2는 사용자가 버튼으로 구매 행동을 확정해야 한다. |
| 실시간 외부 가격 동기화 | P2는 seed/관리자 가격 기준으로 충분하다. |
| 다중 셀러 offer 경쟁 | P2는 1P 자사몰이므로 단일 판매자 기준이다. |
| 실제 PG 결제 | P2는 mock/sandbox 결제로 주문 완료 흐름을 보여준다. |
| Elasticsearch 운영 클러스터 | P2 검색/추천은 FastAPI DB/pgvector 기반으로 방어한다. |

## 완료 기준

- 추천 결과 카드에서 `product_id`, `recommendation_id`, `rank`가 보존된다.
- 상품 상세는 `recommendation_id`가 있을 때 추천 이유와 score breakdown을 보여준다.
- 장바구니 추가 요청은 추천 유입 정보를 Spring에 넘긴다.
- Spring은 cart/order/payment/admin 상태를 소유한다.
- FastAPI는 추천/검색/근거 설명만 소유한다.
