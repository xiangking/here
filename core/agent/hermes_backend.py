"""Project-facing wrapper around NousResearch hermes-agent.

Here keeps the desktop shell, TTS, sprites and JSON dialogue parser. All
reasoning, planning, memory, todo state and tool loops are delegated to
``run_agent.AIAgent``.
"""

from __future__ import annotations

import queue
import threading
import os
import tempfile
from contextlib import contextmanager
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from internal_agent.context import AgentContext, CharacterSoul

DEFAULT_DISABLED_TOOLSETS = ("telegram", "discord", "slack", "matrix", "messaging")
_HERMES_HOME_LOCK = threading.RLock()
_IMAGE_UNSUPPORTED_CACHE_LOCK = threading.RLock()
_IMAGE_UNSUPPORTED_MODEL_KEYS: set[tuple[str, str, str]] = set()
_MODEL_CONFIG_HERMES_HOME = os.environ.get("HERMES_HOME")

DIALOG_PROTOCOL = """
最终 assistant 正文必须只输出 Here 角色对话 JSON，不要把工具状态、计划、记忆日志或调试信息写入正文。
格式为 JSON 数组；每个角色元素必须包含 character_name、speech、emotion、system_action，可选 effect。
emotion 必须使用当前角色已有状态名，优先从 neutral、happy、thinking、surprised、sad、angry 中选择；不要输出立绘编号。
背景、BGM、CG 等系统资源如需编号，使用 asset_id；普通角色对话不要使用 asset_id。
普通对话时 system_action 必须为 null，不要省略。
示例：
[
  {"character_name": "角色名", "speech": "要说的话", "emotion": "neutral", "system_action": null}
]
当且仅当用户明确要求给当前角色取名/改名，并且当前角色在 speech 中接受这个名字时，可以在同一个角色 JSON 中附加：
{"system_action": {"type": "rename_active_character", "name": "名字"}}
如果当前角色询问某个名字是否可以，用户用“好 / 好的 / 可以 / 就这样 / 你喜欢就好”等方式确认，也必须输出 rename_active_character。
不要在普通寒暄、昵称玩笑、提到他人名字、工具状态或计划中输出 system_action。
如果需要说明工具执行状态，请通过 status/tool callback，不要进入角色台词。
长期身份、稳定偏好和关系事实写入 memory；具体的过往聊天内容保存在当前角色的 session 数据库中。
当用户询问“上次聊了什么”、追问过去对话、或当前问题明显需要跨重启回忆时，先使用 session_search 检索当前角色的过往会话，再用角色口吻回答。
""".strip()


@contextmanager
def _temporary_hermes_home(path: str | Path | None):
    with _HERMES_HOME_LOCK:
        if not path:
            yield
            return
        old_home = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(path)
        try:
            yield
        finally:
            if old_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = old_home


@contextmanager
def _hermes_model_config_home():
    """Read model settings from the launch profile, not a temporary memory home."""
    with _HERMES_HOME_LOCK:
        old_home = os.environ.get("HERMES_HOME")
        if _MODEL_CONFIG_HERMES_HOME:
            os.environ["HERMES_HOME"] = _MODEL_CONFIG_HERMES_HOME
        else:
            os.environ.pop("HERMES_HOME", None)
        try:
            yield
        finally:
            if old_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = old_home


@dataclass(frozen=True)
class HermesBackendConfig:
    max_iterations: int = 90
    enabled_toolsets: list[str] | None = None
    disabled_toolsets: list[str] = field(
        default_factory=lambda: list(DEFAULT_DISABLED_TOOLSETS)
    )
    reasoning_config: dict[str, Any] = field(default_factory=dict)
    max_tokens: int | None = None
    stream: bool = True
    use_internal_memory: bool = True
    disable_hermes_native_memory: bool = True


def _local_hermes_model_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        with _hermes_model_config_home():
            model_cfg = (load_config().get("model") or {})
        if isinstance(model_cfg, dict):
            return {
                "provider": str(model_cfg.get("provider") or "").strip(),
                "model": str(model_cfg.get("default") or model_cfg.get("model") or "").strip(),
                "base_url": str(model_cfg.get("base_url") or "").strip(),
            }
    except Exception:
        pass
    return {}


def _hermes_agent_class() -> Any:
    # ``run_agent`` loads Hermes' .env at import time using the active
    # HERMES_HOME. Import it against the launch/model config home before this
    # backend temporarily points HERMES_HOME at a per-character memory folder.
    with _hermes_model_config_home():
        from run_agent import AIAgent

    return AIAgent


