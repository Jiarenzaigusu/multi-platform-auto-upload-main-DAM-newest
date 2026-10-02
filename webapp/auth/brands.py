from __future__ import annotations

import unicodedata


MAX_BRAND_NAME_LENGTH = 120


def normalize_brand_name(value: str) -> tuple[str, str]:
    """Return a display name and a stable lookup key for one brand."""
    display_name = unicodedata.normalize("NFKC", value or "").strip()
    display_name = " ".join(display_name.split())
    if not display_name:
        return "", ""
    if len(display_name) > MAX_BRAND_NAME_LENGTH:
        raise ValueError(f"品牌名不能超过 {MAX_BRAND_NAME_LENGTH} 个字符")
    return display_name, display_name.casefold()
