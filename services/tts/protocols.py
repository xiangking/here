from __future__ import annotations

from abc import ABC, abstractmethod


class TTSAdapter(ABC):
    """Abstract text-to-speech adapter.

    Base defaults and conventions:
        - ``get_config_schema()``: Returns ``{}`` by default (no extra API-tab fields). Non-empty schema
          uses the standard adapter schema meta keys.
        - Constructor arguments are defined by ``TTSAdapterFactory`` and each subclass; this base does not declare them.
    """

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        """Metadata for adapter-specific options; empty ``{}`` means none."""
        return {}

    @abstractmethod
    def generate_speech(self, text, file_path=None, **kwargs):
        pass

    @abstractmethod
    def switch_model(self, model_info):
        pass