def _image_support_cache_key(model_cfg: dict[str, Any]) -> tuple[str, str, str] | None:
    provider = str(model_cfg.get("provider") or "").strip().lower()
    model = str(model_cfg.get("model") or "").strip().lower()
    base_url = str(model_cfg.get("base_url") or "").strip().lower().rstrip("/")
    if not (provider or model or base_url):
        return None
    return (provider, model, base_url)


def _is_image_unsupported_cached(key: tuple[str, str, str] | None) -> bool:
    if key is None:
        return False
    with _IMAGE_UNSUPPORTED_CACHE_LOCK:
        return key in _IMAGE_UNSUPPORTED_MODEL_KEYS


def _mark_image_unsupported(key: tuple[str, str, str] | None) -> None:
    if key is None:
        return
    with _IMAGE_UNSUPPORTED_CACHE_LOCK:
        _IMAGE_UNSUPPORTED_MODEL_KEYS.add(key)


def _content_has_image_parts(value: Any) -> bool:
    if isinstance(value, list):
        return any(_content_has_image_parts(item) for item in value)
    if isinstance(value, dict):
        if value.get("type") in {"image_url", "input_image", "image"}:
            return True
        return any(_content_has_image_parts(item) for item in value.values())
    return False


def _text_from_multimodal_content(value: Any) -> str:
    if not isinstance(value, list):
        return str(value or "")
    lines: list[str] = []
    image_count = 0
    for part in value:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text = str(part.get("text") or "").strip()
            if text:
                lines.append(text)
        elif part.get("type") in {"image_url", "input_image", "image"}:
            image_count += 1
    if image_count:
        lines.append(
            f"【图片附件】用户发送了 {image_count} 张图片，但当前 Hermes 模型/接口不支持图片输入；"
            "请诚实告知用户需要切换到支持视觉的模型后才能查看图片内容。"
        )
    return "\n".join(lines).strip()


def _looks_like_image_input_unsupported(exc: BaseException) -> bool:
    pieces: list[str] = [str(exc)]
    for attr in ("body", "message", "response", "details"):
        try:
            value = getattr(exc, attr, None)
        except Exception:
            value = None
        if value:
            pieces.append(str(value))
    text = "\n".join(pieces).lower()
    phrases = (
        "no endpoints found that support image input",
        "only 'text' content type is supported",
        "only text content type is supported",
        "image_url is not supported",
        "image content is not supported",
        "image input is not supported",
        "images are not supported",
        "multimodal is not supported",
        "multimodal content is not supported",
        "multimodal input is not supported",
        "vision is not supported",
        "vision input is not supported",
        "does not support images",
        "does not support image input",
        "does not support multimodal",
        "does not support vision",
        "model does not support image",
    )
    return any(phrase in text for phrase in phrases)


