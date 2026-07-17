# 백엔드 로그/관측성 인벤토리

이 문서는 현재 백엔드가 남기는 로그를 인프라/운영 관점에서 한 번에 보기 위한 정리본이다.

대상 코드 기준:

- `apps/backend/app/middleware/request_logging.py`
- `apps/backend/app/core/performance_logging.py`
- `apps/backend/app/core/ai_logging.py`
- `apps/backend/app/db/slow_query_logging.py`
- `apps/backend/app/api/routes/*`
- `apps/backend/app/services/*`

## 1. 로그 종류 요약

현재 로그는 크게 세 종류다.

| 종류 | 저장 위치 | 주 용도 |
|---|---|---|
| 요청 로그 | stdout, logger `mwobareullae.request` | API별 응답시간, 상태코드, request_id 추적 |
| 성능/관측 로그 | stdout, logger `mwobareullae.performance` | DB slow query, 추천/상품/주문/결제/AI/seed/rollup 성능 추적 |
| 행동 이벤트 로그 | DB table `event_logs` | 상품 조회, 장바구니, 주문, 결제, 추천/검색 행동 수집 |

일반 Python logger도 일부 있다.

| logger | 위치 | 내용 |
|---|---|---|
| `app.services.data_loader` | `data_loader.py` | 선택 CSV 누락 warning |
| `mwobareullae.email` | `email_service.py` | SMTP 미설정 시 이메일 skip 로그 |
| route module logger | `cart.py`, `payments.py`, `orders.py`, `products.py`, `recommendations.py`, `user_activity.py` | 행동 이벤트 기록 실패 시 exception 로그 |

## 2. 공통 설정

환경변수:

| 변수 | 기본값 | 의미 |
|---|---:|---|
| `LOG_LEVEL` | `INFO` | Python logger level |
| `ENABLE_REQUEST_LOGGING` | `true` | 요청 로그 middleware 활성화 |
| `ENABLE_PERFORMANCE_LOGGING` | `true` | 성능 JSON 로그 활성화 |
| `ENABLE_DB_SLOW_QUERY_LOGGING` | `true` | DB slow query 로그 활성화 |
| `DB_SLOW_QUERY_THRESHOLD_MS` | `100` | 이 값 이상 걸린 SQL만 `db_slow_query` 기록 |
| `DOCKER_LOG_MAX_SIZE` | `10m` | Docker json-file 로그 파일 크기 제한 |
| `DOCKER_LOG_MAX_FILE` | `5` | Docker json-file 보관 개수 |

`mwobareullae.request`, `mwobareullae.performance`는 message-only formatter를 사용한다.
즉, stdout에 JSON 한 줄만 찍히도록 별도 logger로 구성되어 있다.

## 3. 요청 로그

위치:

- `apps/backend/app/middleware/request_logging.py`

logger:

- `mwobareullae.request`

발생 시점:

- 모든 FastAPI 요청 완료 시
- 예외 발생 시에도 `status_code=500`, `error=<예외 타입>`으로 기록 후 예외 재발생

응답 헤더:

- `X-Request-ID`
- `X-Process-Time-Ms`

필드:

| 필드 | 의미 |
|---|---|
| `timestamp` | UTC ISO8601 millisecond |
| `service` | `commerce-backend` |
| `request_id` | `X-Request-ID` 또는 서버 생성 UUID |
| `method` | HTTP method |
| `endpoint` | FastAPI route template. 예: `/api/products/{product_id}` |
| `status_code` | HTTP 상태코드 |
| `response_time_ms` | API 전체 응답 시간 |
| `user_id` | request.state.user_id가 있으면 문자열, 없으면 null |
| `error` | 정상은 null, 예외 시 예외 타입명 |

예시:

```json
{"timestamp":"2026-07-07T04:32:10.123Z","service":"commerce-backend","request_id":"req_123","method":"GET","endpoint":"/api/products/{product_id}","status_code":200,"response_time_ms":42.5,"user_id":"1","error":null}
```

## 4. 성능/관측 로그 공통 포맷

위치:

- `apps/backend/app/core/performance_logging.py`

logger:

- `mwobareullae.performance`

공통 필드:

