# 사용자 행동 데이터 수집 로드맵

## 1. 목표

뭐바를래는 GA4와 자체 DB 이벤트 로그를 함께 사용해 사용자 행동 데이터를 최대한 구조적으로 수집한다.

목표는 단순 방문자 수 확인이 아니라, 이후 개인화 추천과 추천 알고리즘 개선에 사용할 수 있는 기반 데이터를 쌓는 것이다.

```text
프론트 이벤트 감지
-> GA4 전송: 유입, 세션, 퍼널, 대시보드 분석
-> 백엔드 전송: 개인화 추천, 랭킹 튜닝, 사용자 취향 프로필 생성
```

## 2. 역할 분리

### GA4가 맡는 일

- 방문자 수, 세션 수, 신규/재방문 사용자 확인
- 유입 경로 분석: 커뮤니티, 검색, 직접 방문, UTM
- 기기/브라우저/지역/언어 분석
- 페이지뷰, 기본 스크롤, 외부 링크 클릭 등 기본 이벤트 확인
- 추천 클릭, 상품 클릭, 구매 링크 클릭 같은 커스텀 이벤트 집계
- 퍼널 분석: 방문 -> 추천 -> 상품 상세 -> 구매 링크 클릭
- 리텐션 분석: 다시 온 사용자가 얼마나 되는지 확인
- 관리자 화면 없이 기본 리포트/차트/탐색 분석 제공
- 필요 시 BigQuery Export로 원천 이벤트 분석 확장

### 우리 DB가 맡는 일

- 추천 개인화에 필요한 정밀 이벤트 저장
- `recommendation_id`, `product_id`, `rank`, `score_breakdown`, `algorithm_version` 보존
- 어떤 추천 점수와 근거가 실제 클릭/구매 링크 클릭으로 이어졌는지 분석
- 사용자별 선호 카테고리, 브랜드, 가격대, 효능, 성분 추정
- 추후 `user_preference_profile` 생성
- 추천 알고리즘 버전별 성능 비교

## 3. 수집 원칙

- 가능한 많은 행동을 수집하되, 나중에 분석 가능한 이름과 구조로 저장한다.
- GA4에는 고민 원문, 개인정보, 민감한 긴 문장을 보내지 않는다.
- GA4에는 태그, 버킷, 카테고리화된 값만 보낸다.
- 우리 DB에도 원문 저장은 최소화하고, 저장이 필요하면 목적과 보관 기간을 분명히 한다.
- 상품 노출 이벤트는 렌더링 기준이 아니라 실제 화면 노출 기준으로 찍는다.
- 이벤트 이름은 프론트, 백엔드, GA4가 동일하게 사용한다.
- 이벤트에는 가능하면 `anonymous_user_id`, `session_id`, `page`, `section_id`를 포함한다.

## 4. 사용자 식별

로그인이 없으므로 프론트에서 익명 식별자를 만든다.

```text
anonymous_user_id
- 최초 방문 시 생성
- localStorage 또는 cookie에 저장
- 같은 브라우저 재방문 추적용

session_id
- 방문 세션 단위로 생성
- 일정 시간 비활동 시 새 세션으로 갱신
```

이 값으로 다음을 볼 수 있다.

- 신규 사용자와 재방문 사용자 차이
- 한 사용자가 몇 번 추천을 받았는지
- 재방문자가 어떤 상품을 다시 눌렀는지
- 추천 이후 상품 상세나 구매 링크까지 갔는지

## 5. 1차 필수 이벤트

커뮤니티 배포와 MVP 분석에 먼저 필요한 이벤트다.

```text
page_view
home_view
home_section_view
home_product_impression
home_product_click

recommendation_submit
recommendation_result_view
recommendation_product_impression
recommendation_product_click

product_detail_view
purchase_link_click
feedback_submit
```

### 이벤트 의미

