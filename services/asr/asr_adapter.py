from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional
import queue

from services.i18n.lang import normalize_lang
from services.asr.protocols import ASRAdapter, TranscriptionCallback

# Vosk 模型默认路径（可按本机下载模型修改）
VOSK_MODEL_PATH = "./assets/system/models/vosk-model-small-cn-0.22"


def get_asr_log() -> logging.Logger:
    """ASR 专用 logger：默认 stderr。级别可用环境变量 HERE_ASR_LOG（DEBUG/INFO/WARNING）。"""
    log = logging.getLogger("here.asr")
    if log.handlers:
        return log
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(threadName)s] here.asr: %(message)s"
        )
    )
    log.addHandler(h)
    # _name = (os.environ.get("HERE_ASR_LOG") or "INFO").upper()
    _name = 'ERROR'
    _lvl = getattr(logging, _name, logging.INFO)
    log.setLevel(_lvl if isinstance(_lvl, int) else logging.INFO)
    log.propagate = False
    return log


_log = get_asr_log()


def _pcm16_rms(fragment: bytes) -> int:
    """Return RMS for little-endian signed 16-bit PCM audio."""
    sample_count = len(fragment) // 2
    if sample_count <= 0:
        return 0

    total = 0
    for idx in range(0, sample_count * 2, 2):
        sample = int.from_bytes(fragment[idx:idx + 2], "little", signed=True)
        total += sample * sample
    return math.isqrt(total // sample_count)


def voice_ui_to_asr_lang(voice_ui: str) -> str:
    """将 system_config.voice_language（及菜单所选）映射到 ASR / Whisper 语言代码。"""
    s = (voice_ui or "zh").strip().lower().replace("-", "_")
    if s.startswith("zh"):
        return "zh"
    if s in ("ja", "jp"):
        return "ja"
    if s.startswith("en"):
        return "en"
    if s in ("yue", "cantonese", "zh_yue"):
        # Whisper 无 yue 独立码，粤语会话用 zh 识别常可接受
        return "zh"
    return "zh"


def ui_lang_to_asr_lang(ui_lang: str | None) -> str:
    """将 system_config.ui_language（zh_CN / en / ja）映射到 ASR 语言代码。"""
    code = normalize_lang(ui_lang)
    if code == "en":
        return "en"
    if code == "ja":
        return "ja"
    return "zh"


def system_config_to_asr_lang(sys_cfg: Any) -> str:
    """asr_language 非空则用其映射，否则与 ui_language 一致。"""
    raw = getattr(sys_cfg, "asr_language", None)
    if raw is not None and str(raw).strip():
        return voice_ui_to_asr_lang(str(raw))
    return ui_lang_to_asr_lang(str(getattr(sys_cfg, "ui_language", "") or ""))


def _whisper_triplet_from_sys(sys_cfg: Any) -> tuple[str, str, str]:
    """从 system_config 读取 Whisper / RealtimeSTT 共用的模型与设备选项。"""
    return (
        str(getattr(sys_cfg, "asr_whisper_model_size", None) or "small"),
        str(getattr(sys_cfg, "asr_whisper_device", None) or "auto"),
        str(getattr(sys_cfg, "asr_whisper_compute_type", None) or ""),
    )


def normalize_asr_provider_storage_key(prov: str) -> str:
    """与 API 页 ASR 下拉 userData 一致的存储键（vosk / faster_whisper / realtime_stt）。"""
    p = (prov or "vosk").strip().lower().replace("-", "_")
    if p in ("faster_whisper", "fasterwhisper", "whisper"):
        return "faster_whisper"
    if p in ("realtime_stt", "realtimestt"):
        return "realtime_stt"
    return "vosk"


def _huggingface_hub_cache_dir() -> Path:
    raw = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if raw:
        return Path(raw).expanduser()
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _is_complete_faster_whisper_snapshot(path: Path) -> bool:
    return all((path / name).exists() for name in (
        "config.json",
        "model.bin",
        "tokenizer.json",
        "vocabulary.txt",
    ))


def _resolve_cached_faster_whisper_model(model_name_or_path: str) -> str:
    """Return a local snapshot path when the requested faster-whisper model is already cached."""
    raw = str(model_name_or_path or "").strip()
    if not raw:
        return raw

    direct = Path(raw).expanduser()
    if direct.exists():
        return direct.resolve().as_posix()

    model_name = raw
    if "/" in raw:
        parts = raw.split("/")
        if len(parts) == 2 and parts[0] == "Systran" and parts[1].startswith("faster-whisper-"):
            model_name = parts[1].removeprefix("faster-whisper-")
        else:
            return raw

    repo_cache = _huggingface_hub_cache_dir() / f"models--Systran--faster-whisper-{model_name}"
    snapshots = repo_cache / "snapshots"
    ref_file = repo_cache / "refs" / "main"
    if ref_file.exists():
        ref = ref_file.read_text(encoding="utf-8").strip()
        candidate = snapshots / ref
        if _is_complete_faster_whisper_snapshot(candidate):
            return candidate.resolve().as_posix()

    if snapshots.exists():
        candidates = [p for p in snapshots.iterdir() if p.is_dir()]
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for candidate in candidates:
            if _is_complete_faster_whisper_snapshot(candidate):
                return candidate.resolve().as_posix()
    return raw


class VoskAdapter(ASRAdapter):
    """
    Vosk 库的适配器。
    将 Vosk 的流式处理逻辑映射到 ASRAdapter 接口。
    """

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "model_path": {
                "type": "str",
                "label": "Vosk model path",
                "default": VOSK_MODEL_PATH,
            },
            "sample_rate": {
                "type": "int",
                "label": "Sample rate",
                "default": 16000,
                "min": 8000,
                "max": 48000,
                "step": 1000,
            },
            "chunk_size": {
                "type": "int",
                "label": "Chunk size",
                "default": 8192,
                "min": 1024,
                "max": 32768,
                "step": 1024,
            },
        }

    def __init__(
        self,
        language: str,
        callback: TranscriptionCallback,
        model_path: str = VOSK_MODEL_PATH,
        sample_rate: int = 16000,
        chunk_size: int = 8192,
    ):
        super().__init__(language, callback)
        # 禁止在模块顶层 import vosk：会立刻执行其 open_dll/add_dll_directory，冻结时路径常无效。
        import pyaudio
        from vosk import Model, KaldiRecognizer  # noqa: E402

        self._pyaudio = pyaudio
        self._KaldiRecognizer = KaldiRecognizer
        self.model_path = Path(model_path).absolute().as_posix()
        self._is_running = False
        self._thread: Optional[threading.Thread] = None

        self._pause_event = threading.Event()
        self._pause_event.set()

        self.samplerate = int(sample_rate or 16000)
        self.chunk_size = int(chunk_size or 8192)

        try:
            self.model = Model(model_path=self.model_path)
        except Exception as e:
            _log.error("Vosk model load failed: %s path=%s", e, self.model_path)
            self.model = None

    def _vosk_recognition_loop(self):
        """在独立线程中运行的 Vosk 识别循环。"""
        if self.model is None:
            return
        pyaudio = self._pyaudio
        KaldiRecognizer = self._KaldiRecognizer

        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.samplerate,
            input=True,
            frames_per_buffer=self.chunk_size,
        )

        recognizer = KaldiRecognizer(self.model, self.samplerate)
        stream.start_stream()
        silence_probe_count = 0
        silence_probe_rms_max = 0
        silence_probe_notified = False

        while self._is_running:
            if not self._pause_event.is_set():
                time.sleep(0.1)
                continue

            data = stream.read(self.chunk_size, exception_on_overflow=False)
            if not silence_probe_notified and silence_probe_count < 8:
                try:
                    silence_probe_rms_max = max(silence_probe_rms_max, _pcm16_rms(data))
                except Exception:
                    pass
                silence_probe_count += 1
                if silence_probe_count >= 8 and silence_probe_rms_max <= 1:
                    silence_probe_notified = True
                    self.callback("麦克风输入为空，请检查系统输入设备/权限/音量。", is_partial=True)
            if recognizer.AcceptWaveform(data):
                result_json = json.loads(recognizer.Result())
                if result_json.get("text"):
                    self.callback(result_json["text"], is_partial=False)
            else:
                result_json = json.loads(recognizer.PartialResult())
                if result_json.get("partial"):
                    self.callback(result_json["partial"], is_partial=True)

        stream.stop_stream()
        stream.close()
        p.terminate()
        _log.info("Vosk recognition loop ended")

    def start(self):
        """启动 Vosk 识别线程。"""
        if self._is_running:
            _log.warning("Vosk start: already running")
            return

        if self.model is None:
            raise RuntimeError(f"Vosk 模型未加载，无法启动：{self.model_path}")

        _log.info("Vosk starting…")
        self._is_running = True
        self._thread = threading.Thread(target=self._vosk_recognition_loop)
        self._thread.start()
        _log.info("Vosk started")

    def stop(self):
        """停止 Vosk 识别线程。"""
        if not self._is_running:
            return

        _log.info("Vosk stopping…")
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join()
        _log.info("Vosk stopped")

    def get_status(self) -> str:
        """获取 Vosk 的运行状态。"""
        return "Running" if self._is_running else "Stopped"

    def pause(self):
        """暂停 Vosk 识别。"""
        if self._is_running:
            _log.info("Vosk pause")
            self._pause_event.clear()

    def resume(self):
        """恢复 Vosk 识别。"""
        if self._is_running:
            _log.info("Vosk resume")
            self._pause_event.set()


