"""Chat history state and helpers used by main and UI workers."""

from __future__ import annotations

import json
import re
from typing import Any

from infrastructure.paths import get_app_paths

from core.messaging.dialog_tokens import is_option_history_name, is_option_history_plain
from core.messaging.messages import TTSOutputMessage

CHAT_HISTORY_PATH = str(get_app_paths().chat_history_dir)

chat_history: list[Any] = []


def get_history() -> list[Any]:
    """获取聊天历史记录。"""
    return chat_history


def getHistory() -> list[Any]:
    """兼容旧名称。"""
    return get_history()


def save_chat_history(file_path: str, history: Any) -> None:
    """旧对话后端历史已移除；此函数保留给 UI 调用点做空操作。"""


def load_chat_history(file_path: str) -> Any:
    return []


def clear_chat_history(history_file: str, ui_queue: Any, agent_backend: Any) -> None:
    from services.i18n import tr

    chat_history.clear()
    if hasattr(agent_backend, "reset_session"):
        agent_backend.reset_session()
    ui_queue.put(
        TTSOutputMessage(
            audio_path="",
            character_name=tr("main.system_name"),
            speech=tr("main.history_cleared"),
            sprite="-1",
            is_system_message=False,
        )
    )


def copy_chat_history_to_clipboard() -> None:
    """将聊天记录复制到系统剪贴板，去除 HTML 标签并格式化为纯文本。"""
    try:
        from PySide6.QtWidgets import QApplication

        text = "\n".join(re.sub(r"<[^>]+>", "", str(x)) for x in chat_history)
        QApplication.clipboard().setText(text)
    except Exception:
        pass


def replay_history_entry(window: Any, history_entry: str) -> None:
    """回放一条历史记录。若为选项则重新显示选项。"""
    if not history_entry:
        return

    plain_text = re.sub(r"<[^>]+>", "", history_entry).strip()
    name = ""
    content = plain_text
    if "：" in plain_text:
        name, content = plain_text.split("：", 1)
    elif ":" in plain_text:
        name, content = plain_text.split(":", 1)

    if is_option_history_name(name):
        option_list = [item.strip() for item in content.split("/") if item.strip()]
        window.setOptions(option_list)
    else:
        window.setDisplayWords(history_entry)


def is_option_history_entry(history_entry: str) -> bool:
    if not isinstance(history_entry, str):
        return False
    plain_text = re.sub(r"<[^>]+>", "", history_entry).strip()
    return is_option_history_plain(plain_text)


def is_user_history_entry(history_entry: str) -> bool:
    if not isinstance(history_entry, str):
        return False
    return "你</b>" in history_entry or "你</b>：" in history_entry or "你</b>:" in history_entry


def extract_valid_dialog_from_messages(messages: list) -> list:
    """从历史消息中提取最后一条可用 assistant dialog。"""
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return data
        except Exception:
            continue
    return []


def revert_chat_history(user_index: int, agent_backend: Any, hist: list, window: Any) -> None:
    """按 user_index 回溯到该用户消息之前的上一条 assistant 记录。"""
    if user_index < 0:
        return

    current_user_idx = -1
    user_history_pos = -1
    for idx, entry in enumerate(hist):
        if is_user_history_entry(entry):
            current_user_idx += 1
            if current_user_idx == user_index:
                user_history_pos = idx
                break

    if user_history_pos == -1:
        return

    target_index = -1
    for idx in range(user_history_pos - 1, -1, -1):
        if not is_user_history_entry(hist[idx]):
            target_index = idx
            break

    if target_index < 0:
        return

    del hist[target_index + 1:]

    if hasattr(agent_backend, "reset_session"):
        agent_backend.reset_session()

    if hist:
        replay_history_entry(window, hist[-1])


def save_bg(bg_path: str | None, bgm_path: str | None) -> None:
    from services.config.config_manager import ConfigManager

    config = ConfigManager()
    config.config.system_config.background_path = bg_path
    config.config.system_config.bgm_path = bgm_path
    config.save_system_config()
