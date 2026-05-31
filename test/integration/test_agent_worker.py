from __future__ import annotations

from queue import Queue
from dataclasses import dataclass

import pytest

pytest.importorskip("PySide6")

from core.runtime.workers import AgentWorker
from core.delivery.models import DeliveryResult
from core.messaging.messages import UserInputMessage
from internal_agent.agent import InternalAgentModelError


@dataclass
class _StaticRoute:
    channel: str


class _StaticChatRouter:
    def __init__(self, channel: str) -> None:
        self.channel = channel

    def route_chat_response(self):
        return _StaticRoute(self.channel)


class _RecordingDeliveryAdapters:
    def __init__(self, *, fail_external: bool = False) -> None:
        self.fail_external = fail_external
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        if self.fail_external and message.target_channel != "desktop_chat":
            return DeliveryResult(message.target_channel, "failed", "boom")
        return DeliveryResult(message.target_channel, "sent")


def test_agent_worker_streams_json_into_tts_queue(mock_app_runtime):
    mock_app_runtime.config.config.api_config.hermes_streaming = True
    mock_app_runtime.config.resolve_active_character_name.return_value = "TestChar"
    worker = AgentWorker(Queue(), Queue())
    worker.user_input_queue.put(UserInputMessage(text="hi"))
    worker.user_input_queue.put(None)

    worker.run()

    item = worker.tts_queue.get_nowait()
    assert item.name == "TestChar"
    assert item.text == "Mock reply."
    call = mock_app_runtime.agent_backend.calls[-1]
    assert call["context"] is not None
    assert call["context"].selected_characters == ["TestChar"]
    assert call["context"].character_souls[0].character_setting == "You are a test character."
    assert "私有运行状态" in call["context"].life_state
    assert mock_app_runtime.agent_backend.oneshot_calls == []


def test_agent_worker_leaves_session_persistence_to_agent_backend(mock_app_runtime):
    mock_app_runtime.config.config.api_config.hermes_streaming = True
    mock_app_runtime.config.resolve_active_character_name.return_value = "TestChar"
    worker = AgentWorker(Queue(), Queue())
    worker.user_input_queue.put(UserInputMessage(text="刚才我们聊到了炒饭"))
    worker.user_input_queue.put(None)

    worker.run()

    assert worker.memory_store.read_session_summary("default") == ""
    assert mock_app_runtime.agent_backend.calls[-1]["context"].memory_home == (
        worker.memory_store.agent_home("TestChar")
    )


def test_agent_worker_routes_chat_reply_to_selected_external_channel(mock_app_runtime):
    mock_app_runtime.delivery_router = _StaticChatRouter("feishu")
    mock_app_runtime.delivery_adapters = _RecordingDeliveryAdapters()
    worker = AgentWorker(Queue(), Queue())
    worker.user_input_queue.put(UserInputMessage(text="hi"))
    worker.user_input_queue.put(None)

    worker.run()

    assert worker.tts_queue.empty()
    sent = mock_app_runtime.delivery_adapters.messages
    assert len(sent) == 1
    assert sent[0].target_channel == "feishu"
    assert sent[0].dialog.text == "Mock reply."


def test_agent_worker_falls_back_to_desktop_when_external_chat_delivery_fails(mock_app_runtime):
    mock_app_runtime.delivery_router = _StaticChatRouter("telegram")
    mock_app_runtime.delivery_adapters = _RecordingDeliveryAdapters(fail_external=True)
    worker = AgentWorker(Queue(), Queue())
    worker.user_input_queue.put(UserInputMessage(text="hi"))
    worker.user_input_queue.put(None)

    worker.run()

    assert worker.tts_queue.empty()
    sent = mock_app_runtime.delivery_adapters.messages
    assert [message.target_channel for message in sent] == ["telegram", "desktop_chat"]


def test_agent_worker_passes_image_references_as_multimodal_content(mock_app_runtime, tmp_path):
    image = tmp_path / "screen.png"
    image.write_bytes(b"fake")
    worker = AgentWorker(Queue(), Queue())
    worker.user_input_queue.put(UserInputMessage(text=f"看看这个\n[图片: {image}]"))
    worker.user_input_queue.put(None)

    worker.run()

    call = mock_app_runtime.agent_backend.calls[-1]
    assert isinstance(call["user_text"], list)
    assert call["user_text"][0] == {"type": "text", "text": "看看这个"}
    assert call["user_text"][1]["type"] == "image_url"


def test_agent_worker_emits_text_reply_when_hermes_fails(mock_app_runtime):
    def _raise(*_args, **_kwargs):
        raise RuntimeError("No endpoints found that support image input")

    mock_app_runtime.agent_backend.chat = _raise
    worker = AgentWorker(Queue(), Queue())
    worker.user_input_queue.put(UserInputMessage(text="看看这个"))
    worker.user_input_queue.put(None)

    worker.run()

    item = worker.tts_queue.get_nowait()
    assert item.name == "TestChar"
    assert "没有处理成功" in item.text
    assert item.emotion == "sad"


