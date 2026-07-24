from sqlalchemy import JSON, BigInteger, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator, UserDefinedType


def jsonb_type() -> JSON:
    return JSON().with_variant(JSONB, "postgresql")


def big_integer_pk_type() -> BigInteger:
    return BigInteger().with_variant(Integer, "sqlite")


class _PostgresVector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kw) -> str:
        return f"vector({self.dimensions})"


class EmbeddingVector(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PostgresVector(self.dimensions))
        return dialect.type_descriptor(Text())