| 이벤트 | 의미 |
| --- | --- |
| `page_view` | 페이지 진입 |
| `home_view` | 홈 화면 진입 |
| `home_section_view` | 홈의 특정 섹션 노출 |
| `home_product_impression` | 홈 상품 카드가 실제 화면에 노출 |
| `home_product_click` | 홈 상품 카드 클릭 |
| `recommendation_submit` | 사용자가 추천 요청 제출 |
| `recommendation_result_view` | 추천 결과 페이지 진입 |
| `recommendation_product_impression` | 추천 결과 상품 카드 노출 |
| `recommendation_product_click` | 추천 결과 상품 클릭 |
| `product_detail_view` | 상품 상세 페이지 진입 |
| `purchase_link_click` | 외부 구매 링크 클릭 |
| `feedback_submit` | 추천/상품 피드백 제출 |

## 6. 2차 확장 이벤트

1차 이벤트가 안정화된 뒤 추가한다.

```text
scroll_depth
section_visible
search_input_focus
filter_apply
sort_change
ai_narrative_view
ai_narrative_expand
pagination_click
back_to_result
session_end
page_leave
```

### 노출/체류 기준

상품 노출은 DOM 렌더링이 아니라 실제 화면 노출을 기준으로 한다.

```text
product_impression:
- 상품 카드가 50% 이상 보임
- 0.5초 이상 유지

section_visible:
- 섹션이 50% 이상 보임
- 2초 이상 유지

scroll_depth:
- 25%, 50%, 75%, 100% 구간 도달 시 기록
```

프론트에서는 `IntersectionObserver` 기반으로 처리하는 것이 좋다.

## 7. 공통 이벤트 Payload

모든 이벤트는 가능한 한 아래 구조를 따른다.

```json
{
  "event_id": "evt_xxx",
  "event_name": "recommendation_product_click",
  "anonymous_user_id": "anon_xxx",
  "session_id": "sess_xxx",
  "recommendation_id": "rec_xxx",
  "product_id": "prod_xxx",
  "rank": 3,
  "page": "recommendation_result",
  "occurred_at": "2026-06-30T12:00:00+09:00",
  "metadata": {
    "section_id": "result_list",
    "algorithm_version": "recommendation_v1",
    "skin_type": "dry",
    "sensitivity": "normal",
    "concern_tags": ["속건조", "장벽"],
    "effect_tags": ["보습", "장벽"],
    "category_code": "cream",
    "brand": "round_lab",
    "total_score": 87,
    "score_bucket": "80_90",
    "price_bucket": "20000_30000"
  }
}
```

## 8. GA4 전송 값

GA4에는 분석과 퍼널에 필요한 가벼운 값만 보낸다.

```text
event_name
page
section_id
product_id
rank
category_code
brand
skin_type
sensitivity
concern_tags
effect_tags
score_bucket
price_bucket
algorithm_version
```

GA4에 보내지 않을 값:

```text
고민 원문
이름
이메일
전화번호
정확한 로그인 ID
긴 피부 상태 서술
민감한 건강 정보
score_breakdown 전체 원본
```

## 9. 자체 DB 저장 값

우리 DB에는 추천 개선에 필요한 더 자세한 값을 저장한다.

```text
event_name
event_id
user_id
anonymous_user_id
session_id
request_id
recommendation_id
product_id
rank
source
page
cart_id
order_id
metadata_json
occurred_at
created_at
```

`metadata_json`에는 다음 값을 상황에 따라 담는다.

```text
skin_type
sensitivity
section_id
algorithm_version
concern_tags
effect_tags
category_code
brand
total_score
score_breakdown
visible_ms
scroll_depth
price_bucket
source
utm_source
utm_medium
utm_campaign
feedback_label
feedback_reason_tags
```

## 10. 백엔드 구현 계획

### 10.1 DB 테이블

새 테이블 후보:

```text
event_logs
```

컬럼 후보:

