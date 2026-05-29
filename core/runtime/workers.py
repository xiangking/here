import traceback
from html import escape
from queue import Queue
from pathlib import Path
from typing import Optional

from infrastructure.logging.timing import tracker

from PySide6.QtCore import QThread

import threading
import pygame
import sys
current_script = Path(__file__).resolve()
project_root = current_script.parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 导入 ConfigManager 和 Pydantic 消息模型
from services.config.config_manager import ConfigManager
from services.config.config_manager import SYSTEM_CHARACTER_NAME, is_placeholder_character_name
from core.messaging.messages import UserInputMessage, AgentDialogMessage, TTSOutputMessage
from core.runtime.app_runtime import get_app_runtime, try_get_app_runtime, tts_emit_to_ui_queue
from core.messaging.stream_parser import AgentResponseStreamParser
from core.handlers.handler_registry import default_tts_handler_chain, default_ui_output_handler_chain
from internal_agent.context import AgentMemoryStore, build_agent_context
from core.agent.multimodal import build_hermes_user_message
from core.delivery.models import DeliveryMessage
from core.life import LifeEngine
try:
    from internal_agent.agent import InternalAgentModelError
except Exception:  # pragma: no cover - defensive for unusual import states
    InternalAgentModelError = RuntimeError


def _dialog_html(name: str, text: str, color: str) -> str:
    safe_name = escape(name or "")
    safe_text = escape(text or "").replace("\n", "<br>")
    safe_color = color if str(color or "").startswith("#") else "white"
    return (
        f"<p style='line-height: 135%; letter-spacing: 2px;'>"
        f"<b style='color:{safe_color};'>{safe_name}</b>：</p>"
        f"<div style='line-height: 135%; letter-spacing: 2px;'>{safe_text}</div>"
    )
# --- 抽象 Worker 接口定义 ---

class BaseWorker(QThread):
    """
    Worker 抽象基类，定义了统一 QThread 基础。
    """

    def __init__(self, *args, **kwargs):
        # 确保 QThread 初始化
        QThread.__init__(self, *args, **kwargs)
        self.running = True

    def run(self):
        """Worker 线程的主执行逻辑"""
        pass

    def stop(self):
        """停止 Worker 线程并等待结束（最多 3 秒）。"""
        self.running = False
        if not self.wait(3000):
            print(f"警告: {type(self).__name__} 线程未在 3 秒内退出，强制终止")
            self.terminate()
            self.wait()

def getCharacter(name: str):
    rt = try_get_app_runtime()
    if rt is not None:
        return rt.config.get_character_by_name(name)
    return ConfigManager().get_character_by_name(name)


