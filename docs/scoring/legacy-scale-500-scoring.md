# 500성분 레거시 스케일 점수 확장

상태: 2026-07-13 런타임 반영 완료
정책 버전: `mwbl-legacy-scale-500-v1`
런타임 scoring version: `v5_legacy_scale_500`

## 결과

기존 34개와 동결된 신규 466개를 합친 정확한 500개 성분을 같은 작업 단위로 평가했다.

| 항목 | 기존 | 확장 후 |
| --- | ---: | ---: |
| 점수 활성 성분 | 34 | 187 |
| 성분×효능 점수쌍 | 72 | 245 |
| 근거 행 | 72 | 107 |

신규 활성은 153개 성분·173쌍이다. 500개 중 남은 313개는 전문 또는 사람 승인을 받지
못해서 0점이 된 것이 아니다. 기존 6효능에 연결할 좁은 공식 기능 신호나 구조화된 긍정
논문쌍이 없어 긍정 효능점수를 만들지 않은 성분이다.

## 기존 34개 점수의 실제 계보

기존 34개·72쌍은 Excel 수식으로 계산된 값이 아니다.

- A군 30개·67쌍: `a_group_effect_matrix_review.csv`의 사람이 입력한 `effect_score`를 그대로 복사
- B군 4개·5쌍: `b_group_batch1_evidence_scout.csv`의 선택된 `proposed_effect_score`를 수동 추가
- 현재 72쌍 범위: 30~74점

따라서 새 466개에 적용할 완전한 원본 산식은 존재하지 않는다. 확장 규칙은 기존 숫자를
재계산하지 않고, 신규 성분이 기존 검수 성분을 과도하게 앞지르지 않도록 실제 legacy
점수 분포의 바닥값을 사용하는 결정적 규칙으로 고정했다.

## 확장 규칙

### 1. 기존 34개 보존

기존 72쌍은 값과 순서를 그대로 유지한다. baseline SHA-256은
`ddb884a0ec14893814bf9c6236f2d7871b0210eb8afa0f254645fc226f37eb50`이다.

### 2. 공식 기능 prior

`build_ingredient_role_inventory.py`에 이미 승인된 좁은 CosIng 기능만 사용한다.

- high: 해당 효능축의 기존 34개 최저점
- medium: 전체 legacy 최저점 30
- 공식 기능 prior만 있는 쌍은 `ingredient_evidence`를 만들지 않아 근거점수는 0

| 효능축 | high 점수 | medium 점수 |
| --- | ---: | ---: |
| 미백·톤 | 43 | 30 |
| 주름·탄력 | 42 | 30 |
| 여드름·피지 | 40 | 30 |
| 보습·장벽 | 32 | 30 |
| 진정 | 33 | 30 |
| 각질 | 30 | 30 |

동결 466에서 공식 기능 prior는 신규 138개·144쌍이다.

### 3. 구조화 논문 override

v1.3의 긍정 논문 구조화 결과 24개 성분·35쌍은 4/6/8 값을 직접 쓰지 않고 legacy
점수대로 변환한다.

| 논문 분류 | effect_score | 별도 evidence_score |
| --- | ---: | ---: |
| primary | 70 | 50 |
| supporting | 50 | 35 |
| limited_medical | 35 | 25 |

공식 기능 prior와 같은 쌍이면 더 큰 `effect_score`를 사용한다. 논문 override가 공식 기능
prior 밖에 15개 성분·29쌍을 추가해 최종 신규 활성은 153개·173쌍이다.

### 4. 차단 규칙 제거

다음 값은 이번 런타임 점수의 차단 조건이 아니다.

- `full_text_status`
- `review_status`
- 사람 adjudication 또는 운영 승인 여부

검수 상태는 감사 메타데이터로 보존한다. 공식 기능 prior는 임상 근거로 표시하지 않으며,
추천 사유에도 `공식 성분 기능 분류 기반`이라고 별도로 표기한다.

상품 상세의 논문 제목·요약·출처 노출은 점수 활성과 분리한다. 공개 API에는
`review_status=accepted + is_current=true`인 근거만 반환하며, 신규 35행처럼
`candidate_unverified`인 근거는 내부 점수에는 사용할 수 있어도 고객 화면에는 노출하지 않는다.

## 실제 상품 도달률

성분 데이터가 있는 실제 65,955개 상품 기준이다.

| 축 | 기존 34 | 확장 후 |
| --- | ---: | ---: |
| 점수 성분 1개 이상 | 82.89% | 96.47% |
| 보습·장벽 | 81.13% | 96.06% |
| 진정 | 79.40% | 86.62% |
| 여드름·피지 | 25.97% | 33.93% |
| 각질 | 62.79% | 63.16% |
| 미백·톤 | 22.45% | 24.74% |
| 주름·탄력 | 46.81% | 49.17% |

## 정본과 재생성

- 런타임: `data/ingredient_effect.csv`, `data/ingredient_evidence.csv`
- 기존 34 baseline: `data/reconciliation/legacy_scale_500/baseline_*.csv`
- 논문 override: `data/reconciliation/legacy_scale_500_paper_overrides.csv`
- 500개·245쌍 감사표: `data/reconciliation/legacy_scale_500/`
- 재생성: `python data/scripts/build_legacy_scale_500_scoring.py --apply-runtime`

재생성 스크립트는 기존 34 점수 변경, 500개 cohort 이탈, 중복 pair와 중복 근거 키를
오류로 처리한다.
