from __future__ import annotations

from datetime import datetime, timedelta

import core.timezone as timezone_helpers


def test_asia_shanghai_falls_back_to_fixed_offset_when_tzdata_is_missing(monkeypatch):
    def missing_zoneinfo(_name: str):
        raise timezone_helpers.ZoneInfoNotFoundError("missing tzdata")

    monkeypatch.setattr(timezone_helpers, "ZoneInfo", missing_zoneinfo)
    timezone_helpers.clear_timezone_cache()

    tz = timezone_helpers.resolve_timezone("Asia/Shanghai")
    moment = datetime(2026, 5, 30, 12, 0, tzinfo=tz)

    assert moment.utcoffset() == timedelta(hours=8)
    assert moment.tzname() == "Asia/Shanghai"


def test_unknown_timezone_falls_back_without_crashing(monkeypatch):
    def missing_zoneinfo(_name: str):
        raise timezone_helpers.ZoneInfoNotFoundError("missing tzdata")

    monkeypatch.setattr(timezone_helpers, "ZoneInfo", missing_zoneinfo)
    timezone_helpers.clear_timezone_cache()

    now = timezone_helpers.now_in_timezone("Mars/Base")

    assert now.tzinfo is not None
