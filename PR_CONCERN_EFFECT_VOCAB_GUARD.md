# fix: concern→effect 매핑 짝맞춤 로드 + 어휘 검증

**브랜치:** `fix/concern-effect-vocab-guard` (origin/dev 2660d04 기반) · push는 팀 결정

## 무엇이 문제였나

`get_default_concern_repository()`(app/services/concern_repository.py)가 두 데이터 파일을
**서로 다른 디렉터리에서 갈라 로드**할 수 있었다:

```python
tag_dir    = data_dir if (data_dir/"tags.json").exists() else examples_dir
effect_dir = tag_dir  if (tag_dir/"concern_to_effect.json").exists() else examples_dir  # ← 따로 폴백
```

`data_dir`에 `tags.json`은 있는데 `concern_to_effect.json`이 없으면 → tags는 진짜,
effects는 `examples/`의 **옛 어휘**로 갈린다. 그 옛 어휘(`effect_sebum_control`,
`effect_texture`, `effect_barrier`, `effect_moisturizing`)는 채점 효과 택소노미
6종(`effect_acne_sebum`·`effect_brightening`·`effect_calming`·`effect_exfoliation`·
`effect_moisture_barrier`·`effect_wrinkle`)에 **없다**.

결과: `scoring._build_desired_effects`가 만든 효과코드가
`_load_product_effect_recommendation_features`의 `Effect.effect_code.in_(...)` 조회에서
**0건 매칭** → **효능·근거·함량 3개 점수축이 조용히 기본값(0.5/0)으로 죽는다.**

LLM 파서가 켜지면 올바른 택소노미 코드를 산출해 이 경로를 우회하지만, 키워드 파서만
쓰는 경로(LLM 비활성/실패/needs_llm=False)는 죽은 축으로 추천이 나간다.

## 근거 (로컬 격리 측정, dev83)

`concern_to_effect.json` **한 파일만** 다른 두 데이터 디렉터리로 A/B (동일 DB·코드·캐시):

| 심판 | STALE (효과축 죽음) | FIXED (효과축 살아남) |
|---|---|---|
| 실버 Hit@10 / @50 | 24 / 50 | 21 / 38 |
| v3(리뷰) Hit@10 / @50 | .494 / .988 | .229 / .627 |
| v4(합의) Hit@10 | .771 | .518 |

79/83 질문 순위 이동. (리뷰파생 심판은 효과축을 **벌주므로** FIXED가 낮게 나오는 건
심판 성격 탓 — 별도 평가 필요. 이 PR의 목적은 점수 향상이 아니라 **조용한 축 사망 차단**.)

## 이 PR이 하는 일

1. `tags.json`과 `concern_to_effect.json`을 **한 쌍**으로 같은 `tag_dir`에서 로드.
2. `concern_to_effect.json`이 `tag_dir`에 없으면 `FileNotFoundError`로 **즉시 실패**
   (조용한 examples 폴백 제거).
3. 로드된 효과 어휘가 같은 디렉터리 `ingredient_effect.csv`(effect_id) 택소노미의
   부분집합인지 검증, 아니면 `ValueError`. 택소노미 소스가 없으면 경고 후 건너뜀.
4. 회귀 테스트 4종 (`tests/test_concern_repository.py`).

## 영향 / 안전성

- **프로덕션 동작 불변**: 배포 data는 양쪽 파일이 정상 존재(정품 어휘 6종) → 종전과 동일.
- **드러내는 것**: 배포/측정 환경 데이터가 반쪽이거나 옛 어휘가 새어들면, 종전엔
  조용히 축이 죽었지만 이제 시작 시점에 예외로 즉시 드러난다.
- 기존 `tests/test_parser.py` 13종 무회귀 확인.

## 팀 확인 요청

1. **배포 DATA_DIR 점검**: 실제 배포 환경의 `DATA_DIR`에 `concern_to_effect.json`이
   `tags.json`과 같은 디렉터리에 있는지 (examples 폴백이 아닌지) 확인. 있으면 프로덕션 안전.
2. **eval 하네스 마운트 수정**: 로컬/측정이 물리던 `junlge_namanmoo-dev/data`엔 이 파일이
   빠져 있었다 — 앞으로 측정은 정품 data(`junlge_namanmoo/data`)를 마운트해야 효과축이
   살아있는(=프로덕션과 같은) 시스템을 잰다.

전 과정 근거: `eval_harness_v1/.../experiment_log.jsonl` RESULT_vocab_isolation_20260719.
