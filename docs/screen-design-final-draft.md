# 뭐바를래 화면 설계 최종 초안

작성일: 2026-07-10
상태: Draft — 화면 route/API 계약 변경 전 확인 필요
분류: **부록 B — 기술 리포트의 사용자 경험을 화면으로 옮긴 예시 초안**
범위: P2 고객 추천 여정 + 내부 추천 품질 검증 화면

> 이 문서는 확정 UI/API 계약이 아니다. 구현 범위와 화면 우선순위는 기존 코드·최신 API 계약·팀 합의를 우선한다.

## 1. 화면 설계 목표

사용자는 다음 세 가지를 화면에서 바로 이해해야 한다.

1. 내 자연어 고민을 시스템이 어떻게 해석했는가
2. 왜 이 상품이 다른 상품보다 위에 추천됐는가
3. 추천 근거를 확인한 뒤 실제 구매 흐름으로 이동할 수 있는가

내부 운영자는 다음을 확인할 수 있어야 한다.

1. 리뷰 기반 평가 데이터가 신뢰 가능한가
2. 추천 알고리즘이 baseline보다 적합한가
3. 추천 품질 개선이 응답 성능 악화로 이어지지 않았는가

## 2. 전체 화면 흐름

```text
홈/추천 진입
   ↓
고민 입력
   ↓
분석 진행
   ↓
추천 결과 + 입력 해석 요약
   ↓
추천 근거 상세
   ↓
상품 상세
   ↓
장바구니 → Checkout

내부 운영
Admin → 추천 품질 → 데이터 QA / Ranking / 성능 / Ablation
```

현재 route 구조를 임의로 바꾸지 않는다. 고객 추천 흐름은 기존 `/search` 내부 상태와 컴포넌트를 활용하고, 상품 상세는 기존 `recommendation_id` query를 유지한다. 별도 route가 필요하면 구현 전에 API/화면 flow를 확인한다.

## 3. 고객 화면

### 화면 1. 고민 입력

목적:

- 사용자가 전문 용어 없이 고민을 입력한다.
- 피부 타입·민감도·회피 성분이 추천 조건으로 함께 전달되는 것을 보여준다.

핵심 구성:

```text
[피부 타입 segmented control]
[민감도 segmented control]

피부 고민
┌────────────────────────────────────┐
│ 속은 당기는데 겉은 기름지고,       │
│ 자극 없는 진정 세럼을 찾고 있어요. │
└────────────────────────────────────┘

내 프로필에서 적용
민감도 높음 · 알코올 회피

[추천 시작]
```

UX 원칙:

- 입력 예시는 사용자의 표현을 돕되 정답 키워드를 강요하지 않는다.
- 저장된 프로필의 회피 성분은 숨기지 않고 적용 상태를 표시한다.
- 회피 성분 수정은 기존 프로필/입력 flow와 충돌하지 않게 제공한다.
- 빈 문자열과 글자 수 제한을 즉시 안내한다.

기존 컴포넌트 활용:

- `ConcernInputPage`
- `SkinTestPromptModal`
- `SignupSkinProfilePage`

### 화면 2. 분석 진행

목적:

- 긴 추천 요청에서 사용자가 멈춘 것으로 오해하지 않게 한다.
- 단순한 “AI 분석 중”이 아니라 실제 추천 단계를 보여준다.

단계:

```text
1. 피부 고민 해석
2. 기대 효능 연결
3. 상품 후보 검색
4. 함량·근거 검증
5. 추천 순위 계산
```

상태 처리:

- 정상: 현재 단계 표시
- 3초 이상: “근거를 확인하고 있어요” 안내
- timeout: 다시 시도 / 입력 수정
- fallback: 사용자에게 내부 오류명 대신 제한된 추천이 제공됐음을 명확히 안내

기존 컴포넌트 활용:

- `AnalysisLoadingPage`

### 화면 3. 추천 결과

목적:

- 상품 목록보다 먼저 입력 해석이 맞는지 확인시킨다.
- 각 상품이 추천된 핵심 이유를 한눈에 비교하게 한다.

상단 해석 요약:

```text
입력 요약       수부지 · 민감도 높음 · 알코올 회피
해석된 고민     속건조 · 피지 · 민감
추천 효능       보습 장벽 · 진정 · 피지 케어
구매 조건       세럼 · 30,000원 이하
부분 매칭       해석하지 못한 표현이 있을 때만 표시
```

상품 카드 정보 우선순위:

1. 추천 순위와 추천점수
2. 핵심 추천 이유 한 문장
3. 핵심 성분 2~3개
4. 함량 상태: optimal/meaningful/unknown
5. 근거 수준
6. 민감 피부 위험/회피 성분 위반 여부
7. 가격

카드 CTA:

- `왜 추천했나요` → 근거 상세
- 카드 본문 → 상품 상세
- 비교 선택은 최대 2~3개

정렬:

- 추천점수순
- 가격순
- 위험 적은 순

기존 컴포넌트 활용:

- `RecommendationResultsPage`
- `ProductCard`
- `Badge`

### 화면 4. 추천 근거 상세

목적:

- 내부 score 숫자를 나열하는 대신 추천 논리를 사용자 언어로 설명한다.
- 상세한 근거와 한계를 함께 보여준다.

핵심 경로:

```text
내 고민
속건조 · 민감
   ↓
필요한 효능
보습 장벽 · 진정
   ↓
핵심 성분
세라마이드 · 판테놀
   ↓
함량 판단
optimal / meaningful / unknown
   ↓
근거
논문 · DOI/PMID · 식약처 고시
```

Score breakdown 표현:

- 기본 화면: 상위 기여 축 3개만 표시
- `상세 점수 보기`: 전체 축과 위험 penalty 표시
- coefficient와 component score를 혼동하지 않게 구분
- weight profile과 scoring version은 접힌 기술 정보에 배치

근거 카드:

- 성분명
- 연결 효능
- 근거 수준
- 소비자용 근거 요약
- 출처 유형
- 외부 원문 링크

필수 주석:

> 해당 근거는 성분과 효능의 연결을 설명하며, 제품 자체의 임상 효능을 보장하지 않습니다.

함량 unknown 처리:

> 공개된 함량 정보가 없어 성분 포함 여부와 다른 근거를 중심으로 평가했습니다.

기존 컴포넌트 활용:

- `ProductDetailSpaPage`
- `ProductComparisonPanel`
- recommendation narrative API

### 화면 5. 상품 상세와 구매 연결

목적:

- 추천 근거를 읽은 사용자가 구매 정보로 자연스럽게 이동한다.
- 추천 attribution을 장바구니까지 유지한다.

상단:

- `추천 1위` 또는 추천 context 표시
- 추천 이유 요약
- 상품 이미지·브랜드·가격

본문 탭:

- 상품 설명
- 전성분
- 추천 근거
- 리뷰
- Q&A

하단 고정 CTA:

- 찜
- 장바구니
- 구매하기

전달 데이터:

```text
recommendation_id
product_id
recommendation_rank
source=ai_recommendation
```

### 화면 6. 장바구니/Checkout

목적:

- 추천이 실제 커머스 flow로 연결되는 것을 검증한다.
- 추천 상품임을 과도하게 강조하지 않고 attribution만 유지한다.

표시:

- 상품·수량·가격
- 판매/재고 상태
- 추천으로 담은 상품 표시
- 주문 예상 금액
- 배송 정책

검증:

- 재고 부족
- 가격 변경
- 판매 중지
- recommendation context 보존

## 4. 내부 추천 품질 검증 화면

고객 화면에는 HitRate, NDCG 같은 내부 평가 지표를 노출하지 않는다. 기존 Admin 영역에 추천 품질 탭을 추가하는 방향으로 설계한다.

