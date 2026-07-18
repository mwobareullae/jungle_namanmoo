# feat: 함량 추정치 씨드 오버레이 (플래그, **기본 켜짐 제안**)

**브랜치:** `feat/concentration-estimate-overlay` (origin/dev e34363e 기반) · push는 팀 결정

> ## 🚧 병합 게이트 — 사용자 노출 전 반드시 처리
> 이 오버레이를 켜면 함량 값이 **실측이 아닌 추정치**(KCIA 고시·법정 상한 등)로 채워진다.
> 채점 내부용으론 문제없으나, **함량 버킷이 사용자 UI의 "함량 과다 주의" 경고로 노출되는
> 경로가 있다면**, 추정치(예: 법정 상한 1%)가 실제 함유량이 아닌데도 "과다"로 경고될 수
> 있어 **오인·법적 위험**이 있다.
> **필수 후속(별도 작업):** product_ingredients에 '추정치 출처' 표식(컬럼/마이그레이션)을
> 추가하고, 추정치 출처 행의 **과다-경고를 억제**(긍정 신호 '적정'은 살리고 경고만 차단)한
> 뒤에 사용자 노출을 허용할 것. 이 처리 전에는 `=false`로 두거나 채점 내부용으로만 사용.
> **로컬 클론 증명(2026-07-19):** 켜면 함량 있는 상품 919→1,251(+332), 버킷 unknown→적정
> 이동 확인. 실측 무변경.

## 목적 — 함량(%) 정보를 계산에 실제로 태운다

함량 축은 `product_ingredients.normalized_concentration_value`를 읽는데, 실측값은
전체의 0.57%뿐이라 축이 사실상 상수였다. KCIA 고시·법정 사용한도·성분 표기 규칙으로
만든 추정치(`data/reconciliation/concentration_coverage_estimates.csv`)가 이미 repo에
있으나 **어떤 코드도 읽지 않았다.** 이 PR은 씨드 시점에 그 추정치를 함량이 빈 행에만
오버레이해 함량 축을 근거 기반 신호로 만든다.

## ⚠️ 정직한 가치 규정 — 지표 향상이 아니다

로컬 A/B(주입·LLM-on·정품마운트 3방식) 결과 함량 데이터를 채워도 **리뷰파생 정답셋
(실버·v3·v4)에서 추천 지표는 개선되지 않는다(무승부~미세하락).** 이유는 그 심판들이
성분과학 축을 구조적으로 벌주기 때문(별건 `RESULT_vocab_isolation_20260719`). 따라서
이 PR의 가치는:

- **투명성·경고**: "함량 과다 주의(민감 피부)" 등 버킷/경고가 실제 데이터로 작동
- **콜드스타트**: 리뷰 없는 신상품의 함량 판단 근거 제공
- **정확성**: 죽어 있던 축을 근거 기반으로 되살림

**추천 순위 지표를 올리려는 것이 아님.** 합격 기준은 지표가 아니라 "의도한 행만
정확히 채워졌나"의 기계적 검증이어야 한다.

## 변경

- `app/core/config.py`: `concentration_estimate_overlay_enabled` 플래그 (**기본 True — 이 PR이 제안**, `=false`로 끔).
- `app/services/concentration_estimates.py` (신규): 추정치 로더 + 신뢰정책.
  - 허용 전략: exact / range / regulatory_anchor / legal_upper_bound / lower_bound
  - **제외**: prior_estimate(정제수 순수 휴리스틱) · marker_upper_bound(≤1% 상한을
    점값으로 쓰면 버킷 오분류) — 노이즈 42k행 배제. 실제 파일에서 **4,096개** 선별.
  - 대표값: 범위 중앙값 / 상한 / 하한. 각 행 confidence가 채점의 confidence_multiplier로 할인됨.
- `app/services/db_seed.py`: 함량 실측이 **NULL인 행에만** 오버레이(실측 무덮어쓰기),
  채운 행 수를 `seed.concentration_overlay` 성능이벤트로 로깅.
- `tests/test_concentration_estimates.py`: 로더·정책 단위 테스트 5종.

## 안전성

- **기본 켜짐(제안)** — 채점 내부에서 함량 축이 근거 기반으로 작동. 되돌리려면 `CONCENTRATION_ESTIMATE_OVERLAY_ENABLED=false`.
- 실측값 절대 무덮어쓰기 (NULL 행만).
- 파일 없으면 무동작.
- **프로덕션 반영은 여전히 머지+배포+재씨드가 필요** (플래그만으론 기존 DB 불변).
- ⚠️ 사용자 경고 노출은 위 병합 게이트 처리 후에만.

## 적용·검증 절차 (권장)

1. 로컬 클론 DB에 `CONCENTRATION_ESTIMATE_OVERLAY_ENABLED=true`로 재씨드 → 로그의
   `overlay_filled_rows` 확인 (예상 ≤4,096).
2. 함량 피처 재롤업 후 버킷 분포 diff (optimal/below_meaningful/excessive 등).
3. 기계적 회귀: 실측 행 무변동, 미주입 상품 무변동(체크섬), 과다경고 스팟체크.
4. **주의**: A/B 측정 시 정품 data 마운트 필수(효과축 살아있는 상태 —
   `fix/concern-effect-vocab-guard` 참고), 아니면 함량 효과가 안 보인다.

전 과정 근거: `experiment_log.jsonl` RESULT_conc_data_ab_20260718 · RESULT_vocab_isolation_20260719.
