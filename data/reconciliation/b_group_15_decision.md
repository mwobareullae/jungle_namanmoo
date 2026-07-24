# B군 15 후보군 결정안

이 문서는 A군 canonical/alias 연결 이후 남은 `ing_pending_*` 빈도와 `needs_review` 위험 항목을 교차해 만든 B군 1차 후보군 결정안입니다.
아직 DB seed나 효능 점수 반영 대상이 아니며, 점수화 전에 위험 family는 세부 canonical로 쪼갭니다.

## 확정 후보군 15

| 우선 | 후보군 | 근거 | 결정 |
| ---: | --- | --- | --- |
| 1 | 토코페롤/비타민E | 추정 product 589, row 596 | B군 후보 |
| 2 | 센텔라 활성 3종 | 추정 product 405, row 408 | B군 후보. asiaticoside / asiatic acid / madecassic acid 분리 점수화 |
| 3 | 콜라겐 계열 | 추정 product 221, row 225 | B군 후보. 보습/피부컨디셔닝 중심으로 보수 점수 |
| 4 | 베타-글루칸 | 추정 product 215, row 219 | B군 강력 후보 |
| 5 | 감초 활성염 | 추정 product 184, row 185 | B군 강력 후보. 감초추출물에 자동 병합 금지 |
| 6 | 비타민C 유도체 | 추정 product 179, row 179 | B군 후보. SAP / 3-O-ethyl / ascorbyl glucoside 등 분리 점수화 |
| 7 | 피토스핑고신/스핑고신 | 추정 product 94, row 94 | B군 후보. 세라마이드에 자동 병합 금지 |
| 8 | 글루타티온 | 추정 product 82, row 82 | B군 후보 |
| 9 | 약모밀/어성초 | 추정 product 69, row 69 | B군 후보. 추출물/수/소포 범위 결정 필요 |
| 10 | BHA 유도체 | 추정 product 63, row 64 | B군 후보. LHA / betaine salicylate를 salicylic acid에 자동 병합 금지 |
| 11 | 소듐PCA/NMF | 추정 product 57, row 57 | B군 후보. Zinc PCA에 병합 금지 |
| 12 | 카페인 | 추정 product 55, row 55 | B군 후보 |
| 13 | 다이메티콘올 | 추정 product 47, row 47 | B군 후보. Dimethicone과 별도 INCI |
| 14 | 레티노이드 유도체 | 추정 product 26, row 26 | B군 후보. retinyl palmitate / HPR 등 분리 점수화 |
| 15 | 알파-알부틴 | 추정 product 19, row 19 | B군 후보. arbutin에 자동 병합 금지 |

## 점수화 전 분리 필요

- 센텔라 활성 3종: `asiaticoside`, `asiatic_acid`, `madecassic_acid`
- 비타민C 유도체: 최소 `sodium_ascorbyl_phosphate`, `ethyl_ascorbic_acid`, `ascorbyl_glucoside` 우선
- BHA 유도체: 최소 `capryloyl_salicylic_acid`, `betaine_salicylate` 분리
- 레티노이드 유도체: 최소 `retinyl_palmitate`, `hydroxypinacolone_retinoate` 분리
- 토코페롤/비타민E: `tocopherol`과 `tocopheryl_acetate`를 family로 묶을지 분리할지 점수화 전에 결정

## 보류

- 시트릭애씨드: 빈도는 높지만 pH 조절제 false positive 위험으로 B군 제외
- 세부 펩타이드: 빈도는 높지만 A군 peptide family 범위 정책이 먼저 필요
- 실리콘 crosspolymer: dimethicone 이름이 있어도 구조/기능감이 달라 자동 병합 금지
- 정제수, 글라이콜, 보존제, 점증제: 빈도와 무관하게 B군 효능 점수 후보에서 제외

## 다음 작업

1. 위 15 후보군을 Claude/오너 검토용으로 확정한다.
2. 분리 필요 항목은 canonical_id 단위로 쪼갠다.
3. B군 효능 6축 점수 매트릭스를 만든다.
4. alias/canonical seed는 점수 검토가 끝난 뒤 별도 반영한다.
