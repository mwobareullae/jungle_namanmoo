from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.models.data_contract import ConcernEffect, ConcernTag
from app.services.data_loader import load_concern_effects, load_concern_tags


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

    tag_dir = data_dir if (data_dir / "tags.json").exists() else examples_dir
    concern_tags = load_concern_tags(tag_dir)
    effect_dir = tag_dir if (tag_dir / "concern_to_effect.json").exists() else examples_dir
    concern_effects = _filter_effects_for_tags(
        load_concern_effects(effect_dir),
        concern_tags,
    )

    return FileConcernRepository(concern_tags, concern_effects)


def _filter_effects_for_tags(
    concern_effects: tuple[ConcernEffect, ...],
    concern_tags: tuple[ConcernTag, ...],
) -> tuple[ConcernEffect, ...]:
    tag_ids = {tag.tag_id for tag in concern_tags}
    return tuple(effect for effect in concern_effects if effect.tag_id in tag_ids)
