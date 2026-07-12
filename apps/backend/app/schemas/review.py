from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


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


class ProductReviewCreateRequest(BaseModel):
    order_item_id: int = Field(gt=0)
    rating: int = Field(ge=1, le=5)
    review_text: str = Field(min_length=1, max_length=2000)
    is_repurchase_review: bool | None = None

    @field_validator("review_text")
    @classmethod
    def normalize_review_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("리뷰 본문은 1자 이상이어야 합니다.")
        return normalized


class ProductReviewUpdateRequest(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    review_text: str | None = Field(default=None, min_length=1, max_length=2000)
    is_repurchase_review: bool | None = None

    @field_validator("review_text")
    @classmethod
    def normalize_review_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("리뷰 본문은 1자 이상이어야 합니다.")
        return normalized

    @model_validator(mode="after")
    def validate_patch_fields(self) -> "ProductReviewUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("수정할 리뷰 필드를 하나 이상 입력해 주세요.")
        if "rating" in self.model_fields_set and self.rating is None:
            raise ValueError("별점은 null로 변경할 수 없습니다.")
        if "review_text" in self.model_fields_set and self.review_text is None:
            raise ValueError("리뷰 본문은 null로 변경할 수 없습니다.")
        return self


class ProductReviewMutationResponse(BaseModel):
    review: ProductReviewItem | None
    review_id: str
    product_id: str
    status: str
    review_summary: ProductReviewSummary
