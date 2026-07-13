from app.services.scoring import ScoreEvidence, _build_reason_summary


def _score_evidence(*, evidence_id: int | None) -> ScoreEvidence:
    return ScoreEvidence(
        ingredient_id=1,
        effect_id=1,
        evidence_id=evidence_id,
        ingredient_name="부틸렌글라이콜",
        effect_name="보습·장벽",
        evidence_level=None,
        contribution_score=0.32,
        reason="",
    )


def test_reason_summary_labels_evidence_free_function_prior() -> None:
    summary = _build_reason_summary((_score_evidence(evidence_id=None),))

    assert "공식 성분 기능 분류 기반" in summary
    assert "효능 근거" not in summary


def test_reason_summary_keeps_evidence_wording_when_evidence_exists() -> None:
    summary = _build_reason_summary((_score_evidence(evidence_id=10),))

    assert "효능 근거" in summary
