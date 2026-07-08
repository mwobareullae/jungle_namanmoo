from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SkinProfileUpdateRequest(BaseModel):
    skin_type: str
    sensitivity: str
    avoid_ingredients: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)


class SignupSkinProfileRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    skin_type: str = Field(alias="skinType")
    sensitivity: str
    concerns: list[str] = Field(default_factory=list)
    avoid_ingredients: list[str] = Field(default_factory=list, alias="avoidIngredients")


class SkinProfileData(BaseModel):
    id: int
    user_id: int | None = None
    skin_type: str
    sensitivity: str
    skin_type_source: str
    sensitivity_source: str
    explicit_skin_type: str | None = None
    explicit_sensitivity: str | None = None
    avoid_ingredients: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    baumann_type_code: str | None = None
    baumann_inferred_skin_type: str | None = None
    baumann_inferred_sensitivity: str | None = None
    baumann_signal_weight: float
    latest_skin_test_result_id: int | None = None
    latest_skin_test_result_code: str | None = None
    commerce_profile: dict | None = None
    source: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkinProfileResponse(BaseModel):
    has_profile: bool
    profile: SkinProfileData | None = None
