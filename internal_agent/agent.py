from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

from internal_agent.memory import build_identity_prompt
from internal_agent.memory_tool import run as run_memory_tool
from internal_agent.memory_tool import schema as memory_tool_schema
from internal_agent.session_search import search as session_search
from internal_agent.session_search import schema as session_search_schema
from internal_agent.session_store import SessionStore


DEFAULT_MODEL = "gpt-4o-mini"


class InternalAgent:
    """Minimal OpenAI-compatible agent runtime."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
        model: str = "",
        max_iterations: int = 90,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
        quiet_mode: bool = True,
        ephemeral_system_prompt: str | None = None,
        status_callback: Callable[..., None] | None = None,
        tool_start_callback: Callable[..., None] | None = None,
        tool_complete_callback: Callable[..., None] | None = None,
        thinking_callback: Callable[..., None] | None = None,
        reasoning_callback: Callable[..., None] | None = None,
        max_tokens: int | None = None,
        reasoning_config: dict[str, Any] | None = None,
        skip_context_files: bool = True,
        load_soul_identity: bool = False,
        skip_memory: bool = True,
        memory_home: str | Path | None = None,
        session_id: str | None = None,
        session_store: SessionStore | None = None,
        **_: Any,
    ) -> None:
        del quiet_mode, skip_context_files
        self.base_url = base_url or None
        self.provider = (provider or "").strip().lower()
        self.model = model or DEFAULT_MODEL
        self.max_iterations = int(max_iterations or 1)
        self.enabled_toolsets = enabled_toolsets
        self.disabled_toolsets = list(disabled_toolsets or [])
        self.ephemeral_system_prompt = ephemeral_system_prompt or ""
        self.status_callback = status_callback
        self.tool_start_callback = tool_start_callback
        self.tool_complete_callback = tool_complete_callback
        self.thinking_callback = thinking_callback
        self.reasoning_callback = reasoning_callback
        self.max_tokens = max_tokens
        self.reasoning_config = dict(reasoning_config or {})
        self.load_soul_identity = load_soul_identity
        self.skip_memory = skip_memory
        self.memory_home = Path(memory_home).expanduser() if memory_home else None
        self.session_id = str(session_id or self._new_session_id())
        self.session_store = session_store or self._default_session_store()
        self._api_key = api_key or self._api_key_from_env()
        self._api_max_retries = 3
        self._interrupted = threading.Event()

    def interrupt(self) -> None:
        self._interrupted.set()

    def run_conversation(
        self,
        user_message: str | list[dict[str, Any]],
        system_message: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
        task_id: str | None = None,
        stream_callback: Callable[[str], None] | None = None,
        persist_user_message: str | None = None,
    ) -> dict[str, Any]:
        del task_id
        self._interrupted.clear()
        history = list(conversation_history or [])
        messages = self._build_messages(
            user_message=user_message,
            system_message=system_message,
            conversation_history=history,
        )
        tools = self._build_tools()
        final_response = ""

        for _ in range(max(1, self.max_iterations)):
            if self._interrupted.is_set():
                break
            assistant_message = self._request(messages, tools=tools, stream_callback=stream_callback)
            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                final_response = str(assistant_message.get("content") or "")
                messages.append({"role": "assistant", "content": final_response})
                break
            messages.append(assistant_message)
            for tool_call in tool_calls:
                messages.append(self._run_tool(tool_call))
        else:
            final_response = "I reached the maximum tool iterations before producing a final response."

        if persist_user_message is not None:
            self._apply_persist_user_message_override(messages, user_message, persist_user_message)
        persisted = self._messages_without_system(messages)
        self._persist_session(persisted, system_message=system_message)
        return {"final_response": final_response, "messages": persisted, "completed": True}

    def _api_key_from_env(self) -> str:
        candidates: list[str] = []
        if self.provider:
            candidates.append(f"{self.provider.upper().replace('-', '_')}_API_KEY")
        candidates.extend(["OPENAI_API_KEY", "API_KEY"])
        for name in candidates:
            value = os.environ.get(name)
            if value:
                return value
        return "unused"

    def _build_messages(
        self,
        *,
        user_message: str | list[dict[str, Any]],
        system_message: str | None,
        conversation_history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        identity = build_identity_prompt(
            memory_home=self.memory_home,
            load_soul_identity=self.load_soul_identity,
            skip_memory=self.skip_memory,
        )
        system = "\n\n".join(
            part.strip()
            for part in (identity, system_message or self.ephemeral_system_prompt)
            if str(part or "").strip()
        )
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for item in conversation_history:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if role in {"user", "assistant", "system", "tool"} and "content" in item:
                messages.append(
                    {
                        key: value
                        for key, value in item.items()
                        if key in {"role", "content", "tool_call_id", "name", "tool_calls"}
                    }
                )
        messages.append({"role": "user", "content": user_message})
        return messages

    def _build_tools(self) -> list[dict[str, Any]] | None:
        enabled = set(self.enabled_toolsets or [])
        disabled = set(self.disabled_toolsets or [])
        tools: list[dict[str, Any]] = []
        if "memory" in enabled and "memory" not in disabled:
            tools.append(memory_tool_schema())
        if "session_search" in enabled and "session_search" not in disabled:
            tools.append(session_search_schema())
        return tools or None

    def _request(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        stream_callback: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        client = OpenAI(api_key=self._api_key, base_url=self.base_url)
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.reasoning_config:
            kwargs.update(self.reasoning_config)
        if stream_callback is None:
            completion = client.chat.completions.create(**kwargs)
            return _response_message_to_dict(completion)

        kwargs["stream"] = True
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        last_id_at_index: dict[int, str] = {}
        active_slot_by_index: dict[int, int] = {}
        for chunk in client.chat.completions.create(**kwargs):
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            delta = _get_attr(choice, "delta")
            if delta is None:
                continue
            reasoning = _get_attr(delta, "reasoning_content") or _get_attr(delta, "reasoning")
            if reasoning:
                text = str(reasoning)
                reasoning_parts.append(text)
                self._emit_reasoning(text)
            content = _normalize_content(_get_attr(delta, "content"))
            if content:
                content_parts.append(content)
                if not tool_calls:
                    stream_callback(content)
            for tool_delta in _get_attr(delta, "tool_calls") or []:
                raw_index = int(_get_attr(tool_delta, "index") or 0)
                delta_id = str(_get_attr(tool_delta, "id") or "")
                if raw_index not in active_slot_by_index:
                    active_slot_by_index[raw_index] = raw_index
                if (
                    delta_id
                    and raw_index in last_id_at_index
                    and delta_id != last_id_at_index[raw_index]
                ):
                    active_slot_by_index[raw_index] = max(tool_calls, default=-1) + 1
                if delta_id:
                    last_id_at_index[raw_index] = delta_id
                index = active_slot_by_index[raw_index]
                current = tool_calls.setdefault(
                    index,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if delta_id:
                    current["id"] = delta_id
                func = _get_attr(tool_delta, "function")
                if func is not None:
                    name = _get_attr(func, "name")
                    if name:
                        current["function"]["name"] = str(name)
                    arguments = _get_attr(func, "arguments")
                    if arguments:
                        current["function"]["arguments"] += str(arguments)
        message: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
        if reasoning_parts:
            message["reasoning_content"] = "".join(reasoning_parts)
        if tool_calls:
            message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
        return message

    def _run_tool(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        function = tool_call.get("function") or {}
        name = str(function.get("name") or "")
        args_error = ""
        try:
            args = json.loads(function.get("arguments") or "{}")
            if not isinstance(args, dict):
                args = {}
        except Exception as exc:
            args = None
            args_error = str(exc)
        if self.tool_start_callback is not None:
            self.tool_start_callback(tool_name=name)
        if args is None:
            result = f"Error: Invalid JSON arguments for tool '{name}': {args_error}"
        elif name == "memory":
            result = run_memory_tool(
                action=str(args.get("action") or ""),
                target=str(args.get("target") or "memory"),
                content=args.get("content"),
                old_text=args.get("old_text"),
                memory_home=self.memory_home,
            )
        elif name == "session_search":
            result = session_search(
                str(args.get("query") or ""),
                int(args.get("limit") or 5),
                memory_home=self.memory_home,
                session_store=self.session_store,
                current_session_id=self.session_id,
                role_filter=args.get("role_filter"),
            )
        else:
            result = f"Tool {name} is not available."
        if self.tool_complete_callback is not None:
            self.tool_complete_callback(tool_name=name)
        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id") or name,
            "name": name,
            "content": result,
        }

    def _emit_reasoning(self, text: str) -> None:
        for callback in (self.reasoning_callback, self.thinking_callback):
            if callback is None:
                continue
            try:
                callback(text)
            except Exception:
                pass

    def _default_session_store(self) -> SessionStore | None:
        if self.memory_home is None:
            return None
        return SessionStore(self.memory_home.parent.parent)

    def _new_session_id(self) -> str:
        return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    def _messages_without_system(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            dict(message)
            for message in messages
            if isinstance(message, dict) and message.get("role") != "system"
        ]

    def _apply_persist_user_message_override(
        self,
        messages: list[dict[str, Any]],
        original: str | list[dict[str, Any]],
        override: str,
    ) -> None:
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            if message.get("content") == original:
                message["content"] = override
                return

    def _persist_session(self, messages: list[dict[str, Any]], *, system_message: str | None) -> None:
        if self.session_store is None:
            return
        try:
            self.session_store.create_session(
                self.session_id,
                source="desktop_chat",
                model=self.model,
                system_prompt=system_message or self.ephemeral_system_prompt,
            )
            self.session_store.replace_messages(self.session_id, messages)
        except Exception:
            pass


def _message_to_dict(message: Any) -> dict[str, Any]:
    if hasattr(message, "model_dump"):
        data = message.model_dump(exclude_none=True)
    elif isinstance(message, dict):
        data = dict(message)
    else:
        data = {
            "role": getattr(message, "role", "assistant"),
            "content": getattr(message, "content", ""),
        }
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            data["tool_calls"] = [_tool_call_to_dict(tool_call) for tool_call in tool_calls]
    data.setdefault("role", "assistant")
    data["content"] = _normalize_content(data.get("content"))
    return data


def _response_message_to_dict(response: Any) -> dict[str, Any]:
    choices = _get_attr(response, "choices") or []
    if not choices:
        raise RuntimeError("Model response did not include choices.")
    message = _get_attr(choices[0], "message")
    if message is None:
        raise RuntimeError("Model response choice did not include a message.")
    return _message_to_dict(message)


def _get_attr(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _normalize_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("text") or value.get("content") or json.dumps(value, ensure_ascii=False))
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item.get("text") or ""))
        return "\n".join(part for part in parts if part)
    return str(value)


def _tool_call_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        data = dict(value)
    elif hasattr(value, "model_dump"):
        data = value.model_dump(exclude_none=True)
    else:
        function = _get_attr(value, "function") or {}
        data = {
            "id": _get_attr(value, "id") or "",
            "type": _get_attr(value, "type") or "function",
            "function": {
                "name": _get_attr(function, "name") or "",
                "arguments": _get_attr(function, "arguments") or "",
            },
        }
    data.setdefault("type", "function")
    function = data.get("function") or {}
    if not isinstance(function, dict):
        function = {
            "name": _get_attr(function, "name") or "",
            "arguments": _get_attr(function, "arguments") or "",
        }
    data["function"] = {
        "name": str(function.get("name") or ""),
        "arguments": str(function.get("arguments") or ""),
    }
    data["id"] = str(data.get("id") or data["function"]["name"] or "tool_call")
    return data