class AgentWorker(BaseWorker):
    def __init__(
        self,
        input_queue: Queue[UserInputMessage],
        output_queue: Queue[AgentDialogMessage],
        parent=None,
    ):
        super().__init__(parent)
        rt = get_app_runtime()
        self.ui_update_manager = rt.ui_update_manager
        self.user_input_queue = input_queue
        self.tts_queue = output_queue
        self.memory_store = getattr(rt, "agent_memory_store", None) or AgentMemoryStore()
        self.life_engine = getattr(rt, "life_engine", None) or LifeEngine(self.memory_store)

    @property
    def agent_backend(self):
        return get_app_runtime().agent_backend

    def _handle_system_action(
        self,
        agent_dialog: AgentDialogMessage,
        *,
        active_character: str,
        user_text: str,
    ) -> AgentDialogMessage:
        action = agent_dialog.system_action or {}
        if not isinstance(action, dict):
            return agent_dialog
        action_type = str(action.get("type") or "").strip()
        if action_type != "rename_active_character":
            return agent_dialog
        old_name = str(active_character or "").strip()
        confirmed_name = str(action.get("name") or action.get("new_name") or "").strip()
        if not old_name or not confirmed_name or old_name == confirmed_name:
            return agent_dialog
        if old_name == SYSTEM_CHARACTER_NAME or not is_placeholder_character_name(old_name):
            print(f"AgentWorker: 忽略角色命名动作（当前角色不允许自动改名）: {old_name} -> {confirmed_name}")
            return agent_dialog
        if confirmed_name not in (user_text or "") and confirmed_name not in (agent_dialog.text or ""):
            print(f"AgentWorker: 忽略角色命名动作（名字未出现在本轮对话中）: {old_name} -> {confirmed_name}")
            return agent_dialog
        rt = get_app_runtime()
        before_home = self.memory_store.agent_home(old_name)
        renamed = rt.config.rename_character(old_name, confirmed_name)
        if renamed != confirmed_name:
            print(f"AgentWorker: 角色命名未执行: {old_name} -> {confirmed_name}")
            return agent_dialog
        try:
            if before_home.exists():
                self.memory_store.rename_character(old_name, confirmed_name)
        except Exception as exc:
            print(f"AgentWorker: 迁移角色记忆目录失败: {exc}")
        if rt.active_character is not None:
            rt.active_character.set_name(confirmed_name, persist=False)
        if hasattr(self.agent_backend, "reset_session"):
            self.agent_backend.reset_session()
        self.ui_update_manager.post_notification(f"已将 {old_name} 命名为 {confirmed_name}")
        return agent_dialog.model_copy(update={"name": confirmed_name})

    def _emit_agent_dialog(self, agent_dialog: AgentDialogMessage, *, active_character: str) -> None:
        rt = get_app_runtime()
        router = getattr(rt, "delivery_router", None)
        adapters = getattr(rt, "delivery_adapters", None)
        route_chat = getattr(router, "route_chat_response", None)
        if router is None or adapters is None or not callable(route_chat):
            self.tts_queue.put(agent_dialog)
            return
        try:
            route = route_chat()
            channel = str(getattr(route, "channel", "desktop_chat") or "desktop_chat")
            result = adapters.send(
                DeliveryMessage(
                    dialog=agent_dialog,
                    character_name=active_character or agent_dialog.name,
                    target_channel=channel,
                )
            )
            if str(getattr(result, "status", "") or "") == "sent":
                return
            if channel != "desktop_chat":
                reason = str(getattr(result, "reason", "") or "unknown")
                self.ui_update_manager.post_notification(f"外部渠道发送失败，已回到桌面：{reason}")
                adapters.send(
                    DeliveryMessage(
                        dialog=agent_dialog,
                        character_name=active_character or agent_dialog.name,
                        target_channel="desktop_chat",
                    )
                )
                return
        except Exception as exc:
            self.ui_update_manager.post_notification(f"外部渠道发送失败，已回到桌面：{exc}")
        self.tts_queue.put(agent_dialog)

    def _error_message_for_exception(self, exc: Exception) -> str:
        if isinstance(exc, InternalAgentModelError):
            return str(exc)
        return (
            "这次消息没有处理成功。如果你发了图片，可能是当前 Hermes 模型或接口不支持图片输入；"
            "你可以换成支持视觉的模型，或者先用文字描述一下图片。"
        )

    def run(self):
        while self.running:
            try:
                # 从用户输入队列中获取任务，阻塞等待
                # 期望获取的是 UserInputMessage 实例
                message: UserInputMessage = self.user_input_queue.get()
                if message is None:
                    break

                print(f"AgentWorker: 开始处理消息: {message.text}")
                agent_backend = self.agent_backend
                proactive_scheduler = getattr(get_app_runtime(), "proactive_contact_scheduler", None)
                if proactive_scheduler is not None:
                    proactive_scheduler.note_user_message()
                agent_user_message = build_hermes_user_message(message.text)
                tracker.start_cross("e2e")
                self.ui_update_manager.post_notification("发送成功，正在等待回复中...")
                active_character = get_app_runtime().active_character.name
                active_config = getCharacter(active_character)
                active_color = getattr(active_config, "color", "#84C2D5") if active_config else "#84C2D5"
                self.ui_update_manager.post_dialog(
                    _dialog_html(active_character, "正在输入……", active_color)
                )
                life_state = ""
                if active_config is not None:
                    try:
                        self.life_engine.observe_user_message(
                            active_config,
                            message.text,
                            agent_backend=agent_backend,
                            allow_llm_generate=False,
                        )
                        life_state = self.life_engine.current_life_state(
                            active_config,
                            agent_backend=agent_backend,
                            allow_llm_generate=False,
                        )
                    except Exception as exc:
                        print(f"AgentWorker: 生活状态更新失败，继续普通聊天: {exc}")

                # 将用户消息添加到历史 (以 UI 格式和 Agent 上下文分别处理)
                safe_user_text = escape(message.text or "")
                formatted_user_message = f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'><b style='color:white;'>你</b>: {safe_user_text}</p>"
                self.ui_update_manager.chat_history.append(formatted_user_message)

                # 统一获取响应流
                is_streaming = bool(get_app_runtime().config.config.api_config.hermes_streaming)
                agent_context = build_agent_context(
                    config_manager=get_app_runtime().config,
                    memory_store=self.memory_store,
                    system_template=getattr(agent_backend, "system_prompt", ""),
                    session_id="default",
                    selected_character_names=[active_character],
                    life_state=life_state,
                )
                with tracker.track("Hermes chat total"):
                    raw_response = agent_backend.chat(
                        agent_user_message,
                        context=agent_context,
                        stream=is_streaming,
                    )

                # 如果不是流式，将其包装成一个列表，使下文的 for 循环可以统一处理
                if is_streaming:
                    response_stream = raw_response
                else:
                    # 包装成可迭代对象，模拟流式的一个 chunk
                    response_stream = [raw_response]

                parser = AgentResponseStreamParser()
                emitted_dialog = False

                with tracker.track("Hermes stream parse"):
                    for chunk in response_stream:
                        chunk_message = (
                            chunk if isinstance(chunk, str) else str(chunk) if chunk is not None else ""
                        )
                        for agent_dialog in parser.feed(chunk_message):
                            agent_dialog = self._handle_system_action(
                                agent_dialog,
                                active_character=active_character,
                                user_text=message.text,
                            )
                            emitted_dialog = True
                            self._emit_agent_dialog(agent_dialog, active_character=active_character)
                    for agent_dialog in parser.flush():
                        agent_dialog = self._handle_system_action(
                            agent_dialog,
                            active_character=active_character,
                            user_text=message.text,
                        )
                        emitted_dialog = True
                        self._emit_agent_dialog(agent_dialog, active_character=active_character)

                if not emitted_dialog:
                    fallback_text = (parser.accumulated_text or "").strip()
                    recovered_messages = list(parser.recover_messages(fallback_text))
                    for agent_dialog in recovered_messages:
                        agent_dialog = self._handle_system_action(
                            agent_dialog,
                            active_character=active_character,
                            user_text=message.text,
                        )
                        emitted_dialog = True
                        self._emit_agent_dialog(agent_dialog, active_character=active_character)
                    if emitted_dialog:
                        self.user_input_queue.task_done()
                        continue
                    if not fallback_text:
                        fallback_text = "刚才没有拿到有效回复，我们再试一次。"
                    self._emit_agent_dialog(
                        AgentDialogMessage(
                            name=active_character,
                            text=fallback_text,
                            emotion="neutral",
                        ),
                        active_character=active_character,
                    )

                self.user_input_queue.task_done()

            except Exception as e:
                print(f"AgentWorker: 任务处理失败: {e}")
                traceback.print_exc()
                try:
                    active_character = (
                        get_app_runtime().active_character.name
                        if get_app_runtime().active_character is not None
                        else SYSTEM_CHARACTER_NAME
                    )
                except Exception:
                    active_character = SYSTEM_CHARACTER_NAME
                self._emit_agent_dialog(
                    AgentDialogMessage(
                        name=active_character,
                        text=self._error_message_for_exception(e),
                        emotion="sad",
                    ),
                    active_character=active_character,
                )
                self.user_input_queue.task_done()

    def stop(self):
        """停止 Worker 线程并等待结束。"""
        self.running = False
        try:
            self.agent_backend.interrupt()
        except Exception:
            pass
        self.user_input_queue.put(None)  # 解锁 get() 阻塞
        if not self.wait(3000):
            print(f"警告: AgentWorker 线程未在 3 秒内退出，强制终止")
            self.terminate()
            self.wait()


