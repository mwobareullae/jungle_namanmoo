from pydantic import BaseModel


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


class HomeSection(BaseModel):
    section_id: str
    title: str
    subtitle: str
    section_type: str
    algorithm: str
    products: list[HomeSectionProduct]


class HomeSectionsResponse(BaseModel):
    skin_type: str
    sensitivity: str
    category_code: str | None = None
    sections: list[HomeSection]