def test_agent_worker_reports_internal_agent_model_errors(mock_app_runtime):
    def _raise(*_args, **_kwargs):
        raise InternalAgentModelError("Internal Agent 模型不可用：\"step-3.6\"。")

    mock_app_runtime.agent_backend.chat = _raise
    worker = AgentWorker(Queue(), Queue())
    worker.user_input_queue.put(UserInputMessage(text="你好"))
    worker.user_input_queue.put(None)

    worker.run()

    item = worker.tts_queue.get_nowait()
    assert item.name == "TestChar"
    assert "step-3.6" in item.text
    assert "模型不可用" in item.text
    assert item.emotion == "sad"


def test_agent_worker_uses_active_character_context(mock_app_runtime, make_character=None):
    mock_app_runtime.config.config.characters.append(
        mock_app_runtime.config.config.characters[0].model_copy(
            update={"name": "OtherChar", "character_setting": "Other persona."}
        )
    )
    mock_app_runtime.config.set_active_character_name("OtherChar")
    worker = AgentWorker(Queue(), Queue())
    worker.user_input_queue.put(UserInputMessage(text="hi"))
    worker.user_input_queue.put(None)

    worker.run()

    call = mock_app_runtime.agent_backend.calls[-1]
    assert call["context"].selected_characters == ["OtherChar"]
    assert call["context"].character_souls[0].character_setting == "Other persona."


def test_agent_worker_records_life_promise_in_memory(mock_app_runtime):
    mock_app_runtime.config.config.api_config.hermes_streaming = True
    worker = AgentWorker(Queue(), Queue())
    worker.user_input_queue.put(UserInputMessage(text="今晚记得陪我聊一会儿"))
    worker.user_input_queue.put(None)

    worker.run()

    memories = worker.memory_store.read_character_memories("TestChar")
    assert memories == ["用户近期约定/请求：今晚记得陪我聊一会儿"]
    call = mock_app_runtime.agent_backend.calls[-1]
    assert "recent_user_promises=" in call["context"].life_state


def test_agent_worker_falls_back_when_hermes_returns_plain_text(mock_app_runtime):
    mock_app_runtime.agent_backend.response = "现在有两个角色：here_system 和角色A。"
    mock_app_runtime.config.resolve_active_character_name.return_value = "TestChar"
    worker = AgentWorker(Queue(), Queue())
    worker.user_input_queue.put(UserInputMessage(text="现在有哪些角色"))
    worker.user_input_queue.put(None)

    worker.run()

    item = worker.tts_queue.get_nowait()
    assert item.name == "TestChar"
    assert item.text == "现在有两个角色：here_system 和角色A。"
    assert item.emotion == "neutral"


def test_agent_worker_renames_placeholder_character_from_system_action(mock_app_runtime):
    mock_app_runtime.config.config.characters[0].name = "角色A"
    mock_app_runtime.config.resolve_active_character_name.return_value = "角色A"
    mock_app_runtime.config.rename_character.return_value = "小澪"
    mock_app_runtime.agent_backend.response = (
        '[{"character_name":"角色A","speech":"好呀，以后我就叫小澪。","emotion":"happy",'
        '"system_action":{"type":"rename_active_character","name":"小澪"}}]'
    )
    worker = AgentWorker(Queue(), Queue())
    worker.memory_store.append_character_memory("角色A", "第一次见面")
    worker.user_input_queue.put(UserInputMessage(text="以后你就叫小澪吧"))
    worker.user_input_queue.put(None)

    worker.run()

    item = worker.tts_queue.get_nowait()
    assert item.name == "小澪"
    assert item.text == "好呀，以后我就叫小澪。"
    mock_app_runtime.config.rename_character.assert_called_once_with("角色A", "小澪")
    assert not worker.memory_store.agent_home("角色A").exists()
    assert worker.memory_store.read_character_memories("小澪") == ["第一次见面"]


def test_agent_worker_renames_placeholder_character_from_system_action(mock_app_runtime):
    mock_app_runtime.config.config.characters[0].name = "角色A"
    mock_app_runtime.config.config.system_config.active_character_name = "角色A"
    mock_app_runtime.agent_backend.response = (
        '[{"character_name":"角色A","speech":"好呀，以后我就叫小澪。","emotion":"happy",'
        '"system_action":{"type":"rename_active_character","name":"小澪"}}]'
    )
    mock_app_runtime.agent_memory_store.append_character_memory("角色A", "remembers the user")
    worker = AgentWorker(Queue(), Queue())
    worker.user_input_queue.put(UserInputMessage(text="以后你叫小澪"))
    worker.user_input_queue.put(None)

    worker.run()

    item = worker.tts_queue.get_nowait()
    assert item.name == "小澪"
    assert mock_app_runtime.active_character.name == "小澪"
    assert mock_app_runtime.config.config.characters[0].name == "小澪"
    assert mock_app_runtime.agent_memory_store.read_character_memories("小澪") == ["remembers the user"]
    assert not mock_app_runtime.agent_memory_store.agent_home("角色A").exists()