class TTSWorker(BaseWorker):
    def __init__(
        self,
        input_queue: Queue[AgentDialogMessage],
        output_queue: Queue[TTSOutputMessage],
        parent=None,
    ):
        super().__init__(parent)
        self.tts_queue = input_queue
        self.audio_path_queue = output_queue
        self.tts_message_dispatcher = default_tts_handler_chain()
        self.tts_message_dispatcher.init_handlers()

    def put_data(self, character_name: str, speech: str, sprite: str, audio_path, is_system_message: bool = False, effect: str = ""):
        """与 handler 中 tts_emit_to_ui_queue 一致，供本 worker 异常路径使用。"""
        tts_emit_to_ui_queue(
            character_name, speech, sprite, audio_path or "",
            is_system_message=is_system_message, effect=effect,
        )

    def run(self):
        while self.running:
            item: Optional[AgentDialogMessage] = None
            try:
                item = self.tts_queue.get()
                if item is None:
                    break
                with tracker.track("TTS dispatch"):
                    self.tts_message_dispatcher.dispatch(item)
            except Exception as e:
                print(f"TTSWorker: 任务处理失败: {e}")
                traceback.print_exc()
                if item is not None:
                    self.put_data(
                        get_app_runtime().opencc.convert(item.name),
                        item.text,
                        str(item.asset_id) if item.asset_id is not None else "-1",
                        "",
                        is_system_message=False,
                        effect=item.effect,
                    )

    def stop(self):
        """停止 Worker 线程并等待结束。"""
        self.running = False
        self.tts_queue.put(None)
        if not self.wait(3000):
            print(f"警告: TTSWorker 线程未在 3 秒内退出，强制终止")
            self.terminate()
            self.wait()

