from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Product:
    product_id: str
    brand: str
    name: str
    category: str
    skin_type_tags: tuple[str, ...]
    thumbnail_url: str | None
    image_urls: tuple[str, ...]
    functional_review_text: str | None
    functional_cosmetic_status: str | None
    functional_cosmetic_claims: tuple[str, ...]
    functional_claim_confidence: str | None
    functional_claim_basis: str | None
    is_recommendable: bool = True
    recommend_exclude_reason: str | None = None


@dataclass(frozen=True)
class ProductPrice:
    product_id: str
    mall_name: str
    price: int
    product_url: str
    is_lowest: bool
    currency: str


@dataclass(frozen=True)
class ProductImageAsset:
    product_id: str
    image_type: str
    display_order: int
    storage_key: str


@dataclass(frozen=True)
class ProductInventory:
    product_id: str
    stock_quantity: int
    sales_status: str
    safety_stock: int
    inventory_source: str


@dataclass(frozen=True)
class ProductMarketSignal:
    product_id: str
    review_count: int
    average_rating: float | None
    sales_count: int
    sales_rank: int | None
    recent_view_count: int
    wishlist_count: int
    cart_add_count: int
    source: str
    updated_at: str | None


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
class ProductSkinProfile:
    product_id: str
    dry_fit: float
    oily_fit: float
    combination_fit: float
    normal_fit: float
    dehydrated_oily_fit: float
    sensitive_fit: float
    sensitivity_tag: str
    confidence: str
    reason: str


@dataclass(frozen=True)
class Ingredient:
    ingredient_id: str
    name_ko: str
    name_en: str
    description: str
    source_url: str | None


@dataclass(frozen=True)
class IngredientAlias:
    ingredient_id: str
    alias: str
    alias_type: str
    confidence: str
    source: str


@dataclass(frozen=True)
class IngredientEffect:
    ingredient_id: str
    effect_id: str
    effect_name: str
    effect_score: int


@dataclass(frozen=True)
class IngredientEffectRange:
    ingredient_id: str
    effect_id: str
    unit: str
    meaningful_min: float | None
    optimal_min: float | None
    optimal_max: float | None
    excessive_min: float | None
    range_confidence: str
    source_type: str
    source_url: str | None
    note: str


@dataclass(frozen=True)
class IngredientEvidence:
    ingredient_id: str
    effect_id: str
    evidence_level: str
    evidence_score: int
    source_title: str
    source_url: str | None
    summary: str
    source_type: str | None
    pmid: str | None
    doi: str | None
    source_authority_score: float | None
    canonical_evidence_key: str
    review_status: str
    result_direction: str
    score_use_level: str
    is_representative: bool
    representative_rank: int | None
    is_current: bool
    review_note: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None


@dataclass(frozen=True)
class RiskFlag:
    ingredient_id: str
    risk_type: str
    display_text: str
    severity: str
    severity_score: float | None
    applies_to: tuple[str, ...]
    condition: str | None
    source_type: str | None
    source_url: str | None


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
    product_image_assets: tuple[ProductImageAsset, ...]
    product_inventories: tuple[ProductInventory, ...]
    product_market_signals: tuple[ProductMarketSignal, ...]
    product_ingredients: tuple[ProductIngredient, ...]
    product_skin_profiles: tuple[ProductSkinProfile, ...]
    ingredients: tuple[Ingredient, ...]
    ingredient_aliases: tuple[IngredientAlias, ...]
    ingredient_effects: tuple[IngredientEffect, ...]
    ingredient_effect_ranges: tuple[IngredientEffectRange, ...]
    ingredient_evidence: tuple[IngredientEvidence, ...]
    risk_flags: tuple[RiskFlag, ...]
    concern_tags: tuple[ConcernTag, ...]
    concern_effects: tuple[ConcernEffect, ...]
    search_documents: tuple[SearchDocument, ...]