```text
id BIGINT PK
event_id VARCHAR(128) UNIQUE NOT NULL
event_name VARCHAR(80) NOT NULL
occurred_at TIMESTAMP NOT NULL
user_id BIGINT NULL
anonymous_user_id VARCHAR(128) NULL
session_id VARCHAR(128) NULL
request_id VARCHAR(128) NULL
recommendation_id VARCHAR(128) NULL
product_id VARCHAR(128) NULL
rank INT NULL
source VARCHAR(64) NULL
page VARCHAR(255) NULL
cart_id BIGINT NULL
order_id BIGINT NULL
metadata_json JSONB NOT NULL DEFAULT '{}'
created_at TIMESTAMP NOT NULL
```

인덱스 후보:

```text
ux_event_logs_event_id
ix_event_logs_event_name_occurred_at
ix_event_logs_user_id_occurred_at
ix_event_logs_anonymous_session_occurred_at
ix_event_logs_recommendation_id_occurred_at
ix_event_logs_product_event_occurred_at
ix_event_logs_request_id
ix_event_logs_cart_id
ix_event_logs_order_id
```

### 10.2 API

```http
POST /api/events
POST /api/events/batch
```

`POST /api/events`는 단일 이벤트 저장용이다.

`POST /api/events/batch`는 노출 이벤트처럼 짧은 시간에 여러 개가 발생하는 이벤트를 묶어 저장한다.

### 10.3 검증 규칙

- `event_name` 필수
- `event_id`는 선택값이며 없으면 서버가 생성
- `anonymous_user_id`, `session_id`는 비회원 추적용 선택값
- 로그인 사용자의 `user_id`는 프론트가 보내지 않고 서버가 session cookie 기준으로 저장
- `occurred_at` 없으면 서버 수신 시간 사용
- batch 최대 50개
- `metadata_json` 최대 16KB
- 알 수 없는 이벤트 이름은 우선 허용하되, 로그/모니터링 대상
- `email`, `phone`, `address`, `raw_prompt`, `raw_response`, `token`, `password` 등 민감 metadata key는 서버에서 거부

## 11. 프론트 구현 계획

### 11.1 환경변수

```env
VITE_GA_ENABLED=true
VITE_GA_MEASUREMENT_ID=G-XXXXXXXXXX
VITE_EVENT_LOGGING_ENABLED=true
```

### 11.2 파일 구조 후보

```text
apps/frontend/src/lib/analytics/identity.ts
apps/frontend/src/lib/analytics/ga4.ts
apps/frontend/src/lib/analytics/events.ts
apps/frontend/src/lib/analytics/visibility.ts
```

### 11.3 역할

```text
identity.ts
- anonymous_user_id 생성/조회
- session_id 생성/갱신

ga4.ts
- GA4 초기화
- GA4 이벤트 전송

events.ts
- trackEvent(eventName, payload)
- GA4와 백엔드에 동시 전송
- 실패해도 사용자 플로우를 막지 않음

visibility.ts
- IntersectionObserver 기반 노출 이벤트 처리
```

## 12. 구현 순서

```text
1. 이벤트 이름/필드 계약 문서 확정
2. event_logs ERD 확정
3. 백엔드 event_logs 마이그레이션 추가
4. POST /api/events 구현
5. POST /api/events/batch 구현
6. 백엔드 테스트 작성
7. 프론트 anonymous_user_id/session_id 구현
8. 프론트 trackEvent wrapper 구현
9. GA4 Measurement ID 연결
10. page_view/home_view부터 연결
11. 추천 제출/결과/상품 클릭 이벤트 연결
12. 상품 상세/구매 링크 클릭 이벤트 연결
13. impression/section_visible/scroll_depth 연결
14. GA4 DebugView와 DB row를 동시에 확인
15. 커뮤니티 배포 후 이벤트 과다/누락 점검
16. user_preference_profile 배치 설계
17. 개인화 추천 로직에 profile 반영
```

## 13. 개인화 확장 방향

이벤트 로그가 쌓이면 사용자별 취향 프로필을 만든다.