class FasterWhisperAdapter(ASRAdapter):
    """Streaming microphone ASR using faster-whisper.

    The first initialization downloads the requested model through
    faster-whisper/CTranslate2's normal Hugging Face cache path.
    """

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "vad_filter": {
                "type": "bool",
                "label": "VAD filter",
                "default": True,
                "help": "Filter silence during transcription.",
            },
            "chunk_seconds": {
                "type": "float",
                "label": "Chunk seconds",
                "default": 4.0,
                "min": 1.0,
                "max": 15.0,
                "step": 0.5,
                "help": "Microphone audio chunk length for each transcription pass.",
            },
            "beam_size": {
                "type": "int",
                "label": "Beam size",
                "default": 1,
                "min": 1,
                "max": 8,
                "step": 1,
            },
            "silence_threshold": {
                "type": "float",
                "label": "Silence threshold",
                "default": 0.01,
                "min": 0.0,
                "max": 0.2,
                "step": 0.01,
            },
            "sample_rate": {
                "type": "int",
                "label": "Sample rate",
                "default": 16000,
                "min": 8000,
                "max": 48000,
                "step": 1000,
            },
            "chunk_frames": {
                "type": "int",
                "label": "Chunk frames",
                "default": 1024,
                "min": 256,
                "max": 4096,
                "step": 256,
            },
        }

    def __init__(
        self,
        language: str,
        callback: TranscriptionCallback,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "",
        vad_filter: bool = True,
        chunk_seconds: float = 4.0,
        beam_size: int = 1,
        silence_threshold: float = 0.01,
        sample_rate: int = 16000,
        chunk_frames: int = 1024,
    ):
        super().__init__(language, callback)
        try:
            import numpy as np
            import pyaudio
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper ASR dependencies are missing. Run: uv sync --extra asr"
            ) from exc

        self._np = np
        self._pyaudio = pyaudio
        self.model_size = model_size or "small"
        self.model_path_or_size = _resolve_cached_faster_whisper_model(self.model_size)
        self.device = "auto" if (device or "auto") == "auto" else device
        self.compute_type = compute_type or ("int8" if self.device in ("auto", "cpu") else "float16")
        self.vad_filter = bool(vad_filter)
        self.chunk_seconds = max(1.0, float(chunk_seconds or 4.0))
        self.beam_size = max(1, int(beam_size or 1))
        self.silence_threshold = max(0.0, float(silence_threshold if silence_threshold is not None else 0.01))
        self.sample_rate = int(sample_rate or 16000)
        self.chunk_frames = int(chunk_frames or 1024)
        self._is_running = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._thread: Optional[threading.Thread] = None
        _log.info(
            "Loading faster-whisper model=%s resolved=%s device=%s compute=%s",
            self.model_size,
            self.model_path_or_size,
            self.device,
            self.compute_type,
        )
        self.model = WhisperModel(
            self.model_path_or_size,
            device=self.device,
            compute_type=self.compute_type,
        )

    def _recognition_loop(self) -> None:
        p = self._pyaudio.PyAudio()
        stream = p.open(
            format=self._pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_frames,
        )
        stream.start_stream()
        frames_per_pass = max(self.chunk_frames, int(self.sample_rate * self.chunk_seconds))
        pcm = bytearray()
        try:
            while self._is_running:
                if not self._pause_event.is_set():
                    time.sleep(0.1)
                    continue
                data = stream.read(self.chunk_frames, exception_on_overflow=False)
                pcm.extend(data)
                if len(pcm) < frames_per_pass * 2:
                    continue
                raw = bytes(pcm)
                pcm.clear()
                audio = self._np.frombuffer(raw, dtype=self._np.int16).astype(self._np.float32) / 32768.0
                if audio.size == 0 or float(self._np.max(self._np.abs(audio))) < self.silence_threshold:
                    continue
                segments, _info = self.model.transcribe(
                    audio,
                    language=self.language if self.language else None,
                    vad_filter=self.vad_filter,
                    beam_size=self.beam_size,
                )
                text = "".join(seg.text for seg in segments).strip()
                if text:
                    self.callback(text, is_partial=False)
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

    def start(self):
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._recognition_loop, name="faster_whisper_asr")
        self._thread.start()

    def stop(self):
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def get_status(self) -> str:
        return "Running" if self._is_running else "Stopped"

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()


