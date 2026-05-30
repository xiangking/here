"""Timezone helpers that work even when platform tzdata is missing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_FALLBACK_TIMEZONE = "Asia/Shanghai"

_FIXED_TIMEZONES = {
    "Asia/Shanghai": timezone(timedelta(hours=8), "Asia/Shanghai"),
}


def resolve_timezone(timezone_name: str | None, fallback_name: str = DEFAULT_FALLBACK_TIMEZONE) -> tzinfo:
    """Return a timezone object, falling back instead of crashing on Windows."""
    name = _normalize_timezone_name(timezone_name, fallback_name)
    return _resolve_timezone_cached(name)


def now_in_timezone(timezone_name: str | None, fallback_name: str = DEFAULT_FALLBACK_TIMEZONE) -> datetime:
    return datetime.now(resolve_timezone(timezone_name, fallback_name))


def clear_timezone_cache() -> None:
    _resolve_timezone_cached.cache_clear()


def _normalize_timezone_name(timezone_name: str | None, fallback_name: str) -> str:
    name = str(timezone_name or "").strip()
    if name:
        return name
    fallback = str(fallback_name or "").strip()
    return fallback or "UTC"


@lru_cache(maxsize=64)
def _resolve_timezone_cached(timezone_name: str) -> tzinfo:
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        fixed = _FIXED_TIMEZONES.get(timezone_name)
        if fixed is not None:
            return fixed
        local_timezone = datetime.now().astimezone().tzinfo
        return local_timezone or timezone.utc
