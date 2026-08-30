"""Agent backend selection."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from typing import Any

from core.agent.hermes_backend import HermesAgentBackend
from core.agent.internal_agent_backend import InternalAgentBackend


HERMES_AGENT_BACKEND = "hermes-agent"
INTERNAL_AGENT_BACKEND = "internal-agent"
AUTO_AGENT_BACKEND = "auto"
DEFAULT_AGENT_BACKEND = AUTO_AGENT_BACKEND


def normalize_agent_backend(value: str | None) -> str:
    key = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "": DEFAULT_AGENT_BACKEND,
        "hermes": HERMES_AGENT_BACKEND,
        "hermes-agent": HERMES_AGENT_BACKEND,
        "local-hermes": HERMES_AGENT_BACKEND,
        "internal": INTERNAL_AGENT_BACKEND,
        "internal-agent": INTERNAL_AGENT_BACKEND,
        "core": INTERNAL_AGENT_BACKEND,
        "internal": INTERNAL_AGENT_BACKEND,
        "auto": AUTO_AGENT_BACKEND,
    }
    return aliases.get(key, key)


def hermes_agent_available() -> bool:
    if (
        importlib.util.find_spec("run_agent") is None
        or importlib.util.find_spec("hermes_cli.config") is None
    ):
        return False
    try:
        from hermes_cli.config import load_config

        model_cfg = (load_config().get("model") or {})
    except Exception:
        return False
    if not isinstance(model_cfg, dict):
        return False
    provider = str(model_cfg.get("provider") or "").strip()
    model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
    return bool(provider and model)


def create_agent_backend(
    config_manager: Any,
    *,
    system_prompt: str = "",
    status_callback: Callable[[str], None] | None = None,
    tool_status_callback: Callable[[str], None] | None = None,
):
    api = getattr(getattr(config_manager, "config", None), "api_config", None)
    requested = normalize_agent_backend(getattr(api, "agent_backend", None))
    selected = requested
    if requested in {AUTO_AGENT_BACKEND, HERMES_AGENT_BACKEND}:
        selected = HERMES_AGENT_BACKEND if hermes_agent_available() else INTERNAL_AGENT_BACKEND

    backend_cls = {
        HERMES_AGENT_BACKEND: HermesAgentBackend,
        INTERNAL_AGENT_BACKEND: InternalAgentBackend,
    }.get(selected)
    if backend_cls is None:
        raise ValueError(f"未知 agent backend: {requested}")
    backend = backend_cls.from_config_manager(
        config_manager,
        system_prompt=system_prompt,
        status_callback=status_callback,
        tool_status_callback=tool_status_callback,
    )
    setattr(backend, "requested_backend_id", requested)
    setattr(backend, "selected_backend_id", selected)
    return backend
