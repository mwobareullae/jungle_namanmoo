# P2 FastAPI Commerce Contract

이 문서는 P2 1P 자사몰 MVP에서 FastAPI 백엔드가 추천/검색과 구매 흐름을 함께 처리하기 위한 최소 계약입니다.
이전 초안의 Spring Commerce 분리 전제는 사용하지 않습니다. MVP는 FastAPI를 유지하고, 자사몰 구매 흐름까지 FastAPI 안에서 연결합니다.

## P2 목표

| 항목 | 결정 |
| --- | --- |
| 한 문장 | AI 추천 결과를 실제 자사몰 구매 행동으로 연결한다. |
| 추천 책임 | 피부 고민/프로필을 받아 추천 결과, 추천 이유, 상품 상세 근거를 제공한다. |
| 커머스 책임 | 회원, 찜, 장바구니, checkout, 결제 mock/Toss sandbox, 주문, 재고를 처리한다. |
| 핵심 경계 | 프론트는 화면과 사용자 입력을 맡고, FastAPI는 추천 계산과 구매 상태 변경을 서버에서 확정한다. |

## MVP API 계약

| 흐름 | Endpoint | P2 용도 |
| --- | --- | --- |
| 홈 섹션 | `GET /api/home/sections` | 첫 방문자용 콜드스타트 상품 섹션 |
| 추천 생성 | `POST /api/recommendations?page={page}&page_size={page_size}` | 피부 고민과 프로필로 추천 결과 생성 |
| 추천 조회 | `GET /api/recommendations/{recommendation_id}` | 생성된 추천 결과 재조회 |
| 추천 서사 | `POST /api/recommendations/{recommendation_id}/narrative` | `cards`, `detail`, `full` 뷰별 AI 설명 생성 |
| 상품 상세 | `GET /api/products/{product_id}?recommendation_id={recommendation_id}` | 추천 맥락이 포함된 상품 상세 근거 조회 |
| 찜 | `POST /api/wishlists/items`, `GET /api/wishlists/items`, `DELETE /api/wishlists/items/{product_id}` | 사용자의 관심 상품 저장 |
| 장바구니 | `POST /api/cart/items`, `GET /api/cart`, `PATCH /api/cart/items/{item_id}`, `DELETE /api/cart/items/{item_id}` | 구매 전 상품 수량과 유입 출처 보존 |
| Checkout preview | `POST /api/checkout/preview` | 주문 전 가격, 판매상태, 재고 재검증 |
| 주문 | `POST /api/orders`, `GET /api/orders/{order_id}` | 주문 생성과 주문 상세 조회 |
| 결제 | `POST /api/payments/mock/confirm`, `POST /api/payments/toss/confirm` | mock 결제와 Toss sandbox 결제 확인 |

아직 구현되지 않은 endpoint는 계약 기준입니다. 실제 개발 시 프론트와 맞추기 전에 request/response schema를 확정합니다.

## 공통 ID 계약

| ID | 소유 | 규칙 | P2 사용처 |
| --- | --- | --- | --- |
| `product_id` | 공통 데이터 | API에서는 `data/products.csv`의 상품 고유 ID 문자열을 그대로 사용한다. DB 내부 FK는 `products.id`를 사용한다. | 추천 결과, 상품 상세, 찜, 장바구니, 주문 item |
| `recommendation_id` | FastAPI | 추천 실행 1회당 생성되는 추적 ID다. | 추천 조회, 상품 상세 맥락, 장바구니/주문 유입 출처 |
| `rank` | FastAPI | 추천 결과 내 순위다. | 카드 노출, 전환 추적 |
| `seller_id` | FastAPI DB | MVP에서는 기본 seller `mwobareullae`에 모든 상품을 연결한다. API에 반드시 노출하지 않아도 된다. | 관리자/재고/주문 item snapshot |
| `user_id` | FastAPI Auth | 로그인 사용자의 내부 ID다. | 프로필, 찜, 장바구니, 주문 |

P2/MVP에서는 `offer_id`를 사용하지 않습니다. 상품은 `product_id` 기준으로 판매되고, 판매자 연결은 DB의 `products.seller_id`와 기본 seller로 처리합니다. 다중 셀러가 같은 상품을 경쟁 판매하는 구조가 생기면 그때 `offers`를 재검토합니다.

## 추천 생성 요청

FastAPI는 로그인 사용자의 저장된 피부 프로필을 사용할 수 있고, 비회원/임시 흐름에서는 프론트가 넘긴 snapshot을 사용할 수 있습니다.

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