### 화면 7. 추천 품질 Overview

필터:

```text
dataset version
scoring version
Git SHA
review split
category / concern / skin type
head / mid / tail popularity
```

상단 KPI:

- HitRate@10
- MRR@10
- Recall@50
- Concern-group NDCG@10
- Negative exposure@10
- Hard constraint violation

탭:

1. Label QA
2. Ranking
3. Slice
4. Ablation
5. Failed cases
6. Performance

### 화면 8. Label QA

- Product mapping rate
- Concern extraction precision
- Effect sentiment precision
- Leakage rate
- Human agreement
- Label coverage
- relevance grade 분포
- 제외 사유 분포

운영 액션:

- leakage 사례 검수
- confidence 낮은 label 필터
- review 원문과 정제 query 비교
- 개인정보/식별 정보 노출 확인

### 화면 9. Ablation 비교

행:

```text
인기순
BM25
성분-only
+효능
+근거
+함량
전체 scoring
```

열:

```text
HitRate@10
MRR@10
Recall@50
NDCG@10
Negative exposure@10
constraint violation
추천 core p95
```

추천 품질과 latency를 같은 표에서 확인해, 품질 개선이 성능 악화로 이어졌는지 판단한다.

### 화면 10. Failed case 상세

```text
정제된 고민
기대 label 상품
실제 Top-10
후보 Recall 성공/실패
score breakdown
근거/함량 coverage
fallback 여부
```

원인 분류:

- parser error
- candidate retrieval miss
- scoring weight issue
- evidence missing
- concentration missing
- hard constraint error
- popularity bias

## 5. 반응형 우선순위

### Mobile

- 한 화면에 하나의 핵심 결정만 표시
- 해석 요약은 접기 가능
- 추천 상품은 1열
- 상위 추천 이유와 CTA를 이미지보다 먼저 읽을 수 있게 구성
- 근거 경로는 세로 흐름
- 구매 CTA는 하단 고정

### Desktop

- 추천 요약과 상품 목록을 같은 첫 화면에 배치
- 상품은 2~3열
- 근거 상세는 상품 정보와 병렬 배치 가능
- 비교 기능은 우측 panel 또는 overlay

## 6. 이벤트 설계

화면별 최소 이벤트:

| 화면 | 이벤트 |
| --- | --- |
| 고민 입력 | recommendation_started |
| 추천 결과 | recommendation_result_viewed |
| 상품 카드 | recommendation_product_impression |
| 상품 클릭 | recommendation_product_click |
| 근거 상세 | recommendation_evidence_viewed |
| 비교 | recommendation_comparison_opened |
| 장바구니 | cart_item_added + recommendation_id/rank |
| Checkout | checkout_started |
| 구매 | order_paid |
| 부정 행동 | wishlist_removed / cart_removed |

이벤트 taxonomy를 실제로 변경할 때는 프로젝트 규칙에 따라 구현 전에 확인한다.

## 7. 구현 우선순위

### P0 — 발표와 핵심 사용자 가치

1. 추천 결과 상단의 입력 해석 요약
2. 카드의 추천 이유·함량 상태·근거 수준
3. 추천 근거 상세 경로
4. recommendation context를 장바구니까지 유지
5. loading 단계와 timeout/fallback UX

### P1 — 추천 품질 운영

1. 추천 품질 Overview
2. Label QA
3. Ablation 비교
4. Failed case 상세

### P2 — 확장

1. 행동 개인화 결과 표시
2. cache 적용 상태 관측
3. online experiment 비교

## 8. 구현 전 확인이 필요한 결정

- 화면 route 구조 변경
- 추천 API response 필드 변경
- score breakdown의 사용자 노출 범위
- 논문/고시 외부 링크 정책
- 리뷰 원문과 정제 label의 운영자 노출 범위
- 이벤트 taxonomy 변경
- 행동 개인화 적용과 설명 방식