```text
event_logs
-> 사용자별 클릭/노출/구매 링크/피드백 집계
-> user_preference_profile 생성
-> 홈 추천, 검색 랭킹, 상품 정렬에 반영
```

프로필 후보 필드:

```text
anonymous_user_id
preferred_categories
preferred_brands
preferred_effects
preferred_ingredients
price_preference
sensitivity_preference
recent_concern_tags
last_seen_at
updated_at
```

반영 예시:

```text
세럼 클릭이 많음 -> 세럼 가중치 증가
2만원 이하 구매 링크 클릭이 많음 -> 가격대 선호 반영
진정/장벽 상품 클릭이 많음 -> 해당 효능 가중치 증가
특정 브랜드 반복 클릭 -> 브랜드 선호도 증가
구매 링크 클릭한 상품의 성분 -> 선호 성분 후보로 반영
```

## 14. 주의사항

- 이벤트 수집은 사용자 경험을 막으면 안 된다.
- 이벤트 전송 실패로 추천/상세 페이지가 깨지면 안 된다.
- 노출 이벤트는 너무 많이 쌓일 수 있으므로 batch 전송을 우선한다.
- 개인정보와 민감정보는 GA4로 보내지 않는다.
- 자체 DB에도 원문/민감정보 저장은 최소화한다.
- 데이터가 많아지면 retention 정책과 aggregation 테이블이 필요하다.
- GA4와 자체 DB 이벤트 이름이 달라지면 분석이 어려워지므로 공통 enum처럼 관리한다.
- 이벤트는 많이 쌓는 것보다 나중에 해석 가능한 구조로 쌓는 것이 더 중요하다.

## 15. 우선 작업 단위

원우 백엔드 우선 작업:

```text
1. event_logs 테이블
2. /api/events
3. /api/events/batch
4. API 테스트
5. 프론트 전달용 이벤트 계약 정리
```

프론트 우선 작업:

```text
1. anonymous_user_id/session_id
2. GA4 연결
3. trackEvent wrapper
4. 추천/상품/홈 핵심 이벤트 연결
5. 노출/스크롤 이벤트 연결
```

인프라/운영 확인 사항:

```text
1. 커뮤니티 배포 서버 GA4 Measurement ID 설정
2. VITE_GA_ENABLED 환경변수 설정
3. 이벤트 로그 테이블 마이그레이션 적용
4. 운영 DB 저장량 모니터링
5. 필요 시 오래된 raw event 보관 기간 결정
```

## 16. 수집하려는 데이터 범위

### 16.1 지금 가져오려는 데이터

초기 목표는 커뮤니티 배포 후 사용자가 서비스를 어떻게 쓰는지 빠르게 파악하고, 추천 품질 개선에 필요한 최소 행동 데이터를 확보하는 것이다.

```text
유입 데이터:
- 어디서 들어왔는지
- 커뮤니티, 검색, 직접 방문, SNS, UTM
- 모바일/PC, 브라우저, OS, 지역, 언어

서비스 흐름 데이터:
- 홈 진입
- 추천 요청 제출
- 추천 결과 페이지 진입
- 상품 상세 페이지 진입
- 구매 링크 클릭

추천 결과 반응 데이터:
- 어떤 추천 결과가 노출됐는지
- 몇 위 상품을 봤는지
- 몇 위 상품을 눌렀는지
- 어떤 product_id가 눌렸는지
- 어떤 recommendation_id에서 발생했는지

상품/홈 반응 데이터:
- 홈 섹션 노출
- 홈 상품 노출
- 홈 상품 클릭
- 카테고리 탭 클릭

기본 관심도 데이터:
- 스크롤 깊이
- 섹션 실제 노출 여부
- 상품 카드 실제 노출 여부
- AI 추천 설명 영역 노출/확장 여부
```

이 데이터로 먼저 확인하려는 질문:

