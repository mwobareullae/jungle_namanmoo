from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    product_id: str
    brand: str
    name: str
    category: str
    skin_type_tags: tuple[str, ...]
    thumbnail_url: str | None
    image_urls: tuple[str, ...]


@dataclass(frozen=True)
class ProductPrice:
    product_id: str
    mall_name: str
    price: int
    product_url: str
    is_lowest: bool
    currency: str


@dataclass(frozen=True)
class ProductIngredient:
    product_id: str
    ingredient_id: str
    ingredient_name: str
    content_confidence: str
    display_order: int
    concentration_text: str | None
    concentration_value: float | None
    concentration_unit: str | None
    concentration_confidence: str
    normalized_concentration_value: float | None
    normalized_concentration_unit: str | None


@dataclass(frozen=True)
class Ingredient:
    ingredient_id: str
    name_ko: str
    name_en: str
    description: str
    source_url: str | None


@dataclass(frozen=True)
class IngredientEffect:
    ingredient_id: str
    effect_id: str
    effect_name: str
    effect_score: int


@dataclass(frozen=True)
class IngredientEvidence:
    ingredient_id: str
    effect_id: str
    evidence_level: str
    evidence_score: int
    source_title: str
    source_url: str | None
    summary: str


@dataclass(frozen=True)
class RiskFlag:
    ingredient_id: str
    risk_type: str
    display_text: str
    severity: str


@dataclass(frozen=True)
class ConcernTag:
    tag_id: str
    name: str
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class ConcernEffect:
    tag_id: str
    effect_id: str
    effect_name: str
    weight: float


@dataclass(frozen=True)
class SearchDocument:
    doc_id: str
    source_type: str
    source_id: str
    text: str


@dataclass(frozen=True)
class DataCatalog:
    products: tuple[Product, ...]
    product_prices: tuple[ProductPrice, ...]
    product_ingredients: tuple[ProductIngredient, ...]
    ingredients: tuple[Ingredient, ...]
    ingredient_effects: tuple[IngredientEffect, ...]
    ingredient_evidence: tuple[IngredientEvidence, ...]
    risk_flags: tuple[RiskFlag, ...]
    concern_tags: tuple[ConcernTag, ...]
    concern_effects: tuple[ConcernEffect, ...]
    search_documents: tuple[SearchDocument, ...]
