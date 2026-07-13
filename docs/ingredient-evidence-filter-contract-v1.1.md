# 뭐바를래 성분 근거 필터 계약 v1.1

## 1. 목적과 적용 범위

이 계약은 화장품 성분별 인체 피부 도포 근거를 검색·선별·추출·검수할 때 사용하는
재현 가능한 데이터 계약이다. 기존 6효능 점수와 새 효능 후보를 찾되, 이번 파이프라인은
근거 후보를 생성할 뿐 DB, seed, 추천 런타임 점수를 변경하지 않는다.

v1.1의 핵심 변경은 다음과 같다.

- 논문 한 행에 여러 지표·방향·통계를 합치지 않는다.
- 판정 단위는 `성분 × 연구 × 비교 × 결과지표 × 시점`이다.
- 적격성, 전문 검증, 적용범위, 효능 매핑, 결과 방향, 점수 사용 여부를 서로 다른 상태축으로 기록한다.
- 초록 기반의 긍정 신호는 보존하되 전문 확인 전에는 점수 후보가 될 수 없다.
- 검색 대상 manifest와 사용한 사전의 버전·SHA-256을 모든 산출물에서 추적한다.
- v1 파일을 덮어쓰지 않고 `_v1_1` 산출물을 새로 만든다.

규범 표현은 다음 의미로 사용한다.

- `반드시`: 충족하지 않으면 계약 위반이다.
- `할 수 있다`: 조건을 충족하면 허용한다.
- `금지`: 해당 값을 점수 또는 자동 매핑에 사용할 수 없다.

## 2. 공통 불변식

1. 모든 자동 산출물은 `review_status=candidate_unverified`이다.
2. 모든 자동 산출물은 `runtime_score_change=none`이다.
3. `score_status`만 점수 후보 여부를 나타낸다. `primary_status`는 호환용 표시값이다.
4. 원시 검색 결과와 v1 산출물은 수정·삭제하지 않는다.
5. 값이 확인되지 않으면 추정하지 않고 빈 값, `not_checked`, `not_extracted`, `not_assessable` 중 계약상 맞는 값을 사용한다.
6. 부정·무차이·안전성 결과도 삭제하지 않는다.
7. 효능명은 성분 우선 검색어에 넣지 않는다.

## 3. 식별자와 판정 단위

| 식별자 | 정의 |
| --- | --- |
| `ingredient_id` | 승인된 canonical 성분 ID |
| `report_id` | PMID 우선, 없으면 정규화 DOI, 둘 다 없으면 정규화 제목 기반 출판물 ID |
| `study_id` | 같은 시험·모집단을 묶는 ID. 확인 전에는 `not_clustered` |
| `comparison_id` | 시험군·대조군·분석 contrast 조합 ID |
| `outcome_result_id` | `ingredient_id + study_id/report_id + comparison_id + raw outcome + timepoint`의 안정적 해시 ID |

출판물(`report`)과 실제 시험(`study`)은 같은 개념이 아니다. 하나의 시험이 여러 출판물로
보고될 수 있으며, 점수 계산 시 같은 연구·같은 결과는 한 번만 계산한다.

초록 자동 선별에서 비교·원시 지표·시점이 아직 추출되지 않은 행은
`outcome_id_status=provisional_abstract`로 표시한다. 이 단계의 ID는
`ingredient_id, report_id, not_clustered, not_extracted comparison, evidence_span,
outcome_rank`를 ASCII unit separator로 연결한 UTF-8 바이트의 SHA-256 앞 24자리이며
`outcome:` 접두사를 붙인다. 전문 정규화 후 최종 ID로 교체할 때 이전 ID와의 매핑을
보존한다.

## C01. 대상 성분

대상은 승인된 manifest에 포함된 `ingredient_id` 단위로 한정한다. 현재 manifest는 기존
v1 성분 원장의 정확한 466개 `ingredient_id`를 동결해 승계한다. 원래 상위 500개 입력과
런타임 34개 중 실제 중복은 28개이므로 비런타임 후보는 472개이며, v1 용량 기준 밖의
후순위 6개는 이 manifest에 포함되지 않는다. 따라서 `500-34=466`으로 해석하지 않는다.
검색 결과가 0건이어도 성분 요약 행과 소스별 검색 실행 행을 생성한다.