| 필드 | 의미 |
|---|---|
| `timestamp` | UTC ISO8601 millisecond |
| `service` | `commerce-backend` |
| `event` | 성능 이벤트명 |
| `request_id` | 요청 로그와 연결되는 ID. 요청 밖 batch/seed면 null일 수 있음 |
| `duration_ms` | 해당 작업 소요 시간. 없는 이벤트도 가능 |

주의:

- `timestamp`, `service`, `event`, `request_id`, `duration_ms`는 예약 필드다.
- metadata에 같은 이름을 넣어도 덮어쓰지 않는다.
- Decimal, datetime, date, list, dict는 JSON safe 형태로 변환된다.

## 5. DB Slow Query 로그

위치:

- `apps/backend/app/db/slow_query_logging.py`
- `apps/backend/app/db/session.py`

event:

- `db_slow_query`

발생 시점:

- SQLAlchemy engine의 `before_cursor_execute`, `after_cursor_execute`, `handle_error`
- `DB_SLOW_QUERY_THRESHOLD_MS` 이상 걸린 SQL만 기록

필드:

| 필드 | 의미 |
|---|---|
| `db_system` | DB dialect. 예: `postgresql`, `sqlite` |
| `statement_type` | SQL 첫 단어. 예: `SELECT`, `INSERT`, `UPDATE` |
| `sql` | 공백 정규화된 SQL. 최대 500자 |
| `sql_length` | 정규화된 SQL 길이 |
| `rowcount` | cursor rowcount. 모르면 null |
| `executemany` | executemany 여부 |
| `error` | 정상은 null, 에러 시 예외 타입 |

예시:

```json
{"event":"db_slow_query","request_id":"req_123","duration_ms":128.4,"db_system":"postgresql","statement_type":"SELECT","sql":"SELECT ...","sql_length":214,"rowcount":10,"executemany":false,"error":null}
```

## 6. API/도메인 성능 로그

### 홈

위치:

- `apps/backend/app/api/routes/home.py`

| event | 붙은 API | 주요 필드 |
|---|---|---|
| `home_layout_completed` | `GET /api/home/layout` | `section_count`, `section_ids` |
| `home_market_popular_completed` | `GET /api/home/market-popular` | `product_count`, `category_code`, `limit` |
| `home_evidence_picks_completed` | `GET /api/home/evidence-picks` | `product_count`, `category_code`, `limit` |
| `home_for_you_completed` | `GET /api/home/for-you` | `product_count`, `category_code`, `skin_type`, `sensitivity`, `has_user`, `limit`, `personalization_sources` |

### 상품

위치:

- `apps/backend/app/api/routes/products.py`

| event | 붙은 API | 주요 필드 |
|---|---|---|
| `popular_products_completed` | `GET /api/products/popular` | `window_days`, `requested_limit`, `item_count`, `category_code`, `top_popularity_score` |
| `product_detail_completed` | `GET /api/products/{product_id}` | `product_id`, `has_recommendation_context`, `can_purchase`, `sales_status`, `stock_status` |
| `product_reviews_completed` | `GET /api/products/{product_id}/reviews` | `product_id`, `sort`, `limit`, `item_count`, `has_next`, `has_profile_filter` |
| `product_review_create_completed` | `POST /api/products/{product_id}/reviews` | `product_id`, `review_id`, `review_count` |
| `product_review_update_completed` | `PATCH /api/reviews/{review_id}` | `product_id`, `review_id`, `review_count` |
| `product_review_delete_completed` | `DELETE /api/reviews/{review_id}` | `product_id`, `review_id`, `review_count` |
| `product_review_catalog_sync_completed` | 리뷰 변경 후 ES 단건 동기화 | `product_id`, `action` |
| `product_review_catalog_sync_failed` | 리뷰 저장 후 ES 단건 동기화 실패 | `product_id`, `error` |

### 카탈로그 탐색

위치:

- `apps/backend/app/api/routes/catalog.py`

| event | 붙은 API | 주요 필드 |
|---|---|---|
| `product_listing_completed` | `GET /api/products` | `page`, `page_size`, `item_count`, `total_items`, `sort`, 필터별 개수 |
| `catalog_categories_completed` | `GET /api/categories` | `item_count` |
| `catalog_brands_completed` | `GET /api/brands` | `page`, `page_size`, `item_count`, `has_query` |

### 추천 API

