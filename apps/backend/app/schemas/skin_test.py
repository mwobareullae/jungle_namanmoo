from pydantic import BaseModel, Field

from app.schemas.profile import SkinProfileData


class SkinTestOptionResponse(BaseModel):
    id: int
    text: str


class SkinTestQuestionResponse(BaseModel):
    id: int
    text: str
    options: list[SkinTestOptionResponse]
    skip_conditions: dict | list | None = None


class SkinTestQuestionsResponse(BaseModel):
    version: str
    questions: list[SkinTestQuestionResponse]


class SkinTestAnswerInput(BaseModel):
    question_id: int
    option_id: int


class SkinTestSubmitRequest(BaseModel):
    version: str | None = None
    anonymous_id: str | None = None
    answers: list[SkinTestAnswerInput] = Field(min_length=1)


class SkinTestResultData(BaseModel):
    result_id: int
    skin_type: str
    sensitivity: str
    recommended_effects: list[str] = Field(default_factory=list)
    avoid_hint: list[str] = Field(default_factory=list)
    concern_tags: list[str] = Field(default_factory=list)
    type_code: str
    title: str
    subtitle: str | None = None
    image_storage_key: str | None = None


class SkinTestResultResponse(BaseModel):
    result: SkinTestResultData


class SkinTestApplyRequest(BaseModel):
    result_id: int


class SkinTestApplyResponse(BaseModel):
    success: bool = True
    skin_profile: SkinProfileData | None = None