염, 에스터, 수화물, 추출물, 하위 활성성분은 승인된 성분 사전이 동일 개체라고 명시한
경우에만 같은 성분으로 취급한다.

### Manifest 계약

- `manifest_version`: `mwbl-ingredient-evidence-targets-466-v1.1`
- cohort source: `ingredient_evidence_adjudication_466.csv`의 순서 있는 466개 ID
- 행 정렬: `ingredient_rank` 정수 오름차순
- canonical 열 순서: `ingredient_rank,ingredient_id,name_en,product_count`
- 직렬화: 위 열 이름의 헤더 1행을 먼저 쓰고, RFC 4180 호환 CSV quoting을 적용한
  UTF-8·쉼표 구분·LF 줄바꿈·마지막 LF 포함 형식
- `manifest_sha256`: 헤더 1행과 canonical 466행을 합친 직렬화 바이트의 SHA-256

필수 필드:

- `manifest_version`
- `manifest_sha256`
- `ingredient_rank`
- `ingredient_id`
- `canonical_name`
- `ingredient_entity_type`

## C02. 논문 검색

각 성분의 공식명과 승인 동의어별로 `성분명 AND 피부·국소 도포 문맥어`를 검색한다.
기존·신규 효능명은 검색어에 넣지 않는다. 실제 측정 결과는 검색 이후 추출한다.

대상 소스:

- PubMed
- Europe PMC
- Crossref
- OpenAlex
- KCI
- RISS

소스별 실제 질의문, 검색명, 실행일, 필터, 원시 건수, 수집 건수, pagination 완료 여부와
실패 사유를 기록한다. 소스를 실행하지 못한 사실도 결과다.

모든 v1.1 검색은 frozen 466 manifest와 실행 시점의 승인 이름 사전으로 새로 수행한다.
`input_provenance`에는 source collector 버전을, `query_contract_status`에는
`approved_terms_only`를 기록한다. 기존 검색 산출물을 비교용으로 읽더라도 새 검색 결과와
섞지 않는다. 승인어 전용 여부를 입증하지 못했거나 선언된 검색 프로토콜 자체가
부분·실패·미실행이면 `rerun_required=Y`이다. 공식 API 자격·robots 정책처럼 현재 실행자가
해결할 수 없는 구조적 접근 제한은 `access_unavailable`과 근거 URL·사유를 남기고
`rerun_required=N`으로 닫을 수 있으며, 접근 조건이 바뀌면 새 실행으로 갱신한다.

각 source collector는 실행 전에 relevance 정렬과 성분당 retrieval cap을 고정할 수 있다.
원시 hit 수가 cap을 넘으면 `pagination_complete=false`를 그대로 보존하되, 선언한 cap까지
오류 없이 수집한 실행은 `success_protocol_capped`로 구분한다. 이 값은 전체 source corpus를
완전 수집했다는 뜻이 아니며, 전문 판정이나 점수 근거의 완전성을 주장할 수 없다.

### `search_status`

| 값 | 의미 |
| --- | --- |
| `success` | 요청과 필요한 페이지 수집이 성공했고 결과가 1건 이상 |
| `success_protocol_capped` | 사전 고정한 relevance cap까지 성공적으로 수집했으나 source 전체 pagination은 하지 않음 |
| `zero_results` | 요청은 성공했으나 결과 0건 |
| `partial` | 일부 성분·페이지·기간만 수집됨 |
| `technical_failure` | 요청했으나 네트워크·응답·파싱 오류로 실패 |
| `access_unavailable` | API key, 기관 권한, 이용 한도 등 접근 조건이 없음 |
| `not_attempted` | 실행하지 않았으며 사유를 기록함 |

소스 역할은 `bibliographic_primary`, `metadata_discovery`,
`regional_bibliographic` 중 하나로 기록한다. Crossref와 OpenAlex 메타데이터는 연구설계나
결과의 전문 확인을 대신하지 않는다.

중복 제거 우선순위는 정규화 DOI, PMID, 정규화 제목+연도+제1저자 순이다. DOI와 PMID가
모두 연결된 경우 하나의 report로 병합하되 원래 소스 목록을 보존한다.

필수 필드:

- `source`
- `source_role`
- `searched_name`
- `query`
- `searched_at`
- `cutoff_date`
- `search_status`
- `failure_reason`
- `raw_count`
- `retrieved_count`
- `pagination_complete`
- `input_provenance`
- `query_contract_status`
- `rerun_required`