위치:

- `apps/backend/app/api/routes/recommendations.py`

| event | 붙은 API | 주요 필드 |
|---|---|---|
| `recommendation_create_completed` | `POST /api/recommendations` | `recommendation_id`, `returned_product_count`, `total_items`, `page`, `page_size`, `matched_concern_count`, `expected_effect_count`, `unmatched_term_count` |
| `recommendation_get_completed` | `GET /api/recommendations/{recommendation_id}` | `recommendation_id`, `returned_product_count`, `total_items`, `page`, `page_size` |
| `recommendation_narrative_completed` | `POST /api/recommendations/{recommendation_id}/narrative` | `recommendation_id`, `generation_source`, `fallback_reason`, `product_explanation_count` |

### 추천 파이프라인 내부

위치:

- `apps/backend/app/services/recommendation_pipeline.py`

| event | 의미 |
|---|---|
| `recommendation_pipeline_completed` | 추천 파이프라인 전체 성공 |
| `recommendation_pipeline_failed` | 추천 파이프라인 실패 |

단계별 시간 필드:

| 필드 | 의미 |
|---|---|
| `intent_parse_ms` | 사용자 입력/고민 파싱 |
| `intent_materialize_ms` | 에이전트 구조화 intent를 추천 입력으로 변환 |
| `run_save_ms` | recommendation_run 저장 |
| `candidate_load_ms` | 후보 상품 로드 |
| `avoid_filter_ms` | 회피 성분 필터 |
| `search_match_ms` | 검색/매칭 |
| `scoring_ms` | 추천 점수 계산 |
| `result_save_ms` | 추천 결과 저장 |
| `commit_ms` | DB commit/flush |
| `response_load_ms` | 응답용 결과 재조회 |

저장 병목을 세분화할 때는 아래 하위 필드를 함께 확인한다.

| 구간 | 하위 필드 |
|---|---|
| 추천 실행 저장 | `run_row_build_ms`, `run_insert_flush_ms`, `run_relation_build_ms`, `run_relation_add_ms`, `run_relation_flush_ms` |
| 최종 결과 저장 | `result_existing_lookup_ms`, `result_existing_evidence_delete_ms`, `result_existing_result_delete_ms`, `result_existing_delete_flush_ms`, `result_row_build_ms`, `result_add_ms`, `result_flush_ms` |
| 추천 근거 저장 | `evidence_row_build_ms`, `evidence_add_ms`, `evidence_flush_ms` |

Opt7 이전 성능 로그에는 후보 trace 저장 시간인 `search_candidate_save_ms`와
`candidate_trace_match_validation_ms`, `candidate_trace_delete_ms`,
`candidate_trace_row_build_ms`, `candidate_trace_add_ms`,
`candidate_trace_flush_ms`가 기록된다. Opt7부터 정상 추천 경로는 후보 trace를
DB에 저장하지 않으므로 해당 필드를 기록하지 않는다.

추가 필드:

| 필드 | 의미 |
|---|---|
| `recommendation_id` | 추천 요청 ID |
| `intent_source` | intent 입력 경로 (`raw_parser`, `agent_structured`) |
| `llm_available` | LLM parser 준비 여부 |
| `llm_used` | LLM 사용 여부 |
| `candidate_pool_limit` | 후보 풀 제한 |
| `result_limit` | 저장 결과 제한 |
| `page`, `page_size` | 페이지 조건 |
| `loaded_candidate_count` | 최초 로드 후보 수 |
| `after_avoid_filter_count` | 회피 필터 후 후보 수 |
| `search_join_document_count` | 검색 join 문서 수 |
| `search_match_count` | 검색 매칭 수 |
| `positive_search_match_count` | 양수 매칭 수 |
| `no_result_reason` | 무결과 진단 사유 |
| `scored_candidate_count` | 점수 계산 후보 수 |
| `final_result_count` | 최종 결과 수 |
| `returned_product_count` | 응답 상품 수 |
| `total_items` | 전체 결과 수 |
| `matched_concern_count` | 매칭 고민 수 |
| `expected_effect_count` | 기대 효능 수 |
| `unmatched_term_count` | 매칭 안 된 단어 수 |
| `avoid_ingredient_count` | 회피 성분 수 |
| `error` | 실패 시 예외 타입 |