def _result_looks_like_image_input_unsupported(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    pieces: list[str] = []
    for key in ("error", "final_response", "message", "details"):
        value = result.get(key)
        if value:
            pieces.append(str(value))
    if not pieces:
        return False
    return _looks_like_image_input_unsupported(RuntimeError("\n".join(pieces)))


class HermesAgentBackend:
    """Minimal backend interface consumed by workers and generation helpers."""

    backend_id = "hermes-agent"

    def __init__(
        self,
        config: HermesBackendConfig,
        *,
        system_prompt: str = "",
        status_callback: Callable[[str], None] | None = None,
        tool_status_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.system_prompt = system_prompt or ""
        self._status_callback = status_callback
        self._tool_status_callback = tool_status_callback
        self._agent: Any | None = None
        self._agent_system_prompt: str | None = None
        self._agent_memory_home: str | None = None
        self._messages: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    @classmethod
    def from_config_manager(
        cls,
        config_manager: Any,
        *,
        system_prompt: str = "",
        status_callback: Callable[[str], None] | None = None,
        tool_status_callback: Callable[[str], None] | None = None,
    ) -> "HermesAgentBackend":
        return cls(
            HermesBackendConfig(**config_manager.get_hermes_config()),
            system_prompt=system_prompt,
            status_callback=status_callback,
            tool_status_callback=tool_status_callback,
        )

    def chat(
        self,
        user_text: str | list[dict[str, Any]],
        system_prompt: str = "",
        *,
        context: AgentContext | None = None,
        stream: bool = True,
    ) -> Iterator[str] | str:
        prompt = system_prompt or self.system_prompt
        if stream:
            return self._chat_stream(user_text, prompt, context)
        return self._run_turn(user_text, prompt, context)

    def oneshot(
        self,
        prompt: str,
        system_prompt: str = "",
        tools: bool = False,
        *,
        emit_callbacks: bool = False,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
    ) -> str:
        """Run a stateless helper generation task.

        ``tools=False`` maps to an empty enabled toolset, so Hermes cannot run
        execution tools for form translation/template generation.
        Helper tasks are silent by default so internal planning/translation
        thoughts do not appear in the desktop chat thinking panel.
        """
        return self._run_helper_once(
            prompt,
            system_prompt,
            tools=tools,
            emit_callbacks=emit_callbacks,
            enabled_toolsets=enabled_toolsets,
            disabled_toolsets=disabled_toolsets,
        )

    def interrupt(self) -> None:
        with self._lock:
            agent = self._agent
        if agent is not None and hasattr(agent, "interrupt"):
            agent.interrupt()

    def reset_session(self) -> None:
        with self._lock:
            self._messages = []
            self._agent = None
            self._agent_system_prompt = None
            self._agent_memory_home = None

    def _config_for_tools(self, *, enabled: bool) -> HermesBackendConfig:
        if enabled:
            return self.config
        return HermesBackendConfig(
            max_iterations=self.config.max_iterations,
            enabled_toolsets=[],
            disabled_toolsets=list(self.config.disabled_toolsets),
            reasoning_config=dict(self.config.reasoning_config),
            max_tokens=self.config.max_tokens,
            stream=self.config.stream,
            use_internal_memory=self.config.use_internal_memory,
            disable_hermes_native_memory=self.config.disable_hermes_native_memory,
        )

    def _run_helper_once(
        self,
        prompt: str,
        system_prompt: str,
        *,
        tools: bool = False,
        emit_callbacks: bool = False,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
    ) -> str:
        helper_config = self._config_for_tools(enabled=tools)
        helper_enabled_toolsets = enabled_toolsets if enabled_toolsets is not None else helper_config.enabled_toolsets
        helper_disabled_toolsets = disabled_toolsets if disabled_toolsets is not None else helper_config.disabled_toolsets
        if helper_enabled_toolsets == []:
            enabled_arg: list[str] | None = []
        else:
            enabled_arg = helper_enabled_toolsets or None
        local_model = self._model_config()
        with tempfile.TemporaryDirectory(prefix="agent_helper_") as home:
            with _temporary_hermes_home(home):
                agent = self._create_agent(
                    base_url=local_model.get("base_url") or None,
                    provider=local_model.get("provider") or None,
                    model=local_model.get("model") or "",
                    max_iterations=int(helper_config.max_iterations),
                    enabled_toolsets=enabled_arg,
                    disabled_toolsets=list(helper_disabled_toolsets or []),
                    quiet_mode=True,
                    ephemeral_system_prompt="",
                    status_callback=self._on_status if emit_callbacks else None,
                    tool_start_callback=self._on_tool_start if emit_callbacks else None,
                    tool_complete_callback=self._on_tool_complete if emit_callbacks else None,
                    thinking_callback=self._on_thinking if emit_callbacks else None,
                    reasoning_callback=self._on_thinking if emit_callbacks else None,
                    max_tokens=helper_config.max_tokens,
                    reasoning_config=dict(helper_config.reasoning_config or {}),
                    skip_context_files=True,
                    load_soul_identity=False,
                    skip_memory=True,
                )
                result = agent.run_conversation(
                    prompt,
                    system_message=str(system_prompt or "").strip(),
                    conversation_history=[],
                )
        if not isinstance(result, dict):
            return str(result or "")
        return str(result.get("final_response") or "")

    def _chat_stream(
        self,
        user_text: str | list[dict[str, Any]],
        system_prompt: str,
        context: AgentContext | None,
    ) -> Iterator[str]:
        out: queue.Queue[object] = queue.Queue()
        sentinel = object()
        error: list[BaseException] = []
        emitted = {"value": False}

        def on_delta(delta: str) -> None:
            if delta:
                emitted["value"] = True
                out.put(str(delta))

        def run() -> None:
            try:
                final = self._run_turn(
                    user_text,
                    system_prompt,
                    context,
                    stream_callback=on_delta,
                )
                if not emitted["value"] and final:
                    out.put(final)
            except BaseException as exc:
                error.append(exc)
            finally:
                out.put(sentinel)

        threading.Thread(target=run, name="HermesAgentStream", daemon=True).start()
        while True:
            item = out.get()
            if item is sentinel:
                if error:
                    raise error[0]
                break
            yield str(item)

    def _run_turn(
        self,
        user_text: str | list[dict[str, Any]],
        system_prompt: str,
        context: AgentContext | None = None,
        *,
        stream_callback: Callable[[str], None] | None = None,
    ) -> str:
        full_system = self._build_system_prompt(system_prompt, context)
        memory_home = (
            str(context.memory_home)
            if self.config.use_internal_memory and context and context.memory_home
            else None
        )
        local_model = self._model_config()
        image_support_key = _image_support_cache_key(local_model)
        has_image_parts = _content_has_image_parts(user_text)
        original_user_text = user_text
        if has_image_parts and _is_image_unsupported_cached(image_support_key):
            user_text = _text_from_multimodal_content(user_text)
            has_image_parts = False
            if self._status_callback is not None:
                self._status_callback("当前 Hermes 模型不支持图片输入，已改为纯文本提示。")
        with self._lock:
            agent = self._get_agent(full_system, memory_home=memory_home)
            history = list(self._messages)
        with _temporary_hermes_home(memory_home):
            previous_retries = getattr(agent, "_api_max_retries", None)
            try:
                if has_image_parts and isinstance(previous_retries, int):
                    agent._api_max_retries = 1
                result = agent.run_conversation(
                    user_text,
                    system_message=full_system,
                    conversation_history=history,
                    stream_callback=stream_callback,
                )
                if has_image_parts and _result_looks_like_image_input_unsupported(result):
                    _mark_image_unsupported(image_support_key)
                    fallback_text = _text_from_multimodal_content(original_user_text)
                    if self._status_callback is not None:
                        self._status_callback("当前 Hermes 模型不支持图片输入，已改为纯文本提示。")
                    if isinstance(previous_retries, int):
                        agent._api_max_retries = previous_retries
                    result = agent.run_conversation(
                        fallback_text,
                        system_message=full_system,
                        conversation_history=history,
                        stream_callback=stream_callback,
                        persist_user_message=fallback_text,
                    )
            except Exception as exc:
                if not (has_image_parts and _looks_like_image_input_unsupported(exc)):
                    raise
                _mark_image_unsupported(image_support_key)
                fallback_text = _text_from_multimodal_content(original_user_text)
                if self._status_callback is not None:
                    self._status_callback("当前 Hermes 模型不支持图片输入，已改为纯文本提示。")
                if isinstance(previous_retries, int):
                    agent._api_max_retries = previous_retries
                result = agent.run_conversation(
                    fallback_text,
                    system_message=full_system,
                    conversation_history=history,
                    stream_callback=stream_callback,
                    persist_user_message=fallback_text,
                )
            finally:
                if has_image_parts and isinstance(previous_retries, int):
                    agent._api_max_retries = previous_retries
        if not isinstance(result, dict):
            return str(result or "")
        messages = result.get("messages")
        if isinstance(messages, list):
            with self._lock:
                self._messages = messages
        return str(result.get("final_response") or "")

    def _build_system_prompt(self, system_prompt: str, context: AgentContext | None = None) -> str:
        parts: list[str] = [DIALOG_PROTOCOL]
        if self.config.use_internal_memory:
            parts.append(self._render_context(context, system_prompt))
        elif system_prompt and system_prompt.strip():
            parts.append(system_prompt.strip())
        return "\n\n".join(parts)

    def _render_context(self, context: AgentContext | None, fallback_system_prompt: str) -> str:
        if context is None:
            return (fallback_system_prompt or "").strip()

        sections: list[str] = []
        sections.append(
            "【Here 专属上下文】\n"
            "你正在 Here 桌面精灵项目中运行。Hermes 的 SOUL.md、MEMORY.md、USER.md 已被定向到 Here 当前角色目录；"
            "只能使用这些 Here 文件、当前聊天模板与本轮上下文作为角色长期身份来源。"
        )
        if context.selected_characters:
            names = "、".join(context.selected_characters)
            sections.append(
                f"【当前可输出角色】\n"
                f"本轮只能输出这些角色的 JSON 台词：{names}。不要输出未列出的角色。"
            )
        template = (context.system_template or fallback_system_prompt or "").strip()
        if template:
            sections.append(f"【当前聊天模板/场景设定】\n{template}")

        summary = (context.session_summary or "").strip()
        if summary:
            sections.append("【当前会话摘要】\n" + summary)

        life_state = (context.life_state or "").strip()
        if life_state:
            sections.append(
                life_state
                + "\n这是角色此刻正在经历的生活状态，只用于增加真实感；不要抢走用户当前话题。"
            )

        if context.dialog_protocol and context.dialog_protocol.strip():
            sections.append("【附加对话协议】\n" + context.dialog_protocol.strip())
        return "\n\n".join(sections)

    def _render_soul(self, soul: CharacterSoul) -> str:
        parts = [f"### {soul.name}"]
        if soul.character_setting.strip():
            parts.append(soul.character_setting.strip())
        if soul.visual_identity.strip():
            parts.append("视觉身份：" + soul.visual_identity.strip())
        if soul.emotion_tags.strip():
            parts.append("立绘/情绪标签：\n" + soul.emotion_tags.strip())
        return "\n".join(parts)

    def _render_memories(self, memories: dict[str, list[str]]) -> str:
        blocks: list[str] = []
        for name, items in (memories or {}).items():
            clean = [str(item).strip() for item in items if str(item).strip()]
            if clean:
                blocks.append(f"### {name}\n" + "\n".join(f"- {item}" for item in clean))
        return "\n\n".join(blocks)

    def _get_agent(self, system_prompt: str, *, memory_home: str | None = None) -> Any:
        if (
            self._agent is not None
            and self._agent_system_prompt == system_prompt
            and self._agent_memory_home == (memory_home or None)
        ):
            return self._agent

        enabled_toolsets = self.config.enabled_toolsets
        if enabled_toolsets == []:
            enabled_arg: list[str] | None = []
        else:
            enabled_arg = enabled_toolsets or None

        local_model = self._model_config()
        with _temporary_hermes_home(memory_home):
            self._agent = self._create_agent(
                base_url=local_model.get("base_url") or None,
                provider=local_model.get("provider") or None,
                model=local_model.get("model") or "",
                max_iterations=int(self.config.max_iterations),
                enabled_toolsets=enabled_arg,
                disabled_toolsets=list(self.config.disabled_toolsets or []),
                quiet_mode=True,
                ephemeral_system_prompt="",
                status_callback=self._on_status,
                tool_start_callback=self._on_tool_start,
                tool_complete_callback=self._on_tool_complete,
                thinking_callback=self._on_thinking,
                reasoning_callback=self._on_thinking,
                max_tokens=self.config.max_tokens,
                reasoning_config=dict(self.config.reasoning_config or {}),
                skip_context_files=True,
                load_soul_identity=bool(memory_home),
                skip_memory=not bool(memory_home),
                **self._extra_agent_kwargs(memory_home=memory_home),
            )
        self._agent_system_prompt = system_prompt
        self._agent_memory_home = memory_home or None
        return self._agent

    def _model_config(self) -> dict[str, Any]:
        return _local_hermes_model_config()

    def _agent_class(self) -> Any:
        return _hermes_agent_class()

    def _create_agent(self, **kwargs: Any) -> Any:
        return self._agent_class()(**kwargs)

    def _extra_agent_kwargs(self, *, memory_home: str | None = None) -> dict[str, Any]:
        return {}

    def _on_status(self, *args: Any, **kwargs: Any) -> None:
        if self._status_callback is None:
            return
        text = " · ".join(str(a) for a in args if a is not None)
        if text:
            self._status_callback(text)

    def _on_tool_start(self, *args: Any, **kwargs: Any) -> None:
        if self._tool_status_callback is None:
            return
        name = kwargs.get("tool_name") or kwargs.get("name")
        if name is None and args:
            name = args[0]
        self._tool_status_callback(f"Hermes tool: {name}")

    def _on_tool_complete(self, *args: Any, **kwargs: Any) -> None:
        if self._tool_status_callback is None:
            return
        name = kwargs.get("tool_name") or kwargs.get("name")
        if name is None and args:
            name = args[0]
        self._tool_status_callback(f"Hermes tool complete: {name}")

    def _on_thinking(self, *args: Any, **kwargs: Any) -> None:
        if self._tool_status_callback is None:
            return
        text = " ".join(str(a) for a in args if a is not None).strip()
        if text:
            self._tool_status_callback(text)