## C03. 성분명 일치

이름 일치와 시험 내 역할을 별도로 판정한다.

통과 가능한 이름:

- 정확한 INCI명
- 승인된 일반명·학명
- 공식 구명칭과 신명칭
- 승인된 철자·하이픈·영국식/미국식 표기 차이

자동 통과할 수 없는 경우:

- 상위 추출물과 하위 활성성분 전용
- 감초추출물과 글라브리딘
- 병풀추출물과 마데카소사이드
- Zinc PCA와 zinc sulfate
- 서로 다른 염·에스터·유도체
- 성분이 측정값, 분석물, 용매, 운반체, 양 군 공통 성분으로만 등장

목표 성분은 승인 사전상 같은 개체이고, 시험군과 대조군 사이에서 실제로 달라지는 개입
성분이어야 효능 근거로 진행할 수 있다. canonical ID를 공백으로 바꾼 문자열은 승인된
동의어로 간주하지 않는다.

필수 필드:

- `raw_ingredient_term`
- `entity_match_type`
- `ingredient_dictionary_sha256`
- `intervention_role`
- `ingredient_match_span`
- `ingredient_reject_reason`

## C04. 허용 연구설계

연구설계는 데이터베이스 publication type만으로 확정하지 않고 실제 METHODS를 기준으로
분류한다.

| 설계 | 점수 사용 조건 |
| --- | --- |
| 체계적 문헌고찰·메타분석 | 적격 인체 피부 도포 원시험과 시험별 결과를 식별 가능. 고찰과 원시험을 중복 점수화하지 않음 |
| 무작위 병행군 RCT | 사람 피부 직접 도포, 적격 대조군, 목표 contrast 존재 |
| 무작위 split-face/body | 같은 사람의 좌우·부위에 시험군과 대조군을 적용하고 paired contrast 사용 |
| Vehicle 대조시험 | 목표 성분 또는 농도 외 제형·처치가 동일 |
| 비무작위 동시대조시험 | 실제 도포, 동시대조, 객관·검증 지표 존재 |
| 단일군 전후시험 | 보조 근거만 가능 |
| 관찰·사용시험 | 객관지표 또는 검증 척도가 있을 때 보조 근거만 가능 |

다음은 효능 점수에서 제외한다.

- 일반 리뷰
- Preprint
- 동물·세포·적출피부·인공피부
- 단순 설문·선호도 조사
- 사례보고의 긍정 효능

사례보고는 적격 안전성 결과가 있으면 `applicability_status=safety_only`로 보존한다.
연구설계 등급과 risk of bias는 별도 값이다.

필수 필드:

- `design`
- `randomized`
- `controlled`
- `within_person`
- `comparator_type`
- `prospective`
- `design_source_span`
- `study_id`
- `risk_of_bias_overall`

## C05. 도포 경로와 대상

목표 성분이 사람의 얼굴, 팔, 다리 또는 몸 피부에 직접 도포되고 해당 피부 결과가 분리
보고된 경우만 통과한다.

| 적용범위 | 처리 |
| --- | --- |
| 건강한 일반 피부 | `general_skin` |
| 피부질환·상처·병변 환자 | `medical_context_limited` |
| 건강인 UV·자극·테이프 스트리핑 유발 모델 | `experimental_challenge_limited` |
| 사례·이상반응 전용 | `safety_only` |

질환·유발 모델의 결과를 정상 피부에 자동 일반화하지 않는다. 두피·모발·손발톱·점막과
피부를 함께 연구한 경우 피부 결과가 분리될 때만 해당 결과를 포함한다.

탈락 범위:

- 경구·주사
- 눈·안구·각막·결막
- 구강·비강·질·기타 점막
- 모발·두피·손발톱만 연구
- 피부에 바르지 않은 혈액·대사 연구

필수 필드:

- `route`
- `body_site`
- `skin_condition`
- `population_type`
- `challenge_model`
- `application_regimen`
- `applicability_status`

## C06. 단일성분 분리

목표 성분의 효과는 비교군 간 목표 성분 또는 그 농도만 다르고, 나머지 활성성분,
vehicle, 도포량, 빈도, 기간이 동일할 때 분리 가능으로 판정한다.

통과 가능한 설계:

