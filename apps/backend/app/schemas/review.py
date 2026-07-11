from datetime import datetime

from pydantic import BaseModel, Field


class ProductReviewSummary(BaseModel):
    review_count: int
    average_rating: float | None
    rating_distribution: dict[int, int]
    general_review_count: int
    month_use_review_count: int
    repurchase_known_count: int
    repurchase_review_count: int
    repurchase_rate: float | None
    profile_labeled_review_count: int
    last_reviewed_at: datetime | None


class ProductReviewAuthor(BaseModel):
    display_name: str
    profile_image_url: str | None = None


class ProductReviewProfileLabel(BaseModel):
    dimension: str
    value_code: str
    display_label: str


class ProductReviewMedia(BaseModel):
    media_type: str
    url: str


class ProductReviewItem(BaseModel):
    review_id: str
    rating: int | None
    review_text: str | None
    reviewed_at: datetime | None
    option_text: str | None
    review_type: str | None
    is_repurchase_review: bool | None
    verified_purchase: bool | None
    helpful_count: int
    badges: list[str] = Field(default_factory=list)
    author: ProductReviewAuthor | None = None
    profile_labels: list[ProductReviewProfileLabel] = Field(default_factory=list)
    media: list[ProductReviewMedia] = Field(default_factory=list)


class ProductReviewsResponse(BaseModel):
    product_id: str
    sort: str
    limit: int
    items: list[ProductReviewItem]
    next_cursor: str | None
    has_next: bool