프론트는 추천 결과의 `product_id`, `recommendation_id`, `rank`를 보존합니다. 커머스 행동이 필요하면 각 상품의 `commerce_handoff` 객체를 FastAPI 커머스 API에 전달합니다.

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
      "thumbnail_image": {
        "image_type": "thumbnail",
        "storage_key": "products/prod_oy_a000000144918/thumbnail_001.jpg",
        "display_order": 0
      },
      "purchase_info": {
        "price": 12600,
        "currency": "KRW",
        "sales_status": "ON_SALE",
        "stock_status": "IN_STOCK"
      },
      "evidence_tags": ["보습장벽", "진정"],
      "key_ingredients": ["나이아신아마이드", "판테놀"],
      "score_breakdown": {
        "ingredient_effect_score": 80,
        "ingredient_evidence_score": 70,
        "concentration_fit_score": 50,
        "skin_type_score": 65,
        "price_score": 90,
        "search_match_score": 20,
        "risk_penalty": 0,
        "risk_warnings": []
      },
      "commerce_handoff": {
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

| 필드 | 사용 | 설명 |
| --- | --- | --- |
| `recommendation_id` | 추적 | 장바구니/주문 유입 출처 추적 |
| `product_id` | 구매 | 찜, 장바구니, 주문 item의 상품 key |
| `rank` | 분석 | 추천 순위별 전환 분석 |
| `purchase_info` | 표시/검증 | 카드 표시용 가격/판매상태. checkout과 주문 시 서버가 다시 검증 |
| `thumbnail_image.storage_key` | 표시 | 프론트가 CDN base URL과 조합해 이미지 URL 생성 |
| `total_score` | 표시/분석 | 구매 가격 계산에는 사용하지 않음 |
| `reason_summary` | 표시 | 추천 카드/상세 설명 |
| `score_breakdown` | 표시/디버그 | 관리자/발표용 근거 |
| `commerce_handoff` | 구매 연결 | 장바구니/찜/checkout API로 넘길 추천 유입 payload |

## 상품 상세 연결

프론트는 추천 카드 클릭 시 추천 맥락을 보존해 상품 상세를 호출합니다.

```text
GET /api/products/{product_id}?recommendation_id={recommendation_id}
```

FastAPI는 같은 상품이라도 추천 맥락이 있으면 `total_score`, `reason_summary`, `score_breakdown`, `commerce_handoff`, `recommendation_reason`을 포함합니다. 추천 맥락이 없는 일반 상품 상세에서는 추천 전용 필드를 `null` 또는 빈 값으로 둡니다.

상품 상세에는 대표 이미지와 상세 이미지를 `storage_key` 기준으로 내려줍니다. CloudFront 절대 URL은 DB/API 기본값으로 저장하거나 내려주지 않고, 프론트가 공개 CDN base URL과 조합합니다.

## AI 설명 연결

추천 설명 생성은 같은 endpoint를 쓰되, 화면 위치에 따라 `view`를 나눕니다.

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

프론트는 목록 카드에서는 `cards`, 상품 상세에서는 `detail`을 사용합니다. 각 `product_explanations[]`도 추천 상품과 같은 `commerce_handoff`를 포함하므로, AI 설명 카드에서 커머스 행동 버튼을 노출해도 같은 payload를 FastAPI 커머스 API에 전달할 수 있습니다.

## Commerce Handoff 계약

장바구니, 찜, checkout 같은 커머스 상태 변경은 FastAPI가 처리합니다. 추천/검색 로직은 커머스 상태를 직접 확정하지 않고, 추천 응답에 `commerce_handoff` 객체를 내려줍니다.

```json
{
  "product_id": "prod_oy_a000000144918",
  "quantity": 1,
  "source": "ai_recommendation",
  "recommendation_id": "rec_000001",
  "recommendation_rank": 1
}
```

| 필드 | 필수 | 설명 |
| --- | --- | --- |
| `product_id` | Y | 장바구니에 담을 상품 ID |
| `quantity` | Y | 수량. 기본 1 |
| `source` | Y | `ai_recommendation`, `product_detail`, `wishlist` 중 하나 |
| `recommendation_id` | N | AI 추천 유입이면 포함 |
| `recommendation_rank` | N | AI 추천 유입이면 포함 |

서버는 장바구니 담기와 checkout preview, 주문 생성 시점에 현재 가격, 판매상태, 재고를 다시 확인합니다. 추천 시점 가격과 checkout 가격이 다르면 checkout/주문 시점의 서버 계산값이 최종값입니다.

## 상태와 이벤트 계약

| 이벤트 | 발생 주체 | 최소 payload |
| --- | --- | --- |
| `recommendation_requested` | Frontend/FastAPI | `user_id`, `anonymous_user_id`, `concern_tags` |
| `recommendation_product_impression` | Frontend/FastAPI | `user_id`, `recommendation_id`, `product_id`, `rank` |
| `recommendation_product_click` | Frontend/FastAPI | `user_id`, `recommendation_id`, `product_id`, `rank` |
| `product_viewed` | Frontend/FastAPI | `user_id`, `product_id`, `recommendation_id` |
| `cart_added` | FastAPI | `user_id`, `cart_id`, `product_id`, `quantity`, `source`, `recommendation_id` |
| `checkout_started` | FastAPI | `user_id`, `cart_id` |
| `payment_failed` | FastAPI | `user_id`, `order_id`, `error_code` |
| `order_completed` | FastAPI | `user_id`, `order_id`, `payment_status` |

이벤트 taxonomy의 최종 enum은 `docs/analytics-event-roadmap.md`와 `event_logs` DB 제약을 기준으로 맞춥니다. 민감정보, 원문 고민, LLM prompt/response 원문은 event metadata에 저장하지 않습니다.

## 에러 경계

| 상황 | 담당 | 권장 응답 |
| --- | --- | --- |
| 고민 텍스트 비어 있음 | FastAPI | `400 INVALID_INPUT` |
| 추천 결과 없음/만료 | FastAPI | `404 NOT_FOUND` 또는 `410 EXPIRED` |
| 상품 없음 | FastAPI | `404 NOT_FOUND` |
| 상품 판매 불가 | FastAPI | `409 PRODUCT_UNAVAILABLE` |
| 재고 부족 | FastAPI | `409 OUT_OF_STOCK` |
| mock/Toss sandbox 결제 실패 | FastAPI | `402 PAYMENT_FAILED` 또는 `409 PAYMENT_REJECTED` |

## 하지 않는 것

| 항목 | 이유 |
| --- | --- |
| `offer_id` 기반 판매 단위 | MVP는 단일 기본 seller 기준이며 중복 상품 판매가 없다는 합의가 있다. |
| CloudFront 절대 URL DB 저장 | CDN 도메인 변경 시 DB 전체 수정이 필요하다. |
| 클라이언트 가격/재고 확정 | 가격, 판매상태, 재고는 서버에서 최종 검증해야 한다. |
| 실제 운영 PG 결제 | P2는 mock 또는 Toss sandbox로 주문 완료 흐름을 검증한다. |
| AI agent가 직접 장바구니에 담기 | P2는 사용자가 버튼으로 구매 행동을 확정해야 한다. |
| 실시간 외부 가격 동기화 | P2는 seed/관리자 가격 기준으로 충분하다. |
| 다중 셀러 offer 경쟁 | P2는 1P 자사몰이므로 단일 판매자 기준이다. |
| Elasticsearch 운영 클러스터 | P2 검색/추천은 FastAPI DB/pgvector 기반으로 방어한다. |

## 1주차 합의 체크리스트

| 항목 | 결정 필요자 | 결정 |
| --- | --- | --- |
| `product_id`를 FastAPI 상품 key로 그대로 쓸지 | 원우, 세민, 규태 | P2 기본값: 그대로 사용 |
| 기본 seller 해석 기준 | 원우, 지현 | P2 기본값: FastAPI 내부에서 `product_id` 기준으로 처리 |
| 피부 프로필 전달 방식 | 원우, 지현, 규태 | FastAPI 저장 프로필 또는 프론트 snapshot 사용 |
| 추천 유입 장바구니 payload | 원우, 지현, 규태 | 이 문서의 `commerce_handoff` payload 사용 |
| 추천 결과 만료 정책 | 원우, 규태 | P2 기본값: 조회 가능하되 checkout 가격은 서버 기준 |
| 이벤트 로그 최소 범위 | 지운, 원우, 규태 | `docs/analytics-event-roadmap.md`의 1차 이벤트와 이 문서의 구매 이벤트를 맞춘다. |

## 완료 기준

- 추천 결과 카드에서 `product_id`, `recommendation_id`, `rank`가 보존된다.
- 상품 상세는 `recommendation_id`가 있을 때 추천 이유와 score breakdown을 보여준다.
- 이미지 응답은 `storage_key`, `image_type`, `display_order` 기준이다.
- 장바구니와 주문 item은 추천 유입 정보를 보존한다.
- checkout과 주문 생성은 서버 기준 가격, 판매상태, 재고를 다시 검증한다.
- FastAPI가 cart/order/payment/admin 상태를 소유한다.
