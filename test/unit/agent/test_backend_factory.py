from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from core.agent import (
    HermesAgentBackend,
    InternalAgentBackend,
    create_agent_backend,
)
from core.agent.backend_factory import HERMES_AGENT_BACKEND, normalize_agent_backend
from internal_agent.context import AgentContext


class _ConfigManager:
    def __init__(self, backend: str, *, internal_agent_config: dict | None = None):
        self.config = types.SimpleNamespace(
            api_config=types.SimpleNamespace(agent_backend=backend)
        )
        self.internal_agent_config = internal_agent_config or {
            "provider": "openai-compatible",
            "model": "test-model",
            "base_url": "https://example.test/v1",
            "api_key": "secret",
        }

    def get_hermes_config(self):
        return {
            "max_iterations": 90,
            "enabled_toolsets": ["memory", "session_search"],
            "disabled_toolsets": [],
            "reasoning_config": {},
            "max_tokens": None,
            "stream": True,
            "use_internal_memory": True,
            "disable_hermes_native_memory": True,
        }

    def get_internal_agent_config(self):
        return dict(self.internal_agent_config)


def test_normalize_agent_backend_aliases():
    assert normalize_agent_backend("hermes") == "hermes-agent"
    assert normalize_agent_backend("internal_agent") == "internal-agent"
    assert normalize_agent_backend("auto") == "auto"
    assert normalize_agent_backend("") == "auto"


def test_factory_selects_hermes_agent(monkeypatch):
    import core.agent.backend_factory as factory

    monkeypatch.setattr(factory, "hermes_agent_available", lambda: True)
    backend = create_agent_backend(_ConfigManager("hermes-agent"))
    assert isinstance(backend, HermesAgentBackend)
    assert not isinstance(backend, InternalAgentBackend)
    assert backend.requested_backend_id == HERMES_AGENT_BACKEND
    assert backend.selected_backend_id == HERMES_AGENT_BACKEND


def test_factory_selects_internal_agent():
    backend = create_agent_backend(_ConfigManager("internal-agent"))
    assert isinstance(backend, InternalAgentBackend)


def test_auto_falls_back_to_internal_agent_when_hermes_missing(monkeypatch):
    import core.agent.backend_factory as factory

    monkeypatch.setattr(factory, "hermes_agent_available", lambda: False)
    backend = create_agent_backend(_ConfigManager("auto"))
    assert isinstance(backend, InternalAgentBackend)
    assert backend.requested_backend_id == "auto"
    assert backend.selected_backend_id == "internal-agent"


def test_auto_prefers_local_hermes_agent(monkeypatch):
    import core.agent.backend_factory as factory

    monkeypatch.setattr(factory, "hermes_agent_available", lambda: True)
    backend = create_agent_backend(_ConfigManager("auto"))
    assert isinstance(backend, HermesAgentBackend)
    assert not isinstance(backend, InternalAgentBackend)
    assert backend.requested_backend_id == "auto"
    assert backend.selected_backend_id == "hermes-agent"


def test_hermes_available_requires_model_configuration(monkeypatch):
    import core.agent.backend_factory as factory

    monkeypatch.setattr(factory.importlib.util, "find_spec", lambda _name: object())

    config_mod = types.ModuleType("hermes_cli.config")
    config_mod.load_config = lambda: {"model": {}}
    hermes_pkg = types.ModuleType("hermes_cli")
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)

    assert factory.hermes_agent_available() is False

    config_mod.load_config = lambda: {
        "model": {"provider": "openai-compatible", "default": "test-model"}
    }
    assert factory.hermes_agent_available() is True


def test_hermes_request_falls_back_to_internal_when_local_hermes_missing(monkeypatch):
    import core.agent.backend_factory as factory

    monkeypatch.setattr(factory, "hermes_agent_available", lambda: False)
    backend = create_agent_backend(_ConfigManager("hermes-agent"))
    assert isinstance(backend, InternalAgentBackend)
    assert backend.requested_backend_id == "hermes-agent"
    assert backend.selected_backend_id == "internal-agent"


def test_internal_agent_backend_uses_independent_agent(monkeypatch):
    calls = []

    class FakeInternalAgent:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def run_conversation(self, *args, **kwargs):
            return {"final_response": "ok", "messages": []}

    mod = types.ModuleType("internal_agent")
    mod.InternalAgent = FakeInternalAgent
    monkeypatch.setitem(sys.modules, "internal_agent", mod)

    cfg = _ConfigManager("internal-agent")
    backend = InternalAgentBackend.from_config_manager(cfg)
    assert backend.chat("hi", stream=False) == "ok"
    assert calls[-1]["model"] == "test-model"
    assert calls[-1]["base_url"] == "https://example.test/v1"
    assert calls[-1]["api_key"] == "secret"


def test_internal_agent_backend_does_not_touch_hermes_home(monkeypatch, tmp_path):
    calls = []

    class FakeInternalAgent:
        def __init__(self, **kwargs):
            calls.append({"init": kwargs, "run_env": None})

        def run_conversation(self, *args, **kwargs):
            calls[-1]["run_env"] = os.environ.get("HERMES_HOME")
            return {"final_response": "ok", "messages": []}

    mod = types.ModuleType("internal_agent")
    mod.InternalAgent = FakeInternalAgent
    monkeypatch.setitem(sys.modules, "internal_agent", mod)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "real-hermes-home"))

    memory_home = tmp_path / "internal-agent-memory-home"
    backend = InternalAgentBackend.from_config_manager(
        _ConfigManager("internal-agent")
    )
    assert backend.chat(
        "hi",
        context=AgentContext(memory_home=memory_home),
        stream=False,
    ) == "ok"

    assert os.environ["HERMES_HOME"] == str(tmp_path / "real-hermes-home")
    assert calls[-1]["run_env"] == str(tmp_path / "real-hermes-home")
    assert calls[-1]["init"]["memory_home"] == str(memory_home)
