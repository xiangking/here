from __future__ import annotations

from typing import Any

from services.selfie.selfie_service import SelfieService
from services.t2i.t2i_manager import T2IAdapterFactory, T2IManager


def resolve_selfie_provider(config_manager: Any) -> str:
    api = config_manager.config.api_config
    return str(
        getattr(api, "selfie_provider", "")
        or getattr(api, "t2i_provider", "")
        or "image-api"
    ).strip() or "image-api"


def selfie_photo_enabled(config_manager: Any) -> bool:
    system = config_manager.config.system_config
    return bool(getattr(system, "proactive_photo_enabled", False))


def selfie_t2i_base_kwargs(config_manager: Any, provider: str) -> dict[str, str]:
    if str(provider or "").strip().lower() == "image-api":
        return {"api_url": str(config_manager.config.api_config.t2i_api_url)}
    return {}


def build_selfie_runtime(
    config_manager: Any,
    *,
    existing_manager: T2IManager | None = None,
    enabled_only: bool = True,
) -> tuple[SelfieService | None, T2IManager | None]:
    if enabled_only and not selfie_photo_enabled(config_manager):
        return None, existing_manager

    provider = resolve_selfie_provider(config_manager)
    kwargs = config_manager.merged_t2i_factory_kwargs(
        provider,
        selfie_t2i_base_kwargs(config_manager, provider),
    )
    adapter = T2IAdapterFactory.create_adapter(adapter_name=provider, **kwargs)
    if existing_manager is None:
        manager = T2IManager(adapter)
    else:
        existing_manager.set_t2i_adapter(adapter)
        manager = existing_manager
    service = SelfieService(
        t2i_manager=manager,
        provider_name=provider,
        default_kwargs=dict(getattr(config_manager.config.api_config, "selfie_extra_configs", {}) or {}),
    )
    return service, manager
