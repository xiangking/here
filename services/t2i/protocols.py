from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class T2IAdapter(ABC):
    """Abstract text-to-image adapter.

    Base defaults and conventions:
        - ``get_config_schema()``: Returns ``{}`` by default; non-empty schema follows
          the standard adapter schema meta keys.
        - ``generate_image(prompt, file_path=None, **kwargs)``: Abstract signature defaults ``file_path``
          to ``None``. Constructor settings such as ``api_url`` are passed by subclasses / factories;
          defaults live in ``ApiConfig``.
    """

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        """Metadata for adapter-specific options; empty ``{}`` means none."""
        return {}

    @abstractmethod
    def generate_image(
        self, prompt: str, file_path: Optional[str] = None, **kwargs
    ) -> Optional[str]:
        pass

    @abstractmethod
    def switch_model(self, model_info: Dict[str, Any]) -> None:
        pass