- 단일성분 대 vehicle
- 단일성분 대 대조성분
- 동일 복합제에서 목표 성분만 추가·제거한 add-on 설계
- 목표 성분 농도만 다른 동일 제형
- 목표 성분의 사전 정의된 주효과 또는 상호작용 효과를 직접 추정하는 factorial 설계

성분표가 비공개이거나 다른 활성성분·vehicle·처치도 함께 달라지면
`eligibility_status=formulation_not_isolated`이다. 활성 대조군 연구는 비교우위만 주장할
수 있고 vehicle 대비 절대 효과로 해석하지 않는다.

필수 필드:

- `test_arm_components`
- `control_arm_components`
- `target_concentration_by_arm`
- `cointerventions_equal`
- `comparator_type`
- `isolation_status`
- `isolation_evidence_span`

## C07. 결과 문장과 판정 단위

방향과 통계는 RESULTS의 문장, 표, 그림 또는 보충자료에서 추출한다. METHODS는 군,
지표, 시점 정의에 사용할 수 있지만 효능 결과로 사용하지 않는다. CONCLUSION만 있고 이를
뒷받침하는 적격 비교 결과가 없으면 positive로 판정하지 않는다.

시험군, 대조군, 지표, 시점, 효과추정치와 통계는 같은 `outcome_result_id`에 연결되어야
한다. 초록 전체에서 성분×효능×p값을 임의 조합하지 않는다.

필수 필드:

- `outcome_result_id`
- `section`
- `page_table_figure`
- `evidence_span`
- `arm_ids`
- `comparison_id`
- `timepoint`

## C08. 기존 6효능 측정지표

기존 효능은 버전 고정된 outcome dictionary의
`effect_id–raw outcome–instrument parameter–unit–favorable direction` 조합으로만 자동
매핑한다. 원문 표현은 반드시 보존하며, 여러 지표는 각각 별도 결과 행으로 만든다.

| 효능 | 인정 지표 예시 | 좋은 방향 |
| --- | --- | --- |
| 미백 | melanin index, L*, ITA°, MASI | melanin·MASI 감소, L*·ITA° 증가 |
| 여드름·피지 | 병변·comedone 수, IGA, sebum output | 감소 |
| 주름 | 주름 깊이·면적·개수, 탄력, firmness | 주름 감소, 탄력·firmness 증가 |
| 보습·장벽 | TEWL, 수분량, capacitance, conductance | TEWL 감소, 수분값 증가 |
| 진정 | erythema index, 검증된 가려움·따가움·화끈거림 척도 | 감소 |
| 각질 | scaling, roughness, desquamation, corneocyte cohesion | 승인된 파라미터별 방향 |

피지와 여드름 병변, TEWL과 수분량은 서로 다른 하위결과로 보존한다. MASI 등 질환 척도는
`medical_context_limited`이다. 각질 지표는 사전의 파라미터 방향이 승인되지 않으면
`outcome_direction=unclear`이다.

필수 필드:

- `effect_id`
- `raw_outcome_name`
- `outcome_concept_id`
- `positive_direction`
- `outcome_dictionary_sha256`

## C09. 기기명 처리

기기명만으로 효능을 매핑하지 않는다. 기기, 채널·파라미터, 단위, 값의 변화와 적격
비교가 함께 확인되어야 한다.

- Corneometer만 등장: 매핑하지 않음
- Corneometer 수분값 증가: 보습 후보
- Tewameter만 등장: 매핑하지 않음
- TEWL 감소: 장벽 후보
- Mexameter: melanin과 erythema 채널 분리
- Cutometer: R0~R9 등 승인된 파라미터별 방향 사용
- Silicone replica: 측정재료이며 dimethicone이 아님
- stratum corneum: 해부학 표현이며 각질 효능이 아님

필수 필드:

- `instrument`
- `model`
- `channel`
- `parameter`
- `unit`
- `raw_outcome_name`

## C10. 동의어와 사전

`ingredient synonym dictionary`와 `outcome mapping dictionary`를 분리한다. 승인된
동의어만 자동 매핑한다. AI는 후보를 제안할 수 있지만 자동 승인할 수 없다.

Codex와 Claude의 독립 검수는 검토 입력이며, 두 AI의 합의도 최종 과학 승인이 아니다.
불일치와 근거를 기록한 뒤 지정된 사람이 최종 adjudication 해야 사전에 추가할 수 있다.
사전 변경 시 영향받는 모든 후보를 재판정한다.

### SHA 계약

