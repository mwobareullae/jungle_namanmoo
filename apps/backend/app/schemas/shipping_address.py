import re


_PHONE_CHARACTERS = re.compile(r"^[0-9\s-]+$")
_POSTAL_CODE = re.compile(r"^\d{5}$")


def normalize_recipient_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("recipient_name is required")
    if not all(character.isalpha() or character in " ·'-" for character in normalized):
        raise ValueError("recipient_name must contain letters only")
    return normalized


def normalize_phone(value: str) -> str:
    normalized = value.strip()
    if not _PHONE_CHARACTERS.fullmatch(normalized):
        raise ValueError("phone must contain digits, spaces, and optional hyphens only")

    digits = re.sub(r"[\s-]", "", normalized)
    if not 10 <= len(digits) <= 11:
        raise ValueError("phone must contain 10 to 11 digits")
    return digits


def normalize_postal_code(value: str) -> str:
    normalized = value.strip()
    if not _POSTAL_CODE.fullmatch(normalized):
        raise ValueError("postal_code must contain exactly 5 digits")
    return normalized


def normalize_required_address(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized
