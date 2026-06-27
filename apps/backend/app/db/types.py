from sqlalchemy import JSON, BigInteger, Integer
from sqlalchemy.dialects.postgresql import JSONB


def jsonb_type() -> JSON:
    return JSON().with_variant(JSONB, "postgresql")


def big_integer_pk_type() -> BigInteger:
    return BigInteger().with_variant(Integer, "sqlite")