class RealtimeSTTAdapter(ASRAdapter):
    """ASR adapter using the RealtimeSTT package.

    RealtimeSTT wraps faster-whisper with VAD and real-time segmentation. Its
    first model load also downloads the requested model to the local cache.
    """

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "enable_realtime_transcription": {
                "type": "bool",
                "label": "Realtime partial text",
                "default": True,
            },
            "realtime_processing_pause": {
                "type": "float",
                "label": "Realtime pause seconds",
                "default": 0.2,
                "min": 0.05,
                "max": 2.0,
                "step": 0.05,
            },
        }

    def __init__(
        self,
        language: str,
        callback: TranscriptionCallback,
        model_name: str = "small",
        device: str = "auto",
        compute_type: str = "",
        enable_realtime_transcription: bool = True,
        realtime_processing_pause: float = 0.2,
    ):
        super().__init__(language, callback)
        try:
            from RealtimeSTT import AudioToTextRecorder
        except ImportError:
            try:
                from realtimestt import AudioToTextRecorder
            except ImportError as exc:
                raise RuntimeError(
                    "RealtimeSTT ASR dependencies are missing. Run: uv sync --extra asr"
                ) from exc

        self._AudioToTextRecorder = AudioToTextRecorder
        self.model_name = model_name or "small"
        self.device = "cuda" if device == "cuda" else "cpu" if device == "cpu" else "auto"
        self.compute_type = compute_type or "default"
        self.enable_realtime_transcription = bool(enable_realtime_transcription)
        self.realtime_processing_pause = max(0.05, float(realtime_processing_pause or 0.2))
        self._is_running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._text_queue: "queue.Queue[str]" = queue.Queue()
        kwargs = {
            "model": self.model_name,
            "language": self.language if self.language else "",
            "enable_realtime_transcription": self.enable_realtime_transcription,
            "realtime_processing_pause": self.realtime_processing_pause,
            "on_realtime_transcription_update": self._on_realtime_text,
        }
        if self.device != "auto":
            kwargs["device"] = self.device
        if self.compute_type and self.compute_type != "default":
            kwargs["compute_type"] = self.compute_type
        _log.info("Loading RealtimeSTT model=%s device=%s compute=%s", self.model_name, self.device, self.compute_type)
        self.recorder = AudioToTextRecorder(**kwargs)

    def _on_realtime_text(self, text: str) -> None:
        text = (text or "").strip()
        if text and not self._paused:
            self.callback(text, is_partial=True)

    def _loop(self) -> None:
        while self._is_running:
            try:
                text = self.recorder.text()
                text = (text or "").strip()
                if text and not self._paused:
                    self.callback(text, is_partial=False)
            except Exception as exc:
                _log.error("RealtimeSTT loop failed: %s", exc)
                time.sleep(0.5)

    def start(self):
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._loop, name="realtime_stt_asr", daemon=True)
        self._thread.start()

    def stop(self):
        self._is_running = False
        try:
            self.recorder.shutdown()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def get_status(self) -> str:
        return "Running" if self._is_running else "Stopped"

    def pause(self):
        self._paused = True
        self._drain_text_queue()
        try:
            self.recorder.stop()
        except Exception:
            pass

    def resume(self):
        self._drain_text_queue()
        self._paused = False
        try:
            self.recorder.start()
        except Exception:
            pass

    def _drain_text_queue(self) -> None:
        while True:
            try:
                self._text_queue.get_nowait()
            except queue.Empty:
                return


