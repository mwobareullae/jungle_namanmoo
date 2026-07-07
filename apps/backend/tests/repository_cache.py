from functools import lru_cache
from pathlib import Path

from app.services.repository import DataRepository, load_repository


def cached_repository(data_dir: Path) -> DataRepository:
    return _load_repository(str(data_dir.resolve()))


@lru_cache(maxsize=None)
def _load_repository(data_dir: str) -> DataRepository:
    return load_repository(Path(data_dir))
