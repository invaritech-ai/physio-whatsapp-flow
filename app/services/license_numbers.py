from __future__ import annotations

import re


_MAX_LICENSE_LENGTH = 64
_LICENSE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9 \-/#]*$")


def normalize_license_number(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().upper().split())
    return normalized or None


def is_valid_license_number(value: str | None) -> bool:
    if value is None:
        return False
    if len(value) < 3 or len(value) > _MAX_LICENSE_LENGTH:
        return False
    return _LICENSE_PATTERN.fullmatch(value) is not None
