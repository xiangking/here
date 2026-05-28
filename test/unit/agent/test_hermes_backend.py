from __future__ import annotations

import sys
import types
import os
from pathlib import Path

from core.agent import HermesAgentBackend, HermesBackendConfig
from internal_agent.context import AgentContext, CharacterSoul


class FakeAIAgent:
    instances = []
    fail_next_image_call = False
    return_failed_image_result = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.interrupted = False
        self.hermes_home_at_init = os.environ.get("HERMES_HOME")
        self.hermes_home_at_run = None
        self.run_conversation_user_messages = []
        self.run_conversation_system_messages = []
        self.api_retries_seen = []
        self._api_max_retries = 3
        FakeAIAgent.instances.append(self)

    def run_conversation(self, user_message, system_message=None, conversation_history=None, stream_callback=None, **kwargs):
        self.hermes_home_at_run = os.environ.get("HERMES_HOME")
        self.run_conversation_user_message = user_message
        self.run_conversation_user_messages.append(user_message)
        self.run_conversation_system_message = system_message
        self.run_conversation_system_messages.append(system_message)
        self.api_retries_seen.append(self._api_max_retries)
        if FakeAIAgent.fail_next_image_call and isinstance(user_message, list):
            FakeAIAgent.fail_next_image_call = False
            raise RuntimeError("No endpoints found that support image input")
        if FakeAIAgent.return_failed_image_result and isinstance(user_message, list):
            FakeAIAgent.return_failed_image_result = False
            return {
                "final_response": "API call failed after 1 retries: No endpoints found that support image input",
                "error": "No endpoints found that support image input",
                "failed": True,
                "messages": [{"role": "user", "content": user_message}],
            }
        if stream_callback is not None:
            stream_callback("hello")
            stream_callback(" world")
        return {
            "final_response": "hello world",
            "messages": [{"role": "user", "content": user_message}, {"role": "assistant", "content": "hello world"}],
            "completed": True,
        }

    def interrupt(self):
        self.interrupted = True


def install_fake_run_agent(monkeypatch):
    FakeAIAgent.instances.clear()
    FakeAIAgent.fail_next_image_call = False
    FakeAIAgent.return_failed_image_result = False
    import core.agent.hermes_backend as hermes_backend

    hermes_backend._IMAGE_UNSUPPORTED_MODEL_KEYS.clear()
    mod = types.ModuleType("run_agent")
    mod.AIAgent = FakeAIAgent
    monkeypatch.setitem(sys.modules, "run_agent", mod)


def install_fake_hermes_config(monkeypatch, by_home: dict[str | None, dict] | None = None):
    hermes_cli = types.ModuleType("hermes_cli")
    config_mod = types.ModuleType("hermes_cli.config")
    default_config = {
        "model": {
            "provider": "xiaomi",
            "default": "mimo-v2.5-pro",
            "base_url": "https://local-hermes.example/v1",
        }
    }
    if by_home is None:
        config_mod.load_config = lambda: default_config
    else:
        config_mod.load_config = lambda: by_home.get(os.environ.get("HERMES_HOME"), {"model": ""})
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)


def test_initialization_maps_config(monkeypatch):
    install_fake_run_agent(monkeypatch)
    install_fake_hermes_config(monkeypatch)
    backend = HermesAgentBackend(
        HermesBackendConfig(
            max_iterations=12,
            disabled_toolsets=["telegram"],
            reasoning_config={"effort": "low"},
        ),
        system_prompt="role",
    )

    assert backend.chat("hi", stream=False) == "hello world"
    kwargs = FakeAIAgent.instances[-1].kwargs
    assert kwargs["provider"] == "xiaomi"
    assert kwargs["model"] == "mimo-v2.5-pro"
    assert kwargs["base_url"] == "https://local-hermes.example/v1"
    assert "api_key" not in kwargs
    assert kwargs["quiet_mode"] is True
    assert kwargs["max_iterations"] == 12
    assert kwargs["disabled_toolsets"] == ["telegram"]
    assert kwargs["reasoning_config"] == {"effort": "low"}
    assert kwargs["skip_context_files"] is True
    assert kwargs["skip_memory"] is True
    assert kwargs["load_soul_identity"] is False


def test_model_config_uses_launch_home_when_context_home_is_active(monkeypatch, tmp_path):
    launch_home = tmp_path / "launch"
    character_home = tmp_path / "character"
    monkeypatch.setenv("HERMES_HOME", str(launch_home))

    import core.agent.hermes_backend as hermes_backend

    monkeypatch.setattr(hermes_backend, "_MODEL_CONFIG_HERMES_HOME", str(launch_home))
    install_fake_run_agent(monkeypatch)
    install_fake_hermes_config(
        monkeypatch,
        {
            str(launch_home): {
                "model": {
                    "provider": "xiaomi",
                    "default": "mimo-v2.5-pro",
                    "base_url": "https://launch.example/v1",
                }
            },
            str(character_home): {"model": ""},
        },
    )
    backend = HermesAgentBackend(HermesBackendConfig())

    backend.chat(
        "hi",
        context=AgentContext(memory_home=character_home),
        stream=False,
    )

    agent = FakeAIAgent.instances[-1]
    assert agent.kwargs["provider"] == "xiaomi"
    assert agent.kwargs["model"] == "mimo-v2.5-pro"
    assert agent.kwargs["base_url"] == "https://launch.example/v1"
    assert agent.hermes_home_at_init == str(character_home)
    assert agent.hermes_home_at_run == str(character_home)


