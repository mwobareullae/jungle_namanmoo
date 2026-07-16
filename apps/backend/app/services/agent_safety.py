from __future__ import annotations

import re

from app.schemas.common import ApiError


# Do not treat phone numbers as sensitive credentials: the shipping-address flow
# legitimately needs them. These patterns target secrets that must never enter an
# LLM request or an agent conversation history.
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?:비밀번호|password|passwd|pwd)\s*(?:[:=]|은|는)\s*\S{4,}", re.IGNORECASE),
    re.compile(r"(?:api[ _-]?key|access[ _-]?token|refresh[ _-]?token)\s*(?:[:=]|은|는)\s*\S{8,}", re.IGNORECASE),
)
_CARD_NUMBER_PATTERN = re.compile(r"(?:\d[ -]?){13,19}")
_CARD_HINT_PATTERN = re.compile(r"(?:카드(?:번호)?|card(?: number)?|cvc|cvv)", re.IGNORECASE)


def reject_sensitive_agent_input(*texts: str) -> None:
    """Reject credentials before they can be sent to an external LLM provider."""
    for text in texts:
        if not text:
            continue
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            raise ApiError(
                400,
                "AGENT_SENSITIVE_INPUT",
                "비밀번호·토큰·API 키는 채팅에 입력할 수 없어요.",
            )
        if _CARD_HINT_PATTERN.search(text) and _CARD_NUMBER_PATTERN.search(text):
            raise ApiError(
                400,
                "AGENT_SENSITIVE_INPUT",
                "카드 정보는 채팅에 입력할 수 없어요.",
            )
