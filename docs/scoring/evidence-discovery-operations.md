# 신규 논문 자동 수집 운영

> 상태: 후보 수집 자동화. 논문 승인과 추천 점수 반영은 자동화하지 않는다.

## 목적

현재 `data/ingredient_effect.csv`의 72개 성분×효능쌍을 기준으로 최근 PubMed 등록 논문을 매주 찾는다.

이 작업의 끝은 다음과 같다.

1. 매주 새 논문 후보를 자동 검색한다.
2. 같은 성분×효능에 이미 등록된 PMID·DOI는 제외한다.
3. 새 결과를 `candidate_unverified` CSV와 Actions 요약으로 남긴다.
4. 사람이 원문을 검수해 별도 변경으로 승인하기 전에는 점수에 넣지 않는다.

기존 논문 전체를 다시 수집하거나 4~18위 논문을 일괄 보강하는 작업이 아니다. 자동 수집을 시작한 이후 새로 등록된 논문을 놓치지 않는 것이 목적이다.

## 입력과 출력

입력 정본:

- `data/ingredient_effect.csv`: 검색할 성분×효능 72쌍
- `data/ingredients.csv`: canonical 영문 성분명
- `data/ingredient_aliases.csv`: 신뢰도 `high`인 영문 INCI·동의어
- `data/ingredient_evidence.csv`: 동일 pair의 기존 PMID·DOI 중복 기준

실행 결과 artifact:

- `new_evidence_candidates.csv`: 논문×성분×효능 검수 후보
- `summary.md`: Actions 화면에서 바로 읽는 요약
- `run_manifest.json`: 입력 파일·수집기·출력 해시와 실제 검색식

후보 CSV는 항상 아래 값을 가진다.

```text
review_status = candidate_unverified
score_eligible = false
```

수집기는 `ingredient_evidence.csv`, DB, 대표 논문, 추천 점수를 수정하지 않는다.

## 자동 실행

`.github/workflows/evidence-discovery.yml`이 매주 월요일 09:17 KST에 최신 `dev` 데이터를 읽어 실행된다.

- #434가 `dev`에 merge되면 `push(dev)`로 첫 수집을 즉시 실행한다.
- 이 저장소의 기본 브랜치는 `main`이므로 주간 예약은 workflow가 정상적인 `dev`→`main` 배포 흐름으로 `main`에 도달한 뒤 시작된다.
- 주간 예약을 켜기 위한 별도 기능 PR은 만들지 않는다.

Actions의 `weekly evidence discovery`에서 수동 실행도 가능하다. 결과는 실행 요약과 `evidence-candidates-<run_id>` artifact에 90일간 보관한다.

저장소 변수 `NCBI_EMAIL`을 설정하면 NCBI 요청에 프로젝트 연락처를 함께 보낸다. `NCBI_API_KEY`는 선택 사항이며, 기본 수집기는 키 없이도 NCBI 공개 한도보다 낮은 초당 2회 이하로 요청한다. 유료 AI API는 사용하지 않는다.

## 로컬 실행

전체 72쌍을 최근 8일 기준으로 실행한다.

```bash
python data/scripts/discover_new_evidence.py \
  --days 8 \
  --output-dir artifacts/evidence-discovery
```

한 쌍만 연결 시험할 수 있다.

```bash
python data/scripts/discover_new_evidence.py \
  --ingredient-id niacinamide \
  --effect-id effect_brightening \
  --days 30 \
  --output-dir artifacts/evidence-discovery
```

단위 테스트:

```bash
python -m unittest discover -s data/scripts/tests -p "test_*.py" -v
```

## 검수 흐름

1. Actions 요약에서 새 후보 수와 효능축을 확인한다.
2. CSV의 PubMed 링크로 성분 형태·효능 측정·단일성분 분리 여부를 검수한다.
3. 채택할 논문만 기존 3중 검수 절차를 거쳐 `ingredient_evidence.csv`에 반영한다.
4. 기각·무효·상충 논문도 정책에 따라 판정 이력을 보존한다.

한 논문이 다른 효능쌍에 이미 있어도 새로운 pair 근거 후보라면 다시 출력한다. 반대로 동일 성분×효능에 같은 PMID 또는 DOI가 있으면 제외한다.

검색 기간은 누락 방지를 위해 8일로 두어 주간 실행 사이 하루가 겹친다. 아직 정본 CSV에 반영되지 않은 후보가 인접한 두 보고서에 다시 나타날 수 있는데, 후보를 조용히 잃는 것보다 재노출하는 쪽을 택한 의도된 동작이다.

## 외부 서비스 기준

- [NCBI E-utilities 소개와 사용 정책](https://www.ncbi.nlm.nih.gov/books/NBK25497/)
- [NCBI E-utilities API Reference](https://www.ncbi.nlm.nih.gov/books/NBK25499/)
- [GitHub Actions 예약 실행](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub Actions artifact 보관](https://docs.github.com/en/actions/tutorials/store-and-share-data)
