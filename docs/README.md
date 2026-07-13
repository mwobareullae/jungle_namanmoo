# 뭐바를래 문서 길잡이

문서를 처음 볼 때는 이 파일의 읽는 순서를 따른다. 문서와 실제 구현이 다르면 코드, migration, 테스트를 우선한다.

## 먼저 읽을 문서

1. [데이터 계약](data/data-contract.md)
2. [P2 AI 커머스 범위](00-overview/p2-ai-commerce-contract.md)
3. [상품 검색 API](api/catalog-search-api-contract.md)
4. [홈 섹션 API](api/home-sections-api-contract.md)
5. [주문·결제 API](api/order-payment-api-contract.md)
6. [커머스 액션 에이전트 API](api/action-agent-api-contract.md)
7. [홈 개인화 추천](recommendation/home-personalized-ranking.md)
8. [추천 기본 스코어링](recommendation/backend-scoring-v0.md)
9. [백엔드 테스트](operations/backend-testing.md)

## 폴더별 역할

| 폴더 | 내용 | 우선해서 볼 문서 |
| --- | --- | --- |
| `00-overview` | 프로젝트 범위, 발표 자료, 전체 정리 | `final-deliverables-index.md`, `final-deliverables/` |
| `api` | 프론트와 백엔드가 맞춰야 하는 API 계약 | `catalog-search-api-contract.md`, `order-payment-api-contract.md` |
| `admin` | 관리자 화면과 운영 화면 설계 | 관리자 담당 작업을 확인할 때 참고 |
| `analytics` | 행동 이벤트와 인기 데이터 수집 계약 | `analytics-event-roadmap.md`, `popularity-event-frontend-contract.md` |
| `data` | 상품·성분·리뷰·seed 데이터 구조와 품질 | `data-contract.md`, `dev-data-subsets.md` |
| `operations` | 백엔드 테스트, 적재·rollup 운영 | `backend-testing.md`, `review-import-operations.md` |
| `performance` | 성능 테스트, 목표 수치, 실행 결과 기록 | `README.md`, `load-testing.md`, `records/` |
| `recommendation` | 홈 추천과 추천 점수 설계 | `home-personalized-ranking.md`, `backend-scoring-v0.md` |
| `search` | 일반 검색, 임베딩, 색인, 검색 품질 | `catalog-search-v1-behavior-spec.md`, `embedding-plan.md` |
| `scoring` | 성분 근거와 추천 점수의 상세 정책 | `scoring-design.md`, `evidence-policy.md` |

## 관심사별 읽는 위치

### 일반 상품 검색

- 동작 기준: [검색 동작 명세](search/catalog-search-v1-behavior-spec.md)
- 요청·응답: [검색 API 계약](api/catalog-search-api-contract.md)
- 색인·성능: [검색 성능 최적화](search/catalog-search-performance-optimization.md)
- 오탈자·동의어·결과 없음: [검색 보완 계획](search/search-synonym-no-result-plan.md)

### 피부 고민 맞춤 추천

- 홈 개인화: [홈 개인화 랭킹](recommendation/home-personalized-ranking.md)
- 기본 점수: [백엔드 스코어링 v0](recommendation/backend-scoring-v0.md)
- 성분 근거: [스코어링 설계](scoring/scoring-design.md)
- 후보 생성: [후보 생성 계획](recommendation/f180-candidate-generation-plan.md)

### 홈 화면

- 섹션 목록과 endpoint: [홈 섹션 API 계약](api/home-sections-api-contract.md)
- 비로그인 추천: [콜드 스타트 랭킹](recommendation/home-cold-start-ranking.md)
- 로그인 추천: [개인화 랭킹](recommendation/home-personalized-ranking.md)

### 주문·결제·리뷰

- 주문과 결제: [주문·결제 API 계약](api/order-payment-api-contract.md)
- 장바구니 결제 흐름: [장바구니·체크아웃 API 계약](api/cart-checkout-api-contract.md)
- 대화형 장바구니·주문 흐름: [커머스 액션 에이전트 API 계약](api/action-agent-api-contract.md)
- 리뷰 요청·응답: [리뷰 API 계약](api/review-api-contract.md)

### 성능 테스트

- 실행 방법: [성능 테스트 길잡이](performance/README.md)
- 부하 테스트: [부하 테스트 실행 방법](performance/load-testing.md)
- 검색 성능: [검색 성능 최적화 기록](performance/catalog-search-performance-optimization.md)
- 실제 실행 결과: [성능 테스트 기록](performance/records/)

### 데이터·운영

- 데이터 구조: [데이터 계약](data/data-contract.md)
- 개발용 데이터 subset: [개발 데이터 subset](data/dev-data-subsets.md)
- 테스트: [백엔드 테스트](operations/backend-testing.md)
- 부하 테스트: [부하 테스트](operations/load-testing.md)

## 문서 상태 읽는 법

- `*-contract.md`: 다른 역할과 맞춰야 하는 요청·응답 또는 데이터 계약
- `*-spec.md`: 기능 동작 기준
- `*-plan.md`, `*-blueprint.md`, `*-draft.md`: 계획·초안이므로 현재 구현을 단정하지 않는다
- `*-report.md`: 특정 시점의 결과 기록
- `*-operations.md`: seed, rollup, 색인, 배포 등 실행 방법

현재 구현 여부를 확인할 때는 문서만 읽지 말고 해당 API router, service, model, migration, 테스트를 함께 확인한다.
