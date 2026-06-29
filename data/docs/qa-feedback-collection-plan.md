# QA 피드백 수집 계획 (tags v2 대비)

커뮤니티 공개 후 실사용 데이터가 쌓이면 이 기준으로 `tags.json`/`concern_to_effect.json` v2를 검토한다.

> 일정: 2026-06-30(내일) 커뮤니티 공개 예정, 약 1주일(빠르면 더 일찍) 후 데이터 확인.

## 어디서 모으나

캐싱 테이블(#9, `concern_llm_cache`)에 이미 `concern_text`+`llm_response`가 쌓이므로, 별도 로깅 없이 이 테이블을 그대로 분석 대상으로 쓴다.

- `llm_response.unmatched_terms`: 표준 11개 고민 중 어디에도 안 걸린 표현
- `llm_response.needs_review = true`: 위험 표현/모순/낮은 confidence로 검토가 필요했던 케이스

## 무엇을 본다

1. **`unmatched_terms` 빈도 집계**: 같은/유사한 표현이 몇 번 반복되는지
2. **`needs_review = true` 케이스 전체 검토**: 위험 표현 오탐, 모순 처리 오류 등

## tags v2로 올리는 기준 (기존 `concern-categories.md` 정책 재사용)

- 같은 표현이 **3회 이상 반복**되면: 기존 태그의 `synonyms`에 추가할지 검토
- 기존 11개 태그 중 의미가 겹치는 게 없으면: 신규 태그 후보로 검토
- 1~2회뿐이고 추천 품질에 큰 영향 없으면: 보류

## 처리 절차

1. 주기적으로(예: 2주 단위) 캐시 테이블에서 `unmatched_terms`/`needs_review` 데이터 추출
2. 위 기준으로 후보 표현 선별
3. `tags.json`/`concern_to_effect.json` 수정 → #14(프롬프트 v2)와 함께 반영
4. 변경 이력은 `concern-categories.md`에 기록

## TODO

- 캐시 테이블에서 위 통계를 뽑는 스크립트는 데이터가 실제로 쌓인 뒤 작성 (지금은 데이터 없음)