## 7. OpenAI / AI 호출 로그

위치:

- `apps/backend/app/core/ai_logging.py`
- `apps/backend/app/services/concern_llm_parser.py`
- `apps/backend/app/services/recommendation_narrative.py`
- `apps/backend/app/services/agent_openai_runner.py`

event:

- 성공: `ai_call_completed`
- 실패: `ai_call_failed`

공통 필드:

| 필드 | 의미 |
|---|---|
| `provider` | 기본 `openai` |
| `operation` | AI 작업명 |
| `model` | 사용 모델 |
| `success` | 성공 여부 |
| `error` | 실패 시 오류 타입 |
| `input_tokens` | 입력 토큰 |
| `output_tokens` | 출력 토큰 |
| `total_tokens` | 전체 토큰 |
| `cost_usd` | 현재 null. 비용 계산은 아직 미구현 |

현재 operation:

| operation | 위치 | 추가 필드 |
|---|---|---|
| `concern_parser` | 고민/의도 파서 | 성공 시 `schema`, 실패 시 `status_code` |
| `recommendation_narrative` | 추천 설명 생성 | `view`, `mode`, `product_count`, `has_product_focus`, 실패 시 `status_code` |
| `agent_chat` | OpenAI Agents SDK 기반 챗봇/액션 에이전트 | `conversation_id`, `max_turns`, `tool_called`, `tool_name`, `item_count`, `ui_action_type` |

민감정보 차단:

`log_ai_call` metadata에서는 아래 key를 저장하지 않는다.

- `prompt`
- `raw_prompt`
- `response`
- `raw_response`
- `messages`
- `message`
- `user_message`
- `user_input`
- `input_text`
- `output_text`
- `final_output`

즉, LLM prompt/response 원문은 성능 로그에 남기지 않는 기준이다.

## 8. Agent Tool 로그

위치:

- `apps/backend/app/services/agent_tool_dispatcher.py`

event:

- `agent_tool_completed`
- `agent_tool_failed`

필드:

| 필드 | 의미 |
|---|---|
| `tool_name` | 실행 tool 이름 |
| `status` | `EXECUTED`, `AWAITING_CONFIRMATION`, `FAILED` |
| `confirmation_required` | 사용자 확인 필요 여부 |
| `tool_call_id` | tool call ID |
| `item_count` | 응답 item 수 |
| `ui_action_type` | 프론트에 요청할 UI action 종류 |
| `user_authenticated` | 로그인 사용자 여부 |
| `error_code` | 실패 시 ApiError code |

현재 Agents SDK에서 연결된 tool:

- `find_similar_products`
- `compare_products`
- `refine_product_results`
- `order_status_lookup`
- `cancel_recent_order`
- `get_cart`
- `add_to_cart`
- `compose_cart`
- `prepare_checkout`
- `register_shipping_address`
- `prepare_order`
- `prepare_review_draft`
- `prepare_claim_draft`

`register_shipping_address`는 개인정보 원문을 `agent_tool_calls.input_json`에 남기지 않는다. 필드 제공 여부와 checkout 재개 여부만 기록한다.

## 9. 주문 / 결제 / 재고 Transaction 로그

위치:

- `apps/backend/app/services/order_service.py`
- `apps/backend/app/services/payment_service.py`
- `apps/backend/app/services/order_cancel_service.py`
- `apps/backend/app/services/payment_expiry_service.py`

| event | 의미 | 주요 필드 |
|---|---|---|
| `order_create_completed` | 주문 생성 성공, 재고 예약 포함 | `requested_item_count`, `selected_item_count`, `reserved_item_count`, `reserved_quantity_total`, `seller_count`, `subtotal_amount`, `shipping_fee`, `total_amount`, `payment_provider`, `order_status`, `idempotent_replay` |
| `order_create_failed` | 주문 생성 실패 | `requested_item_count`, `payment_provider`, `error_code` |
| `payment_confirm_completed` | 결제 승인 성공, 재고 확정 차감 | `provider`, `amount`, `order_status`, `payment_status`, `confirmed_quantity_total`, `idempotent_replay` |
| `payment_confirm_failed` | 결제 승인 실패 | `provider`, `amount`, `error_code` |
| `payment_fail_completed` | 결제 실패 처리 성공, 예약 재고 복원 | `provider`, `payment_status`, `order_status`, `released_quantity_total`, `idempotent_replay` |
| `payment_fail_failed` | 결제 실패 처리 실패 | `provider`, `error_code` |
| `order_cancel_completed` | 결제 전 주문 취소 성공, 예약 재고 복원 | `order_status`, `payment_status`, `released_quantity_total`, `idempotent_replay` |
| `order_cancel_failed` | 주문 취소 실패 | `error_code` |
| `payment_expiry_sweep_completed` | 결제 대기 만료 주문 sweep 성공 | `limit`, `scanned_count`, `expired_count`, `released_quantity_total` |
| `payment_expiry_sweep_failed` | 결제 대기 만료 주문 sweep 실패 | `limit`, `error_code` |

