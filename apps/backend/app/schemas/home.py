from pydantic import BaseModel, Field


class HomeSectionProduct(BaseModel):
    product_id: str
    brand: str
    name: str
    category_code: str
    category_name: str
    thumbnail_url: str
    lowest_price: int
    original_price: int | None = None
    discount_rate: int | None = None
    purchase_url: str | None = None
    badges: list[str]
    tags: list[str]
    reason_summary: str
    display_score: int
    sales_status: str = "UNKNOWN"
    stock_status: str = "UNKNOWN"
    available_quantity: int | None = None
    in_stock: bool = False


class HomeSection(BaseModel):
    section_id: str
    title: str
    subtitle: str
    section_type: str
    algorithm: str
    products: list[HomeSectionProduct]


class HomeLayoutSection(BaseModel):
    section_id: str
    title: str
    subtitle: str
    section_type: str
    endpoint: str
    lazy_load: bool = True


class HomeLayoutResponse(BaseModel):
    sections: list[HomeLayoutSection]


class HomeProductSectionResponse(BaseModel):
    section_id: str
    title: str
    subtitle: str
    section_type: str
    algorithm: str
    category_code: str | None = None
    limit: int
    products: list[HomeSectionProduct]
    skin_type: str | None = None
    sensitivity: str | None = None
    personalization_sources: list[str] = Field(default_factory=list)
