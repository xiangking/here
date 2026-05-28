"""从 Hermes Agent 流式输出中按 JSON 对象切分并解析为 AgentDialogMessage。"""

import json
import re
from typing import Iterator

from core.messaging.messages import AgentDialogMessage


class AgentResponseStreamParser:
    """
    消费文本 chunk，在缓冲区中查找完整的 `{...}` JSON 片段，解析为对话消息。
    与流式/非流式（单 chunk）均可复用；完整原文保存在 accumulated_text 供写入历史。

    feed 为生成器：每成功解析一个对象就 yield 一次，便于立刻写入 tts_queue（与在 worker 里
    边解析边 put 的时序一致；同一 chunk 内多个 JSON 也会在解析第一个后先交付下游）。
    """

    def __init__(self) -> None:
        self._buffer = ""
        self.accumulated_text = ""

    def feed(self, chunk: str) -> Iterator[AgentDialogMessage]:
        """将新到达的文本并入缓冲区，并对其中已完整的 JSON 逐条 yield。"""
        if chunk:
            self._buffer += chunk
            self.accumulated_text += chunk
        yield from self._iter_drain_complete_objects()

    def flush(self) -> Iterator[AgentDialogMessage]:
        """流结束时再尝试解析一次残留内容。"""
        yield from self._iter_drain_complete_objects()
        if self._buffer.strip():
            for msg in self.recover_messages(self._buffer):
                yield msg
            self._buffer = ""

    def recover_messages(self, text: str) -> Iterator[AgentDialogMessage]:
        """从一段完整文本中尽量恢复 Here 对话消息。

        Hermes 偶尔会返回 Markdown 代码块、JSON 数组，或在 speech 中混入未转义的英文引号。
        这些都不应该直接进入 UI；这里按固定字段做最后一层容错提取。
        """
        clean = self._strip_code_fence(text or "").strip()
        if not clean:
            return
        try:
            payload = json.loads(clean)
            yield from self._messages_from_payload(payload)
            return
        except Exception:
            pass
        for raw_object in self._extract_object_like_blocks(clean):
            msg = self._message_from_fixed_fields(raw_object)
            if msg is not None:
                yield msg

    def _next_json_object_span(self) -> tuple[int, int] | None:
        start = self._buffer.find("{")
        if start == -1:
            if len(self._buffer) > 4096:
                self._buffer = self._buffer[-4096:]
            return None
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(self._buffer)):
            ch = self._buffer[index]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return start, index + 1
        if start > 0:
            self._buffer = self._buffer[start:]
        return None

    def _iter_drain_complete_objects(self) -> Iterator[AgentDialogMessage]:
        while True:
            span = self._next_json_object_span()
            if span is None:
                break
            start_index, end_index = span
            json_str = self._buffer[start_index:end_index]
            try:
                dialog_item = json.loads(json_str)
                self._buffer = self._buffer[end_index:].strip()
                yield from self._messages_from_payload(dialog_item)
            except json.JSONDecodeError:
                msg = self._message_from_fixed_fields(json_str)
                self._buffer = self._buffer[end_index:].strip()
                if msg is not None:
                    yield msg
            except Exception as e:
                print(f"处理失败: {e}")
                self._buffer = self._buffer[end_index:].strip()
                break

    def _messages_from_payload(self, payload) -> Iterator[AgentDialogMessage]:
        if isinstance(payload, dict):
            if isinstance(payload.get("dialog"), list):
                yield from self._messages_from_payload(payload["dialog"])
                return
            yield AgentDialogMessage(**payload)
            return
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    yield AgentDialogMessage(**item)

    def _strip_code_fence(self, text: str) -> str:
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped
        stripped = re.sub(r"^```(?:json|JSON)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
        return stripped.strip()

    def _extract_object_like_blocks(self, text: str) -> Iterator[str]:
        old_buffer = self._buffer
        try:
            self._buffer = text
            while True:
                span = self._next_json_object_span()
                if span is None:
                    break
                start_index, end_index = span
                yield self._buffer[start_index:end_index]
                self._buffer = self._buffer[end_index:].strip()
        finally:
            self._buffer = old_buffer

    def _message_from_fixed_fields(self, raw_object: str) -> AgentDialogMessage | None:
        name = self._extract_json_string_field(raw_object, "character_name")
        speech = self._extract_json_string_until_next_known_field(raw_object, "speech")
        emotion = self._extract_json_string_field(raw_object, "emotion") or "neutral"
        asset_id = self._extract_json_scalar_field(raw_object, "asset_id")
        system_action = self._extract_system_action(raw_object)
        if name is None or speech is None:
            return None
        return AgentDialogMessage(
            name=name,
            text=speech,
            emotion=emotion,
            asset_id=asset_id if asset_id is not None else "-1",
            system_action=system_action,
        )

    def _extract_json_string_field(self, raw_object: str, field_name: str) -> str | None:
        pattern = rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"'
        match = re.search(pattern, raw_object, flags=re.DOTALL)
        if not match:
            return None
        return self._decode_jsonish_string(match.group(1))

    def _extract_json_string_until_next_field(
        self, raw_object: str, field_name: str, next_field_name: str
    ) -> str | None:
        pattern = (
            rf'"{re.escape(field_name)}"\s*:\s*"(.*?)"'
            rf'\s*,\s*"{re.escape(next_field_name)}"\s*:'
        )
        match = re.search(pattern, raw_object, flags=re.DOTALL)
        if not match:
            return self._extract_json_string_field(raw_object, field_name)
        return self._decode_jsonish_string(match.group(1))

    def _extract_json_string_until_next_known_field(
        self, raw_object: str, field_name: str
    ) -> str | None:
        pattern = (
            rf'"{re.escape(field_name)}"\s*:\s*"(.*?)"'
            rf'\s*,\s*"(?:emotion|translate|effect|system_action|asset_id)"\s*:'
        )
        match = re.search(pattern, raw_object, flags=re.DOTALL)
        if not match:
            return self._extract_json_string_field(raw_object, field_name)
        return self._decode_jsonish_string(match.group(1))

    def _extract_json_scalar_field(self, raw_object: str, field_name: str) -> str | int | None:
        pattern = rf'"{re.escape(field_name)}"\s*:\s*("(?:\\.|[^"\\])*"|[-]?\d+|null)'
        match = re.search(pattern, raw_object, flags=re.DOTALL)
        if not match:
            return None
        value = match.group(1)
        if value == "null":
            return None
        try:
            return json.loads(value)
        except Exception:
            return value.strip('"')

    def _extract_system_action(self, raw_object: str):
        null_pattern = r'"system_action"\s*:\s*null'
        if re.search(null_pattern, raw_object):
            return None
        action_match = re.search(r'"system_action"\s*:\s*(\{.*\})\s*$', raw_object, flags=re.DOTALL)
        if action_match:
            try:
                return json.loads(action_match.group(1))
            except Exception:
                action_text = action_match.group(1)
                action_type = self._extract_json_string_field(action_text, "type")
                name = self._extract_json_string_field(action_text, "name")
                if action_type:
                    action = {"type": action_type}
                    if name:
                        action["name"] = name
                    return action
        return None

    def _decode_jsonish_string(self, value: str) -> str:
        try:
            return json.loads(f'"{value}"')
        except Exception:
            return value.replace(r"\"", '"').replace(r"\\", "\\")