## 10. 이벤트 수집 API 로그

위치:

- `apps/backend/app/api/routes/events.py`

| event | 붙은 API | 의미 |
|---|---|---|
| `event_batch_collected` | `POST /api/events/batch` | batch 이벤트 저장 성공 |
| `event_batch_failed` | `POST /api/events/batch` | batch 이벤트 저장 실패 |

필드:

| 필드 | 의미 |
|---|---|
| `batch_size` | 요청 이벤트 수 |
| `accepted_count` | 저장/수락된 수 |
| `duplicate_count` | event_id 중복으로 재사용된 수 |
| `rejected_count` | 거부된 수 |
| `event_name_counts` | event_name별 개수 |
| `user_authenticated` | 로그인 여부 |
| `error_code` | 실패 시 ApiError code |

단일 이벤트 API `POST /api/events`는 현재 별도 performance 로그 없이 `event_logs` DB 저장만 수행한다.

## 11. 인기상품 Rollup 로그

위치:

- `apps/backend/app/services/product_popularity_rollup.py`

event:

- `product_popularity_rollup_completed`

필드:

| 필드 | 의미 |
|---|---|
| `product_lookup_ms` | 상품 코드 -> 내부 ID 조회 시간 |
| `direct_event_collect_ms` | 직접 상품 이벤트 집계 시간 |
| `checkout_collect_ms` | checkout_started metadata 기반 집계 시간 |
| `order_event_collect_ms` | 주문 이벤트 + order_items 집계 시간 |
| `existing_metric_load_ms` | 기존 metric 로드 시간 |
| `metric_apply_ms` | metric 갱신 적용 시간 |
| `flush_ms` | DB flush 시간 |
| `window_days` | 집계 기간. 예: 7, 30 |
| `product_count` | 전체 상품 수 |
| `touched_products` | 이벤트로 영향 받은 상품 수 |
| `updated_metrics` | 생성/갱신한 metric 수 |
| `score_version` | 인기점수 공식 버전 |

집계에 쓰는 event_logs:

- `product_viewed`
- `recommendation_product_click`
- `home_product_click`
- `search_result_click`
- `cart_added`
- `wishlist_added`
- `home_product_impression`
- `search_result_impression`
- `wishlist_removed`
- `cart_removed`
- `cart_quantity_changed`
- `checkout_started`
- `order_completed`
- `payment_failed`
- `order_cancelled`

## 12. Seed / Import 로그

위치:

- `apps/backend/app/services/db_seed.py`
- `apps/backend/app/cli/seed_data.py`

event:

| event | 의미 |
|---|---|
| `seed_catalog_loaded` | CSV/JSON 파일 로드와 검증 완료 |
| `seed_phase_completed` | seed 주요 phase 하나 완료 |
| `seed_product_ingredients_progress` | `product_ingredients` 대량 row 처리 진행률 |
| `seed_database_completed` | 전체 seed 성공 |
| `seed_database_failed` | 전체 seed 실패 |

`seed_catalog_loaded` 필드:

| 필드 | 의미 |
|---|---|
| `data_dir` | 사용한 데이터 디렉터리 |
| `row_counts` | 파일별 row 수 |
| `loaded_row_count` | 총 로드 row 수 |

`seed_phase_completed` phase:

| phase | 의미 |
|---|---|
| `taxonomy` | 고민/효능 taxonomy |
| `ingredients` | 성분, alias, 성분 효능, 성분 근거, risk flag |
| `product_catalog` | 브랜드, 카테고리, 상품, 이미지, 가격 |
| `commerce_seed` | 재고, mock market signal 기반 popularity metric |
| `product_ingredients` | 상품-성분 매핑 |
| `product_skin_profiles` | 상품 피부 적합도 |
| `search_documents` | 검색 문서 |

`seed_phase_completed` 공통 필드:

| 필드 | 의미 |
|---|---|
| `phase` | phase 이름 |
| `phase_order` | 현재 phase 순서 |
| `phase_count` | 전체 phase 수. 현재 7 |
| `row_count` | phase 입력 row 수 |
| `data_dir` | 사용한 데이터 디렉터리 |

`seed_product_ingredients_progress` 필드:

| 필드 | 의미 |
|---|---|
| `phase` | `product_ingredients` |
| `processed_row_count` | 처리한 row 수 |
| `total_row_count` | 전체 product_ingredients row 수 |
| `deduplicated_pair_count` | 중복 제거 후 상품-성분 pair 수 |
| `progress_percent` | 진행률 |
| `data_dir` | 사용한 데이터 디렉터리 |

기본 진행 로그 간격:

- `SEED_PROGRESS_INTERVAL_ROWS = 50_000`

`seed_database_completed` 필드:

| 필드 | 의미 |
|---|---|
| `data_dir` | 사용한 데이터 디렉터리 |
| `row_counts` | 파일별 로드 row 수 |
| `loaded_row_count` | 총 로드 row 수 |
| `seed_counts` | 최종 seed count |
| `seeded_entity_count` | seed count 합 |
| `error_count` | 성공이면 0 |
| `failed_row_sample_count` | 현재 0. 실패 row sample 저장은 아직 없음 |
| `counting_mode` | 현재 `loaded_rows_and_final_seed_counts` |

주의:

- 현재 seed는 `inserted`, `updated`, `skipped`를 정확히 분리해서 세지는 않는다.
- 현재 로그는 “로드 row 수 + 최종 seed count + phase 진행률” 기준이다.

## 13. 행동 이벤트 로그: `event_logs`

위치:

- model: `apps/backend/app/db/models/events.py`
- schema: `apps/backend/app/schemas/event.py`
- service: `apps/backend/app/services/event_service.py`
- API: `POST /api/events`, `POST /api/events/batch`

저장 위치:

- PostgreSQL table `event_logs`

주요 컬럼:

| 컬럼 | 의미 |
|---|---|
| `id` | 내부 PK |
| `event_id` | 멱등키. unique |
| `event_name` | 이벤트명 |
| `occurred_at` | 실제 발생 시각 |
| `user_id` | 로그인 사용자 ID |
| `anonymous_user_id` | 비회원/익명 사용자 ID |
| `session_id` | 프론트 세션 ID |
| `request_id` | 백엔드 요청 추적 ID |
| `recommendation_id` | 추천 요청 ID |
| `product_id` | 상품 코드 |
| `rank` | 노출/추천 순위 |
| `source` | 발생 출처 |
| `page` | 화면/페이지 |
| `cart_id` | 장바구니 ID |
| `order_id` | 주문 ID |
| `metadata_json` | 부가 JSON |
| `created_at` | DB 저장 시각 |

프론트 식별 헤더:

| 헤더 | 의미 |
|---|---|
| `X-MWBL-Anonymous-User-Id` | 익명 사용자 식별자 |
| `X-MWBL-Session-Id` | 세션 식별자 |
| `X-Request-ID` | 요청 추적 ID |

metadata 제한:

- 최대 `16KB`
- JSON serializable이어야 함
- 민감 key 포함 시 거부

차단되는 민감 key 예:

- `email`, `phone`, `address`, `name`
- `password`
- `token`, `access_token`, `refresh_token`, `authorization`
- `card_number`
- `prompt`, `raw_prompt`, `raw_response`, `llm_prompt`, `llm_response`
- `recipient_name`, `user_email`, `user_name`

## 14. 공식 이벤트명

현재 `OFFICIAL_EVENT_NAMES`:

