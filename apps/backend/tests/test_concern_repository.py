"""concern→effect 매핑 로더 회귀 테스트.

과거 결함(2026-07): get_default_concern_repository가 tags.json은 data_dir에서,
concern_to_effect.json은 없으면 examples 폴백으로 따로 갈라 로드해, 진짜 태그와
옛 효과어휘가 짝이 안 맞는 조합을 만들었다. 옛 어휘(effect_sebum_control 등)는
채점 택소노미에 없어 효능·근거·함량 3개 점수축이 조용히 죽었다. 아래 테스트가
그 회귀를 막는다.
"""
import json
from pathlib import Path

import pytest

from app.services.concern_repository import (
    _load_effect_taxonomy,
    _validate_effect_vocabulary,
)
from app.models.data_contract import ConcernEffect


def _resolve_data_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data"
        if (candidate / "concern_to_effect.json").exists():
            return candidate
    raise AssertionError("data/concern_to_effect.json을 찾지 못함")


DATA_DIR = _resolve_data_dir()


def _concern_effect_vocab(data_dir: Path) -> set[str]:
    codes: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and value.startswith("effect_"):
                    codes.add(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(json.loads((data_dir / "concern_to_effect.json").read_text(encoding="utf-8-sig")))
    return codes


def test_shipped_concern_effect_vocab_is_subset_of_taxonomy():
    """배포 concern_to_effect.json의 효과 어휘가 채점 택소노미의 부분집합이어야 한다.

    이 assert가 깨지면 = 매핑이 채점이 모르는 효과코드를 참조 = 그 질문의 효능·근거·
    함량 축이 죽는다. (옛 examples 어휘가 새어들어오면 여기서 잡힌다.)
    """
    taxonomy = _load_effect_taxonomy(DATA_DIR)
    assert taxonomy, "ingredient_effect.csv effect_id 택소노미가 비어있음"
    vocab = _concern_effect_vocab(DATA_DIR)
    assert vocab, "concern_to_effect.json 효과 어휘가 비어있음"
    unknown = sorted(vocab - taxonomy)
    assert not unknown, (
        f"concern_to_effect.json이 택소노미에 없는 효과코드 참조: {unknown} "
        f"(택소노미 {sorted(taxonomy)})"
    )


def test_validate_effect_vocabulary_rejects_unknown_code():
    """택소노미에 없는 코드를 참조하는 매핑은 즉시 실패해야 한다."""
    bad = (
        ConcernEffect(
            tag_id="concern_pore",
            effect_id="effect_sebum_control",  # 옛 어휘, 택소노미에 없음
            effect_name="피지",
            weight=1.0,
        ),
    )
    with pytest.raises(ValueError, match="택소노미에 없는 효과코드"):
        _validate_effect_vocabulary(bad, DATA_DIR)


def test_validate_effect_vocabulary_accepts_known_codes():
    """택소노미에 있는 코드만 쓰면 통과해야 한다."""
    taxonomy = _load_effect_taxonomy(DATA_DIR)
    good = tuple(
        ConcernEffect(tag_id="concern_x", effect_id=code, effect_name=code, weight=1.0)
        for code in sorted(taxonomy)[:2]
    )
    _validate_effect_vocabulary(good, DATA_DIR)  # 예외 없이 통과


def test_missing_concern_to_effect_raises(tmp_path, monkeypatch):
    """tags.json은 있는데 concern_to_effect.json이 없는 반쪽 디렉터리 = 즉시 실패.

    (과거엔 조용히 examples 폴백으로 갈려 효과축이 죽었다.)
    """
    (tmp_path / "tags.json").write_text("[]", encoding="utf-8")
    # concern_to_effect.json 일부러 안 만듦

    import app.services.concern_repository as repo
    from app.core.config import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    repo.get_default_concern_repository.cache_clear()
    try:
        with pytest.raises(FileNotFoundError, match="concern_to_effect.json"):
            repo.get_default_concern_repository()
    finally:
        repo.get_default_concern_repository.cache_clear()
