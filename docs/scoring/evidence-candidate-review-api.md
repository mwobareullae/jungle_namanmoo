# 논문 후보 보관함·검수 API

## 목적

주간 PubMed 수집 결과를 점수 테이블과 분리해 영구 보관하고, 관리자 승인 시에만
`ingredient_evidence`로 승격한다.

## 인증

- 자동 수집 적재: `X-Evidence-Ingest-Token` 헤더
- 관리자 조회·판정: 로그인 세션의 `users.role == ADMIN`

실제 토큰은 저장소에 커밋하지 않는다. 백엔드 환경변수와 GitHub Actions secret의
`EVIDENCE_INGEST_TOKEN`을 같은 값으로 설정한다.

## 엔드포인트

| Method | Path | 설명 |
| --- | --- | --- |
| `POST` | `/api/internal/evidence-candidates/import` | 수집 후보 일괄 upsert |
| `GET` | `/api/admin/evidence-candidates` | 상태·검색어 기반 후보 목록 |
| `GET` | `/api/admin/evidence-candidates/{id}` | 후보 상세와 판정 이력 |
| `POST` | `/api/admin/evidence-candidates/{id}/approve` | 승인 후 런타임 근거 승격 |
| `POST` | `/api/admin/evidence-candidates/{id}/reject` | 기각 및 이력 보존 |

## 승인 요청

```json
{
  "summary": "인체 국소 시험에서 해당 효능 지표가 개선됨",
  "evidence_level": "high",
  "evidence_score": 82,
  "result_direction": "positive",
  "score_use_level": "primary",
  "source_authority_score": 0.9,
  "is_representative": false,
  "representative_rank": null,
  "review_note": "원문과 exact 성분 형태를 확인함"
}
```

승인 성공 시 후보 상태와 생성된 `ingredient_evidence.id`를 함께 반환한다.
이미 판정된 후보의 재승인은 `409`다. 대표 순위가 사용 중이면 `409`다.

현재 음성·무효·불명확 결과는 점수 감점식이 확정되지 않았으므로
`evidence_score=0`, `score_use_level=reference_only`만 허용한다.
양성이라도 `reference_only`이면 `evidence_score=0`만 허용한다. `source_authority_score`를
생략하면 근거 등급에 따라 `high=0.9`, `medium=0.7`, `low=0.5`를 적용한다.

## 운영 불변조건

- 후보 import만으로 추천 점수는 바뀌지 않는다.
- 기각은 `ingredient_evidence`를 만들지 않는다.
- 승인과 런타임 근거 생성은 한 트랜잭션이다.
- 동일 성분×효능×PMID/DOI 후보는 한 행만 존재한다.
- 후보·판정 이력은 seed가 삭제하거나 비활성화하지 않는다.