def test_chat_stream_yields_deltas(monkeypatch):
    install_fake_run_agent(monkeypatch)
    backend = HermesAgentBackend(HermesBackendConfig())
    assert list(backend.chat("hi", stream=True)) == ["hello", " world"]


def test_default_toolsets_keep_memory_and_session_search(monkeypatch):
    install_fake_run_agent(monkeypatch)
    backend = HermesAgentBackend(
        HermesBackendConfig(enabled_toolsets=["memory", "session_search"])
    )

    backend.chat("hi", stream=False)

    assert FakeAIAgent.instances[-1].kwargs["enabled_toolsets"] == [
        "memory",
        "session_search",
    ]


def test_oneshot_without_tools_disables_toolsets(monkeypatch):
    install_fake_run_agent(monkeypatch)
    backend = HermesAgentBackend(HermesBackendConfig())
    assert backend.oneshot("translate", tools=False) == "hello world"
    agent = FakeAIAgent.instances[-1]
    assert agent.kwargs["enabled_toolsets"] == []
    assert "system_action 必须为 null" not in agent.kwargs["ephemeral_system_prompt"]
    assert agent.run_conversation_system_message == ""
    assert agent.hermes_home_at_init is not None
    assert agent.hermes_home_at_run == agent.hermes_home_at_init


def test_oneshot_can_use_temporary_toolsets(monkeypatch):
    install_fake_run_agent(monkeypatch)
    backend = HermesAgentBackend(
        HermesBackendConfig(
            enabled_toolsets=["memory"],
            disabled_toolsets=["telegram", "discord"],
        )
    )

    backend.oneshot(
        "send",
        system_prompt="send only",
        tools=True,
        enabled_toolsets=["telegram"],
        disabled_toolsets=[],
    )

    agent = FakeAIAgent.instances[-1]
    assert agent.kwargs["enabled_toolsets"] == ["telegram"]
    assert agent.kwargs["disabled_toolsets"] == []


def test_oneshot_is_silent_by_default(monkeypatch):
    install_fake_run_agent(monkeypatch)
    seen: list[str] = []
    backend = HermesAgentBackend(
        HermesBackendConfig(),
        tool_status_callback=seen.append,
        status_callback=seen.append,
    )

    backend.oneshot("plan", system_prompt="只输出 JSON", tools=False)

    agent = FakeAIAgent.instances[-1]
    assert agent.kwargs["status_callback"] is None
    assert agent.kwargs["tool_start_callback"] is None
    assert agent.kwargs["tool_complete_callback"] is None
    assert agent.kwargs["thinking_callback"] is None
    assert agent.kwargs["reasoning_callback"] is None
    assert seen == []


def test_oneshot_can_opt_in_to_callbacks(monkeypatch):
    install_fake_run_agent(monkeypatch)
    seen: list[str] = []
    backend = HermesAgentBackend(
        HermesBackendConfig(),
        tool_status_callback=seen.append,
        status_callback=seen.append,
    )

    backend.oneshot(
        "plan",
        system_prompt="只输出 JSON",
        tools=False,
        emit_callbacks=True,
    )

    agent = FakeAIAgent.instances[-1]
    assert callable(agent.kwargs["status_callback"])
    assert callable(agent.kwargs["tool_start_callback"])
    assert callable(agent.kwargs["tool_complete_callback"])
    assert callable(agent.kwargs["thinking_callback"])
    assert callable(agent.kwargs["reasoning_callback"])


def test_oneshot_does_not_reuse_chat_history_or_dialog_protocol(monkeypatch):
    install_fake_run_agent(monkeypatch)
    backend = HermesAgentBackend(HermesBackendConfig())
    backend.chat("hi", stream=False)
    assert backend.oneshot("plan", system_prompt="只输出 JSON", tools=False) == "hello world"

    helper = FakeAIAgent.instances[-1]
    assert helper.kwargs["ephemeral_system_prompt"] == ""
    assert helper.run_conversation_system_message == "只输出 JSON"
    assert "system_action 必须为 null" not in helper.kwargs["ephemeral_system_prompt"]
    assert helper.hermes_home_at_init is not None


def test_interrupt_forwards_to_agent(monkeypatch):
    install_fake_run_agent(monkeypatch)
    backend = HermesAgentBackend(HermesBackendConfig())
    backend.chat("hi", stream=False)
    agent = FakeAIAgent.instances[-1]
    backend.interrupt()
    assert agent.interrupted is True


