# B군 1차 후속 검증 메모

베타글루칸과 다이포타슘글리시리제이트는 1차 Claude 검증에서 `strong_candidate`에서 `draft`로 강등했으나, 후속 1차 자료 확인 결과 일부 항목을 다시 strong 후보로 올릴 수 있다고 판단했습니다.

## 베타글루칸

### 보습·장벽

- 근거: Cao et al., 2021, `PMID33128496`
- 연구 형태: split-face, double-blinded, vehicle-controlled study
- 요지: fractional laser 이후 β-glucan 포함 skincare regimen 사용군에서 hydration index, TEWL, hemoglobin index 회복이 vehicle 대비 유의하게 개선되었습니다.
- 판단: 단일 성분 단독 도포가 아니라 regimen 근거라는 한계는 있으나, 장벽 손상 모델에서 hydration/TEWL 개선이 확인되어 `strong_candidate`로 재상향했습니다.

### 진정

- 근거: Jesenak et al., 2015/2016, `PMID26654776`
- 연구 형태: multicentre open split-body study
- 요지: β-glucan-based cream이 mild-to-moderate atopic dermatitis에서 pruritus, flare intensity, EASI score 개선을 보였습니다.
- 판단: open-label cream 근거라 점수는 낮은 보조로 유지하되, 민감/AD 맥락의 진정 후보로는 `strong_candidate` 처리 가능합니다.

## 다이포타슘글리시리제이트

### 진정

- 근거: Xia et al., 2025, `PMID40735556`
- 연구 형태: randomized parallel-controlled clinical study
- 요지: dipotassium glycyrrhizin-containing emollients가 adult atopic dermatitis에서 itching, SCORAD, flare-up 빈도 개선을 보였습니다.
- 판단: 기존 licorice gel 대용 근거보다 직접성이 높아 `strong_candidate`로 재상향했습니다.
- 남은 확인: 논문 표기는 dipotassium glycyrrhizin이며, seed 전 INCI `Dipotassium Glycyrrhizate`와 동일/대응 가능한 표기인지 최종 확인이 필요합니다.

## seed 전 주의

- 세 항목 모두 실제 seed 전 Claude/오너 재검토가 필요합니다.
- 농도 범위는 아직 확정하지 말고 `unknown`으로 두는 것이 안전합니다.
- 베타글루칸은 `beta_glucan` family canonical로 묶되, `sodium_carboxymethyl_beta_glucan` 등 유도체는 자동 병합하지 않습니다.