- `ingredient_dictionary_sha256`: 정해진 파일 순서
  `data/ingredients.csv`, `data/ingredient_aliases.csv`의 바이트 SHA를 결합한 bundle SHA
- `outcome_dictionary_sha256`: `data/effect_outcome_dictionary.csv` 바이트 SHA
- `direction_dictionary_sha256`: `data/effect_direction_dictionary.csv` 바이트 SHA
- summary는 bundle 파일 순서와 각 파일 SHA를 함께 기록한다.

필수 검수 필드:

- `dictionary_type`
- `raw_term`
- `canonical_id`
- `proposal_source`
- `reviewer1_decision`
- `reviewer2_decision`
- `adjudicator`
- `rationale`
- `dictionary_version_sha`

새 결과 표현은 승인 전 `effect_mapping_status=unmapped_outcome`으로 보존한다.

## C11. 결과 방향

방향은 결과별 적격 비교효과를 승인된 좋은 방향과 대조해 판정한다.

| 값 | 의미 |
| --- | --- |
| `positive` | 개선 방향의 적격 비교효과가 C12를 만족 |
| `negative` | 악화 방향의 적격 비교효과가 통계적으로 지지됨 |
| `no_detectable_difference` | 적격 비교에서 차이를 검출하지 못함 |
| `unclear` | 방향, 비교 또는 통계가 불충분 |
| `not_applicable` | 효능 방향 판정 대상이 아님 |

`no_detectable_difference`는 동등성의 증명이 아니다. 동등성·비열등성은 별도 필드로
기록한다. 이상반응은 `safety_signal`로 분리하고 효능 negative와 합치지 않는다.

필수 필드:

- `estimate_direction`
- `outcome_direction`
- `statistical_conclusion`
- `equivalence_supported`
- `safety_signal`

## C12. 통계 기준

대조시험은 목표 성분 효과에 대응하는 군간 차이, 변화량 차이,
`treatment × time` interaction 또는 split-body paired contrast가 있어야 한다. 해당
contrast의 효과 방향과 CI 또는 p값을 같은 결과 행에서 확인한다.

- 논문이 정한 alpha가 없으면 p<0.05 또는 CI가 귀무값을 배제할 때 통계 지지로 본다.
- p값은 비교연산자와 수치를 분리 보존한다. `p_value_operator`는
  `lt|le|eq|gt|ge|not_extracted`를 사용한다. 개선·악화는 유의수준 미만 p값, 무차이는
  유의수준 이상 p값을 해당 결과 문맥에서 확인해야 한다.
- 숫자 하한·상한과 귀무값을 추출하지 못한 CI 표기만으로 통계 게이트를 통과시키지 않는다.
- 효과크기만으로 positive를 판정하지 않는다.
- 시험군만의 전후 개선은 대조시험 positive 근거가 아니다.
- 단일군 전후시험은 객관지표·검증 척도 변화가 있어도 supporting만 가능하다.
- 결과 문장 밖 다른 지표의 p값을 가져오지 않는다.

필수 필드:

- `contrast_type`
- `estimate`
- `estimate_unit`
- `ci_low`
- `ci_high`
- `p_value`
- `p_value_operator`
- `alpha`
- `n_analyzed_by_arm`
- `paired_analysis`
- `multiplicity_adjusted`
- `analysis_population`
- `statistical_support`

## C13. 불확실 표현

다음 표현은 자동 탈락 키워드가 아니라 `hedge_flag`이다.

- may
- might
- potential
- trend
- suggest
- inconclusive
- further research needed

같은 결과에 적격 비교와 C12 통계가 있으면 결론의 hedge 표현만으로 positive를 금지하지
않는다. 반대로 hedge만 있고 적격 수치·통계가 없으면 positive가 될 수 없으며
`unclear` 또는 `abstract_only`로 남긴다.

필수 필드:

- `hedge_flag`
- `hedge_span`
- `explicit_result_available`

## C14. 논문 유효성

- 철회 논문은 `eligibility_status=retracted`로 격리하고 점수화하지 않는다.
- Expression of Concern은 `verification_status=validity_hold`로 보류한다.
- 정정은 원문과 연결하고 `bibliographic_only`, `methods`, `results`, `conclusion` 영향으로 분류한다.
- 동일 시험·모집단 출판물은 하나의 `study_id`로 묶되 모든 report를 보존한다.
- 제조사 지원과 저자 이해관계는 기록하지만 자동 탈락 사유로 사용하지 않는다.
- 긍정 점수 후보는 전문·보충자료에서 성분, 군, 경로, 설계, 결과, 통계를 모두 확인해야 한다.
- 핵심 내용을 전문에서 확인하지 못하면 `verification_status=abstract_only` 또는
  `full_text_unavailable`, `score_status=not_scoreable`이다.