def test_context_is_injected_into_system_prompt(monkeypatch):
    install_fake_run_agent(monkeypatch)
    backend = HermesAgentBackend(HermesBackendConfig())
    context = AgentContext(
        system_template="Scene template",
        character_souls=[
            CharacterSoul(
                name="Alice",
                character_setting="Alice persona",
                visual_identity="red coat",
                emotion_tags="happy=1",
            )
        ],
        long_term_memories={"Alice": ["likes tea"]},
        session_summary="Met yesterday.",
        memory_home=Path("/tmp/internal-agent-memory-home"),
    )

    backend.chat("hi", context=context, stream=False)

    agent = FakeAIAgent.instances[-1]
    assert agent.kwargs["ephemeral_system_prompt"] == ""
    system_prompt = agent.run_conversation_system_message
    assert "here 专属上下文" in system_prompt
    assert "system_action 必须为 null" in system_prompt
    assert '"system_action": null' in system_prompt
    assert system_prompt.count("here 专属上下文") == 1
    assert system_prompt.count("system_action 必须为 null") == 1
    assert "Scene template" in system_prompt
    assert "Alice persona" not in system_prompt
    assert "likes tea" not in system_prompt
    assert "Met yesterday." in system_prompt
    kwargs = FakeAIAgent.instances[-1].kwargs
    assert kwargs["skip_context_files"] is True
    assert kwargs["skip_memory"] is False
    assert kwargs["load_soul_identity"] is True
    assert FakeAIAgent.instances[-1].hermes_home_at_init == "/tmp/internal-agent-memory-home"
    assert FakeAIAgent.instances[-1].hermes_home_at_run == "/tmp/internal-agent-memory-home"


def test_life_state_is_injected_without_memory_dump(monkeypatch):
    install_fake_run_agent(monkeypatch)
    backend = HermesAgentBackend(HermesBackendConfig())
    context = AgentContext(
        selected_characters=["Alice"],
        long_term_memories={"Alice": ["likes tea"]},
        life_state="【当前生活状态】\n现在她正在：写代码和处理项目",
        memory_home=Path("/tmp/internal-agent-memory-home"),
    )

    backend.chat("你在干嘛", context=context, stream=False)

    agent = FakeAIAgent.instances[-1]
    assert agent.kwargs["ephemeral_system_prompt"] == ""
    system_prompt = agent.run_conversation_system_message
    assert "现在她正在：写代码和处理项目" in system_prompt
    assert "不要抢走用户当前话题" in system_prompt
    assert "likes tea" not in system_prompt


def test_image_input_unsupported_error_retries_as_text(monkeypatch):
    install_fake_run_agent(monkeypatch)
    install_fake_hermes_config(monkeypatch)
    FakeAIAgent.fail_next_image_call = True
    seen: list[str] = []
    backend = HermesAgentBackend(HermesBackendConfig(), status_callback=seen.append)

    backend.chat(
        [
            {"type": "text", "text": "看看这个"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ],
        stream=False,
    )

    user_messages = FakeAIAgent.instances[-1].run_conversation_user_messages
    retry_counts = FakeAIAgent.instances[-1].api_retries_seen
    assert isinstance(user_messages[0], list)
    assert isinstance(user_messages[1], str)
    assert retry_counts == [1, 3]
    assert FakeAIAgent.instances[-1]._api_max_retries == 3
    assert "看看这个" in user_messages[1]
    assert "当前 Hermes 模型/接口不支持图片输入" in user_messages[1]
    assert seen == ["当前 Hermes 模型不支持图片输入，已改为纯文本提示。"]


def test_cached_image_input_unsupported_model_uses_text_immediately(monkeypatch):
    install_fake_run_agent(monkeypatch)
    install_fake_hermes_config(monkeypatch)
    seen: list[str] = []
    backend = HermesAgentBackend(HermesBackendConfig(), status_callback=seen.append)
    image_message = [
        {"type": "text", "text": "看看这个"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]

    FakeAIAgent.fail_next_image_call = True
    backend.chat(image_message, stream=False)
    backend.chat(image_message, stream=False)

    user_messages = FakeAIAgent.instances[-1].run_conversation_user_messages
    assert isinstance(user_messages[0], list)
    assert isinstance(user_messages[1], str)
    assert isinstance(user_messages[2], str)
    assert FakeAIAgent.instances[-1].api_retries_seen == [1, 3, 3]
    assert seen == [
        "当前 Hermes 模型不支持图片输入，已改为纯文本提示。",
        "当前 Hermes 模型不支持图片输入，已改为纯文本提示。",
    ]


def test_image_input_unsupported_failed_result_retries_as_text(monkeypatch):
    install_fake_run_agent(monkeypatch)
    install_fake_hermes_config(monkeypatch)
    FakeAIAgent.return_failed_image_result = True
    backend = HermesAgentBackend(HermesBackendConfig())

    backend.chat(
        [
            {"type": "text", "text": "看看这个"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ],
        stream=False,
    )

    user_messages = FakeAIAgent.instances[-1].run_conversation_user_messages
    assert isinstance(user_messages[0], list)
    assert isinstance(user_messages[1], str)
    assert FakeAIAgent.instances[-1].api_retries_seen == [1, 3]