```text
방문자가 추천 버튼까지 누르는가?
추천 결과를 본 뒤 상품 상세로 이동하는가?
상품 상세에서 구매 링크까지 누르는가?
상위 랭크 상품이 실제로 더 많이 클릭되는가?
사용자가 상품 50개 중 어디까지 보는가?
홈의 어떤 섹션이 실제 클릭으로 이어지는가?
AI 추천 설명이 클릭률에 영향을 주는가?
```

### 16.2 추후 더 가져오려는 데이터

서비스가 조금 더 커지면 개인화 추천과 랭킹 튜닝에 직접 사용할 데이터를 확장한다.

```text
사용자 선호 데이터:
- 반복 클릭한 카테고리
- 반복 클릭한 브랜드
- 반복 클릭한 가격대
- 반복 클릭한 효능 태그
- 반복 클릭한 성분

전환 데이터:
- 찜
- 장바구니
- 실제 구매
- 구매 실패/이탈
- 재방문 후 구매 링크 클릭

피드백 데이터:
- 추천이 마음에 들었는지
- 별로였던 이유
- 가격, 브랜드, 제형, 성분, 피부타입 불일치 같은 사유

고도화 분석 데이터:
- 추천 알고리즘 버전
- A/B 테스트 그룹
- score_breakdown
- 노출 대비 클릭률
- 클릭 대비 구매 링크 클릭률
- 재방문자의 행동 변화
```

개인화로 연결되는 방식:

```text
상품 노출 -> 클릭 안 함:
- 사용자가 봤지만 반응하지 않은 후보로 기록

상품 노출 -> 클릭:
- 관심 후보로 기록

상품 상세 -> 구매 링크 클릭:
- 강한 선호 신호로 기록

피드백 좋음:
- 추천 방향 강화

피드백 나쁨:
- 해당 조건, 제품군, 가격대, 성분 방향 감점 후보
```

## 17. 파트별 작업과 업무량

| 파트 | 해야 할 일 | 담당 추천 | 예상 업무량 |
| --- | --- | --- | --- |
| 이벤트 설계 | 이벤트 이름, payload 필드, GA4/DB 저장 기준 확정 | 원우 주도 | 반나절 |
| 백엔드 로그 저장 | `event_logs`, `/api/events`, `/api/events/batch`, 테스트 | 원우 | 1~2일 |
| 프론트 식별자 | `anonymous_user_id`, `session_id` 생성/보관 | 프론트 | 반나절 |
| GA4 연결 | Measurement ID 연결, page_view/custom event 전송 | 프론트/인프라 | 반나절~1일 |
| UI 이벤트 연결 | 추천 클릭, 상품 클릭, 구매 링크 클릭 등 화면별 이벤트 연결 | 프론트 | 1~2일 |
| 노출/체류 측정 | `IntersectionObserver`, visible_ms, scroll_depth | 프론트 | 1일 |
| 운영 설정 | 배포 서버 환경변수, GA4 속성, 마이그레이션 적용 | 인프라 | 반나절 |
| 검증 | GA4 DebugView와 DB row 동시 확인 | 원우+프론트 | 반나절 |
| 분석 기반 | 클릭률/전환율 쿼리, 개인화 프로필 설계 | 원우 주도 | 1일 이상 |

## 18. 원우가 힘을 줄 범위와 위임할 범위

### 18.1 원우가 주도하면 좋은 부분

원우는 백엔드와 추천 로직 담당이므로, 개인화 추천으로 이어질 데이터 구조를 책임지는 쪽이 좋다.

```text
1. 이벤트 계약 문서 확정
2. event_logs DB 테이블 설계
3. 마이그레이션 작성
4. POST /api/events 구현
5. POST /api/events/batch 구현
6. 이벤트 payload 검증
7. 테스트 작성
8. 프론트에 넘길 API 사용법 작성
9. 클릭률/전환율 확인용 기본 쿼리 정리
10. user_preference_profile 설계
```

여기까지 하면 프론트에서 이벤트를 보내기만 해도 우리 DB에는 개인화 추천에 쓸 수 있는 원천 데이터가 쌓인다.