def create_default_asr_adapter(callback: TranscriptionCallback) -> ASRAdapter:
    """按 system_config.asr_provider 创建 ASR。"""
    from services.asr.asr_manager import ASRAdapterFactory

    from services.config.adapter_extra_kwargs import filter_kwargs_for_ctor
    from services.config.config_manager import ConfigManager

    sys_cfg = ConfigManager().config.system_config
    lang = system_config_to_asr_lang(sys_cfg)
    prov = (sys_cfg.asr_provider or "vosk").strip().lower().replace("-", "_")
    storage_key = normalize_asr_provider_storage_key(prov)
    extras = ConfigManager().get_adapter_extra_config("asr", storage_key)
    model_sz, dev, ct = _whisper_triplet_from_sys(sys_cfg)
    _log.info(
        "create_default_asr_adapter: provider=%r language=%r whisper_model=%r device=%r compute=%r",
        prov,
        lang,
        model_sz,
        dev,
        ct,
    )

    adapter_cls = ASRAdapterFactory._adapters.get(storage_key)

    if adapter_cls is None:
        if storage_key != "vosk":
            _log.warning(
                "ASR provider %r not registered; falling back to vosk.",
                storage_key,
            )
        adapter_cls = VoskAdapter

    if adapter_cls is VoskAdapter:
        _kw = filter_kwargs_for_ctor(VoskAdapter, extras)
        model_path = str(_kw.get("model_path") or VOSK_MODEL_PATH)
        return VoskAdapter(language=lang, callback=callback, model_path=model_path, **{
            k: v for k, v in _kw.items() if k != "model_path"
        })

    _kw = filter_kwargs_for_ctor(adapter_cls, extras)
    if storage_key == "faster_whisper":
        _kw.update(model_size=model_sz, device=dev, compute_type=ct)
    elif storage_key == "realtime_stt":
        _kw.update(model_name=model_sz, device=dev, compute_type=ct)
    return adapter_cls(lang, callback, **_kw)
