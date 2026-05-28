"""
应用运行期共享上下文：在 main 中 set_app_runtime 后，各模块通过 get_app_runtime() 访问
配置、管理器、队列、繁简转换、TTS 入 UI 队列等。Handler 不依赖 worker 类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from PySide6.QtCore import QObject, Signal


@dataclass
class UiPlaybackBridge:
    """由 UIWorker 在 init_channel 后写入，供 UI 消息 handler 做对话音轨与跳过。"""

    task_done_requested: Any = None
    dialog_channel: Any = None
    current_audio_path: Any = None


class ActiveCharacterState(QObject):
    changed = Signal(str)

    def __init__(self, config_manager: Any, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._config_manager = config_manager

    @property
    def name(self) -> str:
        return self._config_manager.resolve_active_character_name()

    def set_name(self, name: str, *, persist: bool = True) -> str:
        if persist:
            resolved = self._config_manager.set_active_character_name(name)
        else:
            resolved = str(name or "").strip() or self._config_manager.resolve_active_character_name()
        self.changed.emit(resolved)
        return resolved


@dataclass
class AppRuntime:
    config: Any  # ConfigManager
    ui_update_manager: Any  # UIUpdateManager
    agent_backend: Any  # HermesAgentBackend
    tts_manager: Optional[Any]  # TTSManager | None
    t2i_manager: Optional[Any]  # T2IManager | None
    bgm_list: List[Any]
    user_input_queue: Any
    tts_queue: Any
    audio_path_queue: Any
    text_processor: Any  # TextProcessor
    opencc: Any  # OpenCC
    ui_playback: UiPlaybackBridge = field(default_factory=UiPlaybackBridge)
    active_character: Optional[ActiveCharacterState] = None
    life_engine: Optional[Any] = None
    life_scheduler: Optional[Any] = None
    contact_engine: Optional[Any] = None
    proactive_contact_scheduler: Optional[Any] = None
    selfie_service: Optional[Any] = None
    selfie_t2i_manager: Optional[Any] = None
    delivery_router: Optional[Any] = None
    delivery_adapters: Optional[Any] = None
    chat_platform_bridge: Optional[Any] = None


_runtime: Optional[AppRuntime] = None


def set_app_runtime(rt: AppRuntime) -> None:
    global _runtime
    _runtime = rt


def get_app_runtime() -> AppRuntime:
    if _runtime is None:
        raise RuntimeError("尚未调用 set_app_runtime：请在创建 Worker 之前完成应用上下文注册")
    return _runtime


def try_get_app_runtime() -> Optional[AppRuntime]:
    return _runtime


def tts_emit_to_ui_queue(
    character_name: str,
    speech: str,
    asset_id: str,
    audio_path: str,
    *,
    is_system_message: bool = False,
    effect: str = "",
    emotion: str = "neutral",
) -> None:
    """
    与 TTSWorker.put_data 相同：将一条 TTS 结果送入 UI 队列，并对 Agent 侧 tts_queue 执行 task_done。
    """
    from core.messaging.messages import TTSOutputMessage

    rt = get_app_runtime()
    audio_path = audio_path or ""
    out = TTSOutputMessage(
        audio_path=audio_path,
        name=character_name,
        asset_id=asset_id,
        text=speech,
        emotion=emotion or "neutral",
        is_system_message=is_system_message,
        effect=effect,
    )
    rt.audio_path_queue.put(out)
    rt.tts_queue.task_done()


def tts_item_done_only() -> None:
    """仅消费 Agent->TTS 队列的一条任务（不产出 UI 包），如思维链丢弃。"""
    get_app_runtime().tts_queue.task_done()
