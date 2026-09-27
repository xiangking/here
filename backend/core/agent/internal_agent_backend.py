"""Backend adapter for the bundled Internal Agent."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from internal_agent.context import AgentContext
from core.agent.hermes_backend import (
    HermesAgentBackend,
    HermesBackendConfig,
    _content_has_image_parts,
    _image_support_cache_key,
    _is_image_unsupported_cached,
    _looks_like_image_input_unsupported,
    _mark_image_unsupported,
    _result_looks_like_image_input_unsupported,
    _text_from_multimodal_content,
)


def _internal_agent_class() -> Any:
    from internal_agent import InternalAgent

    return InternalAgent


class InternalAgentBackend(HermesAgentBackend):
    """Backend adapter that talks to the bundled internal agent package."""

    backend_id = "internal-agent"

    def __init__(
        self,
        config: HermesBackendConfig,
        *,
        internal_agent_config: dict[str, Any] | None = None,
        system_prompt: str = "",
        status_callback: Callable[[str], None] | None = None,
        tool_status_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            config,
            system_prompt=system_prompt,
            status_callback=status_callback,
            tool_status_callback=tool_status_callback,
        )
        self.internal_agent_config = dict(internal_agent_config or {})

    @classmethod
    def from_config_manager(
        cls,
        config_manager: Any,
        *,
        system_prompt: str = "",
        status_callback: Callable[[str], None] | None = None,
        tool_status_callback: Callable[[str], None] | None = None,
    ) -> "InternalAgentBackend":
        return cls(
            HermesBackendConfig(**config_manager.get_hermes_config()),
            internal_agent_config=config_manager.get_internal_agent_config(),
            system_prompt=system_prompt,
            status_callback=status_callback,
            tool_status_callback=tool_status_callback,
        )

    def _agent_class(self) -> Any:
        return _internal_agent_class()

    def _model_config(self) -> dict[str, Any]:
        return dict(self.internal_agent_config)

    def _create_agent(self, **kwargs: Any) -> Any:
        model_cfg = self._model_config()
        api_key = model_cfg.get("api_key")
        if model_cfg.get("provider"):
            kwargs["provider"] = model_cfg["provider"]
        if model_cfg.get("model"):
            kwargs["model"] = model_cfg["model"]
        if model_cfg.get("base_url"):
            kwargs["base_url"] = model_cfg["base_url"]
        if api_key:
            kwargs["api_key"] = api_key
        return self._agent_class()(**kwargs)

    def _extra_agent_kwargs(self, *, memory_home: str | None = None) -> dict[str, Any]:
        return {"memory_home": memory_home} if memory_home else {}

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
        enabled_arg = [] if helper_enabled_toolsets == [] else helper_enabled_toolsets or None
        local_model = self._model_config()
        agent = self._create_agent(
            base_url=local_model.get("base_url") or None,
            provider=local_model.get("provider") or None,
            model=local_model.get("model") or "",
            max_iterations=int(helper_config.max_iterations),
            enabled_toolsets=enabled_arg,
            disabled_toolsets=list(helper_disabled_toolsets or []),
            quiet_mode=True,
            ephemeral_system_prompt=str(system_prompt or "").strip(),
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

    def _get_agent(self, system_prompt: str, *, memory_home: str | None = None) -> Any:
        if (
            self._agent is not None
            and self._agent_system_prompt == system_prompt
            and self._agent_memory_home == (memory_home or None)
        ):
            return self._agent

        enabled_toolsets = self.config.enabled_toolsets
        enabled_arg: list[str] | None = [] if enabled_toolsets == [] else enabled_toolsets or None
        local_model = self._model_config()
        self._agent = self._create_agent(
            base_url=local_model.get("base_url") or None,
            provider=local_model.get("provider") or None,
            model=local_model.get("model") or "",
            max_iterations=int(self.config.max_iterations),
            enabled_toolsets=enabled_arg,
            disabled_toolsets=list(self.config.disabled_toolsets or []),
            quiet_mode=True,
            ephemeral_system_prompt=system_prompt,
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
                self._status_callback("当前 Internal Agent 模型不支持图片输入，已改为纯文本提示。")
        with self._lock:
            agent = self._get_agent(full_system, memory_home=memory_home)
            history = list(self._messages)
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
                    self._status_callback("当前 Internal Agent 模型不支持图片输入，已改为纯文本提示。")
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
                self._status_callback("当前 Internal Agent 模型不支持图片输入，已改为纯文本提示。")
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

    def _on_tool_start(self, *args: Any, **kwargs: Any) -> None:
        if self._tool_status_callback is None:
            return
        name = kwargs.get("tool_name") or kwargs.get("name")
        if name is None and args:
            name = args[0]
        self._tool_status_callback(f"Internal Agent tool: {name}")

    def _on_tool_complete(self, *args: Any, **kwargs: Any) -> None:
        if self._tool_status_callback is None:
            return
        name = kwargs.get("tool_name") or kwargs.get("name")
        if name is None and args:
            name = args[0]
        self._tool_status_callback(f"Internal Agent tool complete: {name}")