class UIWorker(QThread):
    def __init__(self, input_queue: Queue[TTSOutputMessage], parent=None):
        super().__init__(parent)
        rt = get_app_runtime()
        self.ui_update_manager = rt.ui_update_manager
        self.audio_path_queue = input_queue
        self.running = True
        self.task_done_requested = threading.Event() # 使用 Event 对象作为跳过标志
        self.current_audio_path = None
        self.DIALOG_CHANNEL_ID = 7
        self.ui_out_dispatcher = default_ui_output_handler_chain()

        self.init_channel()
        br = get_app_runtime().ui_playback
        br.task_done_requested = self.task_done_requested
        br.dialog_channel = self.dialog_channel
        self.ui_out_dispatcher.init_handlers()

    def init_channel(self):
        # --- 新增 Mixer 初始化和通道获取 ---
        try:
            pygame.mixer.init()
            # 确保有足够的通道，此处至少需要 DIALOG_CHANNEL_ID + 1 个
            if pygame.mixer.get_num_channels() < self.DIALOG_CHANNEL_ID + 1:
                pygame.mixer.set_num_channels(self.DIALOG_CHANNEL_ID + 1)

            # 获取对话专用通道
            self.dialog_channel: pygame.mixer.Channel = pygame.mixer.Channel(self.DIALOG_CHANNEL_ID)
            print(f"UIWorker: 对话播放通道初始化成功，使用通道 {self.DIALOG_CHANNEL_ID}")

        except Exception as e:
            print(f"UIWorker: Pygame Mixer 初始化或通道获取失败: {e}")
            self.dialog_channel = None # 如果失败，则禁用音频播放
        # --- 结束新增 ---

    def skip_speech(self):
        """跳过当前对话"""
        if self.audio_path_queue.empty():
            return
        if self.dialog_channel and self.dialog_channel.get_busy():
            self.dialog_channel.stop()

        self.current_audio_path = None
        get_app_runtime().ui_playback.current_audio_path = None

        self.task_done_requested.set()

    def run(self):
        while self.running:
            try:
                self.task_done_requested.clear()
                output_data: TTSOutputMessage = self.audio_path_queue.get()
                if output_data is None:
                    break
                self.ui_out_dispatcher.dispatch(output_data)
            except Exception as e:
                traceback.print_exc()
                print(f"UIWorker: 任务处理失败: {e}")
                try:
                    self.ui_update_manager.post_notification(f"界面更新失败: {e}")
                except Exception:
                    pass
                if not self.task_done_requested.is_set():
                    _text = getattr(output_data, "text", "") or ""
                    wait = max(len(_text) / 10, 0.3) if _text else 0.3
                    self.task_done_requested.wait(timeout=wait)
                self.audio_path_queue.task_done()

    def stop(self):
        """停止 UIWorker 线程并等待结束。"""
        self.running = False
        self.task_done_requested.set()
        self.audio_path_queue.put(None)
        if not self.wait(3000):
            print(f"警告: UIWorker 线程未在 3 秒内退出，强制终止")
            self.terminate()
            self.wait()
