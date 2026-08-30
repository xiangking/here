from __future__ import annotations

import os
from pathlib import Path

from infrastructure.paths import get_app_paths
from typing import Any

import yaml


class MessagingConfig:
    """Load local external-message settings from here and UniMessage-style sources."""

    DEFAULT_PATHS = (
        "~/.unimessage/config.yaml",
        "~/.config/unimessage/config.yaml",
    )

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = dict(data or {})

    @classmethod
    def auto_load(cls) -> "MessagingConfig":
        config = cls()
        for path in cls._candidate_paths():
            expanded = Path(path).expanduser()
            if not expanded.is_file():
                continue
            loaded = cls._load_yaml(expanded)
            if loaded:
                config.merge(loaded)
                break
        config.merge(cls._from_env())
        return config

    @classmethod
    def _candidate_paths(cls) -> list[str]:
        explicit = os.environ.get("HERE_MESSAGING_CONFIG") or os.environ.get("UNIMESSAGE_CONFIG")
        paths = [explicit] if explicit else []
        paths.append(str(get_app_paths().config_dir / "messaging.yaml"))
        paths.extend(cls.DEFAULT_PATHS)
        return [str(path) for path in paths if path]

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _from_env() -> dict[str, Any]:
        data: dict[str, Any] = {}
        for key, value in os.environ.items():
            if not key.startswith("UNIMESSAGE_"):
                continue
            parts = key[len("UNIMESSAGE_") :].lower().split("_", 1)
            if len(parts) != 2:
                continue
            platform, config_key = parts
            data.setdefault(platform, {})[config_key] = value
        return data

    def merge(self, other: dict[str, Any]) -> None:
        for raw_platform, value in other.items():
            platform = str(raw_platform or "").strip().lower()
            if not platform:
                continue
            if isinstance(value, dict):
                current = self._data.setdefault(platform, {})
                if isinstance(current, dict):
                    current.update(value)
                else:
                    self._data[platform] = dict(value)
            else:
                self._data[platform] = value

    def platform(self, channel: str) -> dict[str, Any]:
        value = self._data.get(str(channel or "").strip().lower(), {})
        return dict(value) if isinstance(value, dict) else {}

    def enabled(self, channel: str) -> bool:
        cfg = self.platform(channel)
        value = cfg.get("enabled", True)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}
        return bool(value)

    def set_platform(self, channel: str, values: dict[str, Any]) -> None:
        normalized = str(channel or "").strip().lower()
        if not normalized:
            return
        current = self._data.setdefault(normalized, {})
        if not isinstance(current, dict):
            current = {}
            self._data[normalized] = current
        current.update(values)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def save(self, path: str | Path | None = None) -> None:
        target = Path(path) if path is not None else get_app_paths().config_dir / "messaging.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            yaml.safe_dump(self._data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