### 18.2 프론트에게 부탁할 부분

프론트는 실제 사용자 행동이 발생하는 위치를 가장 잘 알고 있으므로, 이벤트 감지와 전송을 맡는 것이 좋다.

```text
1. GA4 연결
2. anonymous_user_id/session_id 생성
3. trackEvent() 공통 함수 구현
4. GA4와 /api/events 동시 전송
5. 추천/상품/홈 핵심 이벤트 연결
6. IntersectionObserver 기반 노출 이벤트 연결
7. scroll_depth, visible_ms 측정
```

프론트에 전달할 요청 메시지 초안:

```text
GA4와 자체 이벤트 로그를 같이 붙이려고 합니다.

프론트에서는 anonymous_user_id/session_id를 생성하고,
trackEvent(eventName, payload) 공통 함수를 만들어
GA4와 백엔드 /api/events 또는 /api/events/batch 양쪽으로 보내주세요.

우선 연결할 이벤트:
- recommendation_submit
- recommendation_result_view
- recommendation_product_impression
- recommendation_product_click
- product_detail_view
- purchase_link_click
- home_section_view
- home_product_click
- scroll_depth

상품 노출은 렌더링 기준이 아니라 실제 화면 노출 기준으로 찍는 것이 좋습니다.
예: 카드가 50% 이상 0.5초 이상 보였을 때 impression 전송.

GA4에는 고민 원문은 보내지 않고, concern_tags나 score_bucket 같은 가공된 값만 보내는 방향이 안전합니다.
```

### 18.3 인프라에게 부탁할 부분

```text
1. GA4 속성 생성
2. Web Stream 생성
3. Measurement ID 공유
4. 커뮤니티 배포 서버에 VITE_GA_MEASUREMENT_ID 설정
5. VITE_GA_ENABLED 설정
6. event_logs 마이그레이션 배포 DB 적용
7. 운영 DB 이벤트 저장량 모니터링
```

인프라에 전달할 요청 메시지 초안:

```text
커뮤니티 배포에서 사용자 행동 분석을 위해 GA4를 붙이려고 합니다.

GA4 속성과 Web Stream을 생성하고 Measurement ID를 공유해주세요.
프론트 배포 환경에는 아래 환경변수가 필요합니다.

VITE_GA_ENABLED=true
VITE_GA_MEASUREMENT_ID=G-XXXXXXXXXX

백엔드에는 event_logs 테이블 마이그레이션이 추가될 예정이라,
배포 DB에 마이그레이션 적용도 필요합니다.
추후 이벤트 로그가 많이 쌓일 수 있으니 DB 저장량 모니터링과 보관 기간 정책도 같이 논의가 필요합니다.
```

### 18.4 팀장/기획과 정해야 할 부분

```text
1. 고민 원문을 저장할지 여부
2. GA4에 어떤 사용자 속성까지 보낼지
3. 피부 타입/민감도 값을 GA4에 보낼 수 있는지
4. event_logs 보관 기간
5. 피드백 수집 문구와 선택지
6. 개인화 추천에 사용할 수 있는 데이터 범위
```

팀장/기획에 전달할 요청 메시지 초안:

```text
사용자 행동 로그를 GA4와 자체 DB에 같이 수집하려고 합니다.

다만 고민 원문, 피부 상태, 민감도 같은 값은 민감하게 볼 수 있어서
GA4에는 원문을 보내지 않고 concern_tags처럼 가공된 값만 보내는 방향을 제안합니다.

정해야 할 것:
- 고민 원문을 자체 DB에 저장할지
- 저장한다면 보관 기간을 얼마나 둘지
- GA4에는 skin_type, sensitivity, concern_tags 정도를 보내도 되는지
- 추천 피드백 선택지를 어떻게 둘지
- 개인화 추천에 사용할 수 있는 행동 데이터 범위를 어디까지로 볼지
```