| event_name | 의미 |
|---|---|
| `recommendation_requested` | 추천 요청 생성 |
| `recommendation_analyzed` | 추천 요청 분석 완료 |
| `recommendation_viewed` | 추천 결과 조회 |
| `recommendation_product_impression` | 추천 상품 노출 |
| `recommendation_product_click` | 추천 상품 클릭 |
| `home_product_impression` | 홈 상품 노출 |
| `home_product_click` | 홈 상품 클릭 |
| `search_result_impression` | 검색 결과 노출 |
| `search_result_click` | 검색 결과 클릭 |
| `product_viewed` | 상품 상세 조회 |
| `recent_product_viewed` | 최근 본 상품 등록 |
| `wishlist_added` | 찜 추가 |
| `wishlist_removed` | 찜 제거 |
| `cart_added` | 장바구니 추가 |
| `cart_quantity_changed` | 장바구니 수량 변경 |
| `cart_removed` | 장바구니 항목 제거 |
| `checkout_started` | checkout preview/결제 진입 |
| `order_created` | 주문 생성 |
| `order_completed` | 주문/결제 완료 |
| `order_cancelled` | 주문 취소 |
| `payment_started` | 결제 시작 |
| `search_performed` | 검색 수행 |
| `search_no_result` | 검색 무결과 |
| `recommendation_fallback_used` | 추천 fallback 사용 |
| `payment_failed` | 결제 실패 |
| `llm_call` | LLM 호출 이벤트 |
| `api_request_logged` | API 요청 기록 이벤트 |

## 15. 백엔드가 자동 기록하는 행동 이벤트

아래 이벤트는 백엔드 API 호출 중 자동으로 `event_logs`에 저장된다.

| event_name | 위치 | 발생 시점 | 주요 metadata |
|---|---|---|---|
| `recommendation_requested` | `recommendations.py` | `POST /api/recommendations` | product_count, total_items, page, skin_type, sensitivity, matched/effect/unmatched count |
| `recommendation_analyzed` | `recommendations.py` | `POST /api/recommendations` | 위와 동일 |
| `recommendation_viewed` | `recommendations.py` | `GET /api/recommendations/{recommendation_id}` | product_count, total_items, page |
| `product_viewed` | `products.py` | `GET /api/products/{product_id}` | recommendation context, can_purchase, sales_status, stock_status |
| `cart_added` | `cart.py` | 장바구니 추가 | quantity, product_id, recommendation_id, rank, source |
| `cart_quantity_changed` | `cart.py` | 장바구니 수량 변경 | previous_quantity, quantity |
| `cart_removed` | `cart.py` | 장바구니 항목 제거 | previous_quantity, quantity |
| `checkout_started` | `cart.py` | checkout preview | item_count, total_quantity, subtotal, shipping_fee, total, can_checkout, product_ids, warning_codes, address_id_provided |
| `payment_started` | `payments.py` | 결제 시작/승인 요청 전후 | order_code, payment_code, provider, order/payment status, amount, currency |
| `payment_failed` | `payments.py` | Toss confirm 실패 또는 payment fail 처리 | order_code, amount, error_code, error_status_code, payment/order status |
| `order_created` | `orders.py` | 주문 생성 | order_code, order_status, payment_code, provider, payment_status, subtotal, shipping_fee, total, item_count, total_quantity |
| `order_cancelled` | `orders.py` | 주문 취소 | order_code, order_status, payment_code, provider, payment_status, subtotal, shipping_fee, total, item_count, total_quantity |
| `order_completed` | `payments.py` | 결제 승인 완료 | order_code, payment_code, provider, order/payment status, amount, currency |
| `wishlist_added` | `user_activity.py` | 찜 추가 | product_id, source, page |
| `wishlist_removed` | `user_activity.py` | 찜 제거 | product_id, source, page |
| `recent_product_viewed` | `user_activity.py` | 최근 본 상품 등록 | product_id, source, page |

프론트가 직접 전송해야 하는 이벤트:

- `home_product_impression`
- `home_product_click`
- `recommendation_product_impression`
- `recommendation_product_click`
- `search_result_impression`
- `search_result_click`
- `search_performed`
- `search_no_result`
- 필요 시 `recommendation_fallback_used`

## 16. 일반 logger.exception / warning

아래는 JSON performance log가 아니라 일반 Python logger를 탄다.
기본 `logging.basicConfig` 포맷이 붙을 수 있다.