필수 필드:

- `retraction_status`
- `validity_checked_at`
- `validity_source`
- `correction_id`
- `correction_impact`
- `study_id`
- `report_id`
- `duplicate_trial_status`
- `funding`
- `conflict_of_interest`
- `full_text_status`

## C15. 새 효능

기존 6효능 밖의 실제 측정 결과는 raw outcome, 방향, 통계, 적용 맥락과 함께
`effect_mapping_status=new_effect_candidate`로 보존한다. C03~C07을 통과하지 못한 단순
언급, 잘못된 경로·성분 또는 분리 불가능 복합제 결과는 새 효능 후보로 승격하지 않는다.

새 효능축 승인 전 현재 점수에는 반영하지 않는다. 안전성 결과와 질환 한정 결과는 각각
`safety_only`, `medical_context_limited`로 분리한다.

## C16. 다차원 최종 상태

### `eligibility_status`

- `eligible`
- `wrong_ingredient`
- `wrong_route_or_site`
- `ineligible_design`
- `formulation_not_isolated`
- `retracted`
- `not_assessable`

### `verification_status`

- `full_text_verified`
- `abstract_only`
- `full_text_unavailable`
- `correction_pending`
- `validity_hold`

### `applicability_status`

- `general_skin`
- `medical_context_limited`
- `experimental_challenge_limited`
- `safety_only`
- `not_applicable`

### `effect_mapping_status`

- `mapped_existing`
- `new_effect_candidate`
- `unmapped_outcome`
- `not_mapped`

### `outcome_direction`

- `positive`
- `negative`
- `no_detectable_difference`
- `unclear`
- `not_applicable`

### `score_status`

- `score_candidate_positive`
- `score_candidate_supporting`
- `not_scoreable`

### `review_status`

- `candidate_unverified`
- `reviewer1_complete`
- `reviewer2_complete`
- `adjudicated`

### `runtime_score_change`

- v1.1 자동 산출물에서는 `none`만 허용한다.

### 점수 후보 최소 조건

`score_candidate_positive`는 다음을 모두 만족해야 한다.

1. `eligibility_status=eligible`
2. `verification_status=full_text_verified`
3. 기존 승인 효능에 매핑됨
4. `outcome_direction=positive`
5. 단일성분 분리 확인
6. 무작위·적격 대조 또는 동등한 직접 비교
7. 적격 contrast의 통계 지지
8. 중복 연구 확인 완료

`score_candidate_supporting`은 적격 비무작위 동시대조 또는 단일군 전후·관찰·사용시험의
객관·검증 지표가 전문에서 확인된 경우만 가능하다.

### `primary_status` 호환 파생 우선순위

`primary_status`는 이전 도구를 위한 표시값이며 scoring에 사용할 수 없다.

아래 reject-first 우선순위는 개별 report 표시값에 적용한다. 성분 요약은 적격 report가
하나라도 있으면 그 best usable path를 우선하며, 탈락 report는 `all_statuses`와 report
원장에서 별도로 보존한다. 대표 report 선택도 적격 경로를 먼저 1편 확보한 뒤 신호 다양성과
근거등급을 고려한다.

1. 철회·잘못된 성분·경로·설계: `reject_wrong_scope`
2. 성분 독립효과 미분리: `formulation_only`
3. 전문 미확인·정정/유효성 보류: `abstract_insufficient`
4. 새 효능 결과: `new_effect_candidate`
5. negative 또는 no detectable difference: `negative_or_null`
6. 점수 보조 후보: `score_candidate_supporting`
7. 점수 긍정 후보: `score_candidate_positive`
8. 그 외: `abstract_insufficient`

`no_evidence_found`는 `primary_status`가 아니다. 소스별 `search_status=zero_results`와 성분별
`search_result_status=zero_results_all_sources`로 기록한다.

## 4. v1.1 산출물

