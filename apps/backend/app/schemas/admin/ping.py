from pydantic import BaseModel


class AdminPingResponse(BaseModel):
    """관리자 모듈 연결 확인 응답 계약."""

    status: str
    scope: str
