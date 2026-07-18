import csv
import logging
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.models.data_contract import ConcernEffect, ConcernTag
from app.services.data_loader import load_concern_effects, load_concern_tags

logger = logging.getLogger(__name__)


class FileConcernRepository:
    def __init__(
        self,
        concern_tags: tuple[ConcernTag, ...],
        concern_effects: tuple[ConcernEffect, ...],
    ) -> None:
        self._concern_tags = concern_tags
        self._effects_by_tag_id: dict[str, list[ConcernEffect]] = {}
        for effect in concern_effects:
            self._effects_by_tag_id.setdefault(effect.tag_id, []).append(effect)

    def list_concern_tags(self) -> list[ConcernTag]:
        return list(self._concern_tags)

    def get_effects_for_concern(self, tag_id: str) -> list[ConcernEffect]:
        return list(self._effects_by_tag_id.get(tag_id, []))


@lru_cache(maxsize=1)
def get_default_concern_repository() -> FileConcernRepository:
    data_dir = Path(settings.data_dir)
    examples_dir = data_dir / "examples"

    # tags.json과 concern_to_effect.json은 한 쌍이다 — 반드시 같은 디렉터리에서 로드한다.
    # (과거 결함: tags는 data_dir에서, concern_to_effect.json은 없으면 examples 폴백으로
    #  따로 갈려서, 진짜 태그 + 옛 효과어휘가 짝이 안 맞는 조합이 되었다. 그 옛 어휘
    #  (effect_sebum_control·effect_texture 등)는 채점 효과 택소노미에 없어서 desired_effects
    #  조회가 0건이 되고 효능·근거·함량 3개 점수축이 조용히 죽었다. 이 함수가 그 결함의 진원지.)
    tag_dir = data_dir if (data_dir / "tags.json").exists() else examples_dir
    concern_effect_path = tag_dir / "concern_to_effect.json"
    if not concern_effect_path.exists():
        raise FileNotFoundError(
            f"concern_to_effect.json이 {tag_dir}에 없습니다. tags.json과 반드시 같은 "
            f"디렉터리에 있어야 합니다 — 다른 디렉터리로 폴백하면 효과 어휘가 채점 "
            f"택소노미와 어긋나 효능·근거·함량 축이 조용히 죽습니다."
        )

    concern_tags = load_concern_tags(tag_dir)
    concern_effects = _filter_effects_for_tags(
        load_concern_effects(tag_dir),
        concern_tags,
    )
    _validate_effect_vocabulary(concern_effects, tag_dir)

    return FileConcernRepository(concern_tags, concern_effects)


def _filter_effects_for_tags(
    concern_effects: tuple[ConcernEffect, ...],
    concern_tags: tuple[ConcernTag, ...],
) -> tuple[ConcernEffect, ...]:
    tag_ids = {tag.tag_id for tag in concern_tags}
    return tuple(effect for effect in concern_effects if effect.tag_id in tag_ids)


def _load_effect_taxonomy(data_dir: Path) -> set[str]:
    """같은 데이터 디렉터리의 ingredient_effect.csv effect_id 컬럼 = 채점 효과 택소노미."""
    taxonomy_path = data_dir / "ingredient_effect.csv"
    if not taxonomy_path.exists():
        return set()
    with taxonomy_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "effect_id" not in reader.fieldnames:
            return set()
        return {row["effect_id"] for row in reader if row.get("effect_id")}


def _validate_effect_vocabulary(
    concern_effects: tuple[ConcernEffect, ...],
    data_dir: Path,
) -> None:
    """concern→effect 매핑의 효과 어휘가 채점 택소노미에 존재하는지 검증.

    어긋나면 그 효과를 요구한 질문의 효능·근거·함량 축이 통째로 죽으므로, 조용히
    넘어가지 않고 즉시 실패시킨다 (택소노미 소스가 없으면 검증만 건너뛴다).
    """
    taxonomy = _load_effect_taxonomy(data_dir)
    if not taxonomy:
        logger.warning(
            "효과 택소노미 소스(ingredient_effect.csv)를 %s에서 찾지 못해 "
            "concern→effect 어휘 검증을 건너뜁니다.",
            data_dir,
        )
        return
    unknown = sorted({e.effect_id for e in concern_effects} - taxonomy)
    if unknown:
        raise ValueError(
            f"concern_to_effect.json이 채점 택소노미에 없는 효과코드를 참조합니다: "
            f"{unknown} (소스 {data_dir}). 이 코드를 요구하는 질문은 효능·근거·함량 축이 "
            f"죽습니다. 매핑을 택소노미({sorted(taxonomy)})에 맞추세요."
        )