| 로그 메시지 | 위치 | 의미 |
|---|---|---|
| `failed_to_record_cart_added_event` | `cart.py` | 장바구니 추가 이벤트 저장 실패 |
| `failed_to_record_checkout_started_event` | `cart.py` | checkout_started 이벤트 저장 실패 |
| `failed_to_record_cart_item_event` | `cart.py` | cart_quantity_changed/cart_removed 이벤트 저장 실패 |
| `failed_to_record_payment_started_event_log` | `payments.py` | payment_started 이벤트 저장 실패 |
| `failed_to_record_toss_payment_failed_event_log` | `payments.py` | Toss 실패 이벤트 저장 실패 |
| `failed_to_record_payment_event_log` | `payments.py` | payment/order 이벤트 저장 실패 |
| `failed_to_record_<event_name>_event` | `orders.py` | order_created/order_cancelled 이벤트 저장 실패 |
| `failed_to_record_<event_name>` | `user_activity.py` | wishlist/recent event 저장 실패 |
| `failed_to_record_product_viewed_event` | `products.py` | product_viewed 이벤트 저장 실패 |
| `failed_to_record_recommendation_event` | `recommendations.py` | 추천 행동 이벤트 저장 실패 |
| `email_skipped smtp_not_configured ...` | `email_service.py` | SMTP 미설정으로 이메일 발송 생략 |
| `선택 데이터 파일이 없습니다: <file>` | `data_loader.py` | optional CSV가 없어 생략 |

주의:

- `email_skipped`는 현재 to_email, subject를 일반 로그에 남긴다.
- 운영에서 이메일 주소를 stdout에 남기지 않으려면 별도 마스킹이 필요하다.

## 17. 인프라 수집 기준 제안

지금 당장 수집하면 좋은 stdout logger:

| logger | 수집 여부 | 이유 |
|---|---|---|
| `mwobareullae.request` | 필수 | API 응답시간/상태코드/RPS 분석 |
| `mwobareullae.performance` | 필수 | 병목 분석 핵심 |
| root/app logger | 권장 | event 저장 실패, email skip, data warning 확인 |

DB에서 별도 백업/분석할 테이블:

| table | 수집/보관 이유 |
|---|---|
| `event_logs` | 행동 데이터, 인기상품 집계, 추천 품질 분석 |
| `product_popularity_metrics` | 인기상품 read model |
| `agent_tool_calls` | Agent tool 실행 audit |
| `ai_call_logs` | 현재 별도 table로 쓰는지 확인 필요. 성능 로그는 stdout 기준으로 이미 있음 |

## 18. 현재 로그로 바로 볼 수 있는 것

| 질문 | 보는 로그 |
|---|---|
| 어떤 API가 느린가? | `mwobareullae.request.response_time_ms` |
| 어떤 SQL이 느린가? | `db_slow_query` |
| 추천이 어디서 느린가? | `recommendation_pipeline_completed`의 `*_ms` 필드 |
| OpenAI가 느린가/토큰을 많이 쓰나? | `ai_call_completed`, `ai_call_failed` |
| Agent tool이 느린가? | `agent_tool_completed`, `agent_tool_failed` |
| 주문 생성/결제/취소에서 어디가 느린가? | order/payment transaction event |
| 이벤트 batch가 잘 들어오나? | `event_batch_collected`, `event_batch_failed` |
| 인기상품 rollup이 느린가? | `product_popularity_rollup_completed` |
| seed가 멈춘 건가, 진행 중인가? | `seed_catalog_loaded`, `seed_phase_completed`, `seed_product_ingredients_progress` |

## 19. 아직 부족한 부분

현재 로그가 모든 것을 완전히 설명하지는 않는다.

추가가 필요할 수 있는 것:

- API별 DB query total time 합산
- SQLAlchemy connection pool wait time
- Redis cache hit/miss
- Elasticsearch query time
- 프론트 렌더링/실제 노출 시간
- seed의 정확한 `inserted`, `updated`, `skipped` 분리
- email 발송 성공/실패 latency
- Toss 외부 API latency를 별도 span으로 분리
- Docker/container CPU, memory, OOM, restart 지표

현재 단계에서는 baseline으로 충분하고, 실제 병목이 보이는 API부터 더 세밀한 span을 추가하는 방식이 맞다.
