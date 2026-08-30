"""ASR 适配器工厂。"""

from __future__ import annotations

from typing import Type

from services.asr.protocols import ASRAdapter

from services.asr.asr_adapter import FasterWhisperAdapter, RealtimeSTTAdapter, VoskAdapter


class ASRAdapterFactory:
    """内置 ASR 后端。"""

    _adapters: dict[str, Type[ASRAdapter]] = {
        "vosk": VoskAdapter,
        "faster_whisper": FasterWhisperAdapter,
        "realtime_stt": RealtimeSTTAdapter,
    }
