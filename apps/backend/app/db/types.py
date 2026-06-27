from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB


def jsonb_type() -> JSON:
    return JSON().with_variant(JSONB, "postgresql")