| 파일 | 판정 단위 | 용도 |
| --- | --- | --- |
| `ingredient_evidence_adjudication_466_v1_1.csv` | 성분 | 검색·대표논문·상태축 요약 |
| `ingredient_evidence_representatives_466_v1_1.csv` | 성분×report | 서지정보와 논문 단위 제한·검증 상태 |
| `ingredient_evidence_outcome_results_466_v1_1.csv` | 성분×study/report×비교×결과×시점 | 효능·방향·통계 정본 |
| `ingredient_evidence_search_runs_466_v1_1.csv` | 성분×소스 | 검색식·성공·부분·실패 감사 원장 |
| `ingredient_evidence_adjudication_466_v1_1_summary.json` | 실행 | 정책·manifest·사전 SHA와 집계 |

표의 경로는 artifact 내부 논리 경로다. 대용량 CSV·원시 검색 파일은 Git 런타임 경로에
직접 커밋하지 않고 GitHub Release
`ingredient-evidence-v1.1-bdata-20260713`의 SHA 고정 archive에 보존한다. 저장소의
`data/reconciliation/ingredient_evidence_v1_1_artifact.json`이 release URL, archive SHA,
파일 수와 검증 상태를 가리킨다. artifact의 `candidate_unverified` 상태와 83/83 무결성
검사 통과는 사람의 전문 판정이나 임상 효능 승인을 뜻하지 않는다.

장기적으로 `study`, `ingredient_intervention`, `review_decision`을 별도 테이블로 분리할 수
있다. v1.1 CSV에 값이 없으면 확인되지 않은 사실을 자동 생성하지 않는다.

현재 자동 생성기는 frozen 466개 성분을 여섯 소스에서 새로 검색하고 후보를 초록 수준으로
선별한다. 전문 확인을 가장해 `full_text_verified`나 점수 후보를 자동 생성하지 않으며,
전문·중복·제형 분리의 수동 adjudication이 끝날 때까지 모든 행은
`candidate_unverified`와 `not_scoreable`을 유지한다. `rerun_required=Y`인 검색 실행은 C02
완료로 간주하지 않는다. `success_protocol_capped`는 선언한 retrieval 프로토콜의 완료이지
source 전체 문헌의 exhaustive retrieval을 뜻하지 않는다.

## 5. 판정 우선순위

다음 순서로 판정한다.

1. 철회·유효성 보류
2. 성분 entity 일치
3. 경로·부위·사람 피부 범위
4. 허용 연구설계
5. 단일성분 분리
6. 결과 문장과 판정 단위 연결
7. 기존·신규 효능 매핑
8. 결과 방향
9. 적격 contrast 통계
10. 전문 확인과 중복 연구 확인
11. score status 산출

앞 단계가 실패해도 report와 안전성·부정·무차이 결과는 삭제하지 않고 해당 상태로
보존한다.

## 6. v1에서 v1.1로의 마이그레이션

- 기존 무접미사 v1 CSV·JSON은 보존한다.
- v1의 `score_candidate_*`는 `machine_signal_status`로 옮긴다.
- 전문 미확인 v1 score candidate는 v1.1에서 `score_status=not_scoreable`,
  `primary_status=abstract_insufficient`이다.
- v1의 `negative_or_null`은 결과 단위에서 `negative`와
  `no_detectable_difference`로 분리한다. 분리할 수 없으면 `unclear`이다.
- v1의 `no_evidence_found`는 소스별 `search_status`로 이동한다.
- v1의 `sources_not_searched` 문자열은 소스별 검색 실행 행으로 분리한다.
- v1의 `mapped_effect_ids`, `directions`, `statistical_support`, `evidence_spans`는
  `outcome_result_id`별 행으로 정규화한다.
- v1.1 재생성만으로 `ingredient_effect.csv`, `ingredient_evidence.csv`, DB 또는 추천 점수를
  변경하지 않는다.

## 7. 방법론 참고 기준

- CONSORT: 무작위시험 결과는 군별 결과와 군간 효과추정치·불확실성을 연결해 보고한다.
  <https://www.bmj.com/content/389/bmj-2024-081124>
- PRISMA: 체계적 문헌고찰은 포함 연구와 개별 연구 결과를 추적 가능하게 보고한다.
  <https://www.prisma-statement.org/>
- NLM: PubMed의 정정·철회 연결 관계를 사용해 원문과 notice를 함께 확인한다.
  <https://www.nlm.nih.gov/bsd/policy/errata.html>
