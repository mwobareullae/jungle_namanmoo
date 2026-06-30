# B군 1차 evidence scout 검증 메모

Claude 교차검증 결과를 반영한 후속 메모입니다.

## 반영한 조정

- `glutathione / effect_brightening`
  - topical oxidized glutathione DBPC RCT 근거가 확인되어 `draft`에서 `strong_candidate`로 상향했습니다.
  - 단, 일반 glutathione과 oxidized glutathione(GSSG) form 차이는 최종 seed 전 검토가 필요합니다.
- `beta_glucan / effect_moisture_barrier`, `beta_glucan / effect_calming`
  - 근거가 단일성분 인체 임상보다 복합 regimen·상처치유 기전에 가까워 `strong_candidate`에서 `draft`로 강등했습니다.
- `dipotassium_glycyrrhizate / effect_calming`
  - 인용 근거가 분리염 단독이 아니라 감초 젤 임상 대용 근거라 `strong_candidate`에서 `draft`로 강등했습니다.
- `collagen / effect_wrinkle`
  - 상처치유·콜라겐합성 근거를 화장품 주름개선으로 직접 인정하지 않고 `exclude`로 표시했습니다.
- `asiaticoside / effect_wrinkle`, `asiatic_acid / effect_wrinkle`
  - 상처치유·콜라겐합성 근거를 화장품 주름개선으로 직접 인정하지 않고 `exclude`로 표시했습니다.

## 엔진 정책 필요

센텔라 계열은 이중계상 위험이 있습니다.

- A군: `centella_asiatica`, `madecassoside`
- B군 후보: `asiaticoside`, `asiatic_acid`, `madecassic_acid`

한 제품에 전초 추출물과 분리 활성이 함께 표기되면 같은 효능축 점수가 중복 가산될 수 있습니다.
추천 엔진에서는 `centella_asiatica`와 그 분리 활성 성분을 같은 효능축에서 무제한 합산하지 않는 cap 또는 family dedupe 정책이 필요합니다.
