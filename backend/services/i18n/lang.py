"""Language codes shared by the app (normalization, supported set)."""

from __future__ import annotations

SUPPORTED_LANGS: tuple[str, ...] = ("zh_CN", "en", "ja", "ko")


def normalize_lang(code: str | None) -> str:
    if not code:
        return "zh_CN"
    c = str(code).strip().replace("-", "_")
    low = c.lower()
    if low in ("zh", "zh_cn", "chinese", "cmn", "hans"):
        return "zh_CN"
    if low in ("en", "eng", "english"):
        return "en"
    if low in ("ja", "jp", "jpn", "japanese"):
        return "ja"
    if low in ("ko", "kr", "kor", "korean"):
        return "ko"
    if c in SUPPORTED_LANGS:
        return c
    return "zh_CN"
