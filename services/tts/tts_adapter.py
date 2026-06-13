# tts_adapter.py
from services.adapters import TTSAdapter
import binascii
import os
import requests
from pathlib import Path
import asyncio


def _clean_url(url: str, default: str) -> str:
    text = str(url or "").strip()
    return text.rstrip("/") if text else default.rstrip("/")


def _raise_missing_secret(name: str, env_name: str) -> None:
    raise RuntimeError(f"{name} requires an API key. Set it in tts_extra_configs or ${env_name}.")


class EdgeTTSAdapter(TTSAdapter):
    """Adapter for the free Microsoft Edge online TTS service via edge-tts."""

    requires_reference_audio = False

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
        **_ignored,
    ):
        self.voice = voice or "zh-CN-XiaoxiaoNeural"
        self.rate = rate or "+0%"
        self.volume = volume or "+0%"
        self.pitch = pitch or "+0Hz"

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "voice": {
                "type": "str",
                "label": "Voice",
                "default": "zh-CN-XiaoxiaoNeural",
                "placeholder": "zh-CN-XiaoxiaoNeural",
                "choices": [
                    "zh-CN-XiaoxiaoNeural",
                    "zh-CN-XiaoyiNeural",
                    "zh-CN-YunjianNeural",
                    "zh-CN-YunxiNeural",
                    "zh-CN-YunxiaNeural",
                    "zh-CN-YunyangNeural",
                    "zh-CN-liaoning-XiaobeiNeural",
                    "zh-CN-shaanxi-XiaoniNeural",
                    "zh-HK-HiuGaaiNeural",
                    "zh-HK-HiuMaanNeural",
                    "zh-HK-WanLungNeural",
                    "zh-TW-HsiaoChenNeural",
                    "zh-TW-HsiaoYuNeural",
                    "zh-TW-YunJheNeural",
                    "ja-JP-NanamiNeural",
                    "ja-JP-KeitaNeural",
                    "en-US-JennyNeural",
                    "en-US-GuyNeural",
                    "en-US-AriaNeural",
                    "en-GB-SoniaNeural",
                    "en-GB-RyanNeural",
                ],
                "editable": True,
                "help": "Edge TTS voice name, e.g. zh-CN-XiaoxiaoNeural / zh-CN-YunxiNeural.",
            },
            "rate": {
                "type": "str",
                "label": "Rate",
                "default": "+0%",
                "placeholder": "+0%",
                "help": "Speech rate, e.g. +0%, -10%, +15%.",
            },
            "volume": {
                "type": "str",
                "label": "Volume",
                "default": "+0%",
                "placeholder": "+0%",
            },
            "pitch": {
                "type": "str",
                "label": "Pitch",
                "default": "+0Hz",
                "placeholder": "+0Hz",
            },
        }

    def _normalize_output_path(self, file_path: str | None) -> str:
        path = Path(file_path or os.path.join("temp", f"edge_tts_{os.urandom(4).hex()}.mp3"))
        path = path.with_suffix(".mp3")
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path.resolve())

    async def _generate_async(self, text: str, out_path: str) -> None:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError("edge-tts is not installed. Run: pip install edge-tts") from exc
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch,
        )
        await communicate.save(out_path)

    def generate_speech(self, text, file_path=None, **kwargs):
        text = str(text or "").strip()
        if not text:
            return None
        out_path = self._normalize_output_path(file_path)
        try:
            asyncio.run(self._generate_async(text, out_path))
            return out_path if os.path.exists(out_path) else None
        except Exception as e:
            print(f"Edge TTS generation failed: {e}")
            return None

    def switch_model(self, model_info):
        return None


class OpenAITTSAdapter(TTSAdapter):
    """Online TTS via OpenAI's speech API."""

    requires_reference_audio = False

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        response_format: str = "mp3",
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 60,
        **_ignored,
    ):
        self.api_key = (
            api_key
            or os.environ.get("OPENAI_API_KEY", "")
            or os.environ.get("SILICONFLOW_API_KEY", "")
            or os.environ.get("API_KEY", "")
        )
        self.model = model or "gpt-4o-mini-tts"
        self.voice = voice or "alloy"
        self.response_format = (response_format or "mp3").lstrip(".")
        self.base_url = _clean_url(base_url, "https://api.openai.com/v1")
        self.timeout = int(timeout or 60)

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "api_key": {"type": "password", "label": "OpenAI API key", "default": ""},
            "model": {"type": "str", "label": "Model", "default": "gpt-4o-mini-tts"},
            "voice": {"type": "str", "label": "Voice", "default": "alloy"},
            "response_format": {"type": "str", "label": "Format", "default": "mp3"},
            "base_url": {"type": "str", "label": "Base URL", "default": "https://api.openai.com/v1"},
            "timeout": {"type": "int", "label": "Timeout seconds", "default": 60, "min": 5, "max": 600},
        }

    def _output_path(self, file_path: str | None) -> str:
        suffix = "." + (self.response_format or "mp3").lstrip(".")
        path = Path(file_path or os.path.join("temp", f"openai_tts_{os.urandom(4).hex()}{suffix}"))
        path = path.with_suffix(suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path.resolve())

    def generate_speech(self, text, file_path=None, **kwargs):
        text = str(text or "").strip()
        if not text:
            return None
        if not self.api_key:
            _raise_missing_secret("OpenAI TTS", "OPENAI_API_KEY")
        out_path = self._output_path(file_path)
        payload = {
            "model": kwargs.get("model", self.model),
            "voice": kwargs.get("voice", self.voice),
            "input": text,
            "response_format": self.response_format,
        }
        try:
            response = requests.post(
                f"{self.base_url}/audio/speech",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            with open(out_path, "wb") as f:
                f.write(response.content)
            return out_path if os.path.exists(out_path) else None
        except Exception as e:
            print(f"OpenAI TTS generation failed: {e}")
            return None

    def switch_model(self, model_info):
        if not model_info:
            return
        if model_info.get("model"):
            self.model = model_info["model"]
        if model_info.get("voice"):
            self.voice = model_info["voice"]


class ElevenLabsTTSAdapter(TTSAdapter):
    """Online TTS via ElevenLabs."""

    requires_reference_audio = False

    def __init__(
        self,
        api_key: str = "",
        voice_id: str = "EXAVITQu4vr4xnSDxMaL",
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "mp3_44100_128",
        base_url: str = "https://api.elevenlabs.io/v1",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        timeout: int = 90,
        **_ignored,
    ):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self.voice_id = voice_id or "EXAVITQu4vr4xnSDxMaL"
        self.model_id = model_id or "eleven_multilingual_v2"
        self.output_format = output_format or "mp3_44100_128"
        self.base_url = _clean_url(base_url, "https://api.elevenlabs.io/v1")
        self.stability = float(stability)
        self.similarity_boost = float(similarity_boost)
        self.timeout = int(timeout or 90)

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "api_key": {"type": "password", "label": "ElevenLabs API key", "default": ""},
            "voice_id": {"type": "str", "label": "Voice ID", "default": "EXAVITQu4vr4xnSDxMaL"},
            "model_id": {"type": "str", "label": "Model", "default": "eleven_multilingual_v2"},
            "output_format": {"type": "str", "label": "Output format", "default": "mp3_44100_128"},
            "base_url": {"type": "str", "label": "Base URL", "default": "https://api.elevenlabs.io/v1"},
            "stability": {"type": "float", "label": "Stability", "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05},
            "similarity_boost": {"type": "float", "label": "Similarity boost", "default": 0.75, "min": 0.0, "max": 1.0, "step": 0.05},
            "timeout": {"type": "int", "label": "Timeout seconds", "default": 90, "min": 5, "max": 600},
        }

    def _output_path(self, file_path: str | None) -> str:
        path = Path(file_path or os.path.join("temp", f"elevenlabs_tts_{os.urandom(4).hex()}.mp3"))
        path = path.with_suffix(".mp3")
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path.resolve())

    def generate_speech(self, text, file_path=None, **kwargs):
        text = str(text or "").strip()
        if not text:
            return None
        if not self.api_key:
            _raise_missing_secret("ElevenLabs TTS", "ELEVENLABS_API_KEY")
        out_path = self._output_path(file_path)
        voice_id = kwargs.get("voice_id", self.voice_id)
        payload = {
            "text": text,
            "model_id": kwargs.get("model_id", self.model_id),
            "voice_settings": {
                "stability": self.stability,
                "similarity_boost": self.similarity_boost,
            },
        }
        try:
            response = requests.post(
                f"{self.base_url}/text-to-speech/{voice_id}",
                params={"output_format": self.output_format},
                headers={
                    "xi-api-key": self.api_key,
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            with open(out_path, "wb") as f:
                f.write(response.content)
            return out_path if os.path.exists(out_path) else None
        except Exception as e:
            print(f"ElevenLabs TTS generation failed: {e}")
            return None

    def switch_model(self, model_info):
        if not model_info:
            return
        if model_info.get("voice_id"):
            self.voice_id = model_info["voice_id"]
        if model_info.get("model_id"):
            self.model_id = model_info["model_id"]


class MiniMaxTTSAdapter(TTSAdapter):
    """Online TTS via MiniMax T2A v2."""

    requires_reference_audio = False

    def __init__(
        self,
        api_key: str = "",
        group_id: str = "",
        model: str = "speech-02-hd",
        voice_id: str = "female-shaonv",
        base_url: str = "https://api.minimax.io/v1",
        sample_rate: int = 32000,
        bitrate: int = 128000,
        audio_format: str = "mp3",
        timeout: int = 90,
        **_ignored,
    ):
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self.group_id = group_id or os.environ.get("MINIMAX_GROUP_ID", "")
        self.model = model or "speech-02-hd"
        self.voice_id = voice_id or "female-shaonv"
        self.base_url = _clean_url(base_url, "https://api.minimax.io/v1")
        self.sample_rate = int(sample_rate or 32000)
        self.bitrate = int(bitrate or 128000)
        self.audio_format = (audio_format or "mp3").lstrip(".")
        self.timeout = int(timeout or 90)

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "api_key": {"type": "password", "label": "MiniMax API key", "default": ""},
            "group_id": {"type": "str", "label": "MiniMax Group ID", "default": ""},
            "model": {"type": "str", "label": "Model", "default": "speech-02-hd"},
            "voice_id": {"type": "str", "label": "Voice ID", "default": "female-shaonv"},
            "base_url": {"type": "str", "label": "Base URL", "default": "https://api.minimax.io/v1"},
            "sample_rate": {"type": "int", "label": "Sample rate", "default": 32000, "min": 8000, "max": 48000, "step": 1000},
            "bitrate": {"type": "int", "label": "Bitrate", "default": 128000, "min": 32000, "max": 320000, "step": 8000},
            "audio_format": {"type": "str", "label": "Format", "default": "mp3"},
            "timeout": {"type": "int", "label": "Timeout seconds", "default": 90, "min": 5, "max": 600},
        }

    def _output_path(self, file_path: str | None) -> str:
        suffix = "." + (self.audio_format or "mp3").lstrip(".")
        path = Path(file_path or os.path.join("temp", f"minimax_tts_{os.urandom(4).hex()}{suffix}"))
        path = path.with_suffix(suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path.resolve())

    def generate_speech(self, text, file_path=None, **kwargs):
        text = str(text or "").strip()
        if not text:
            return None
        if not self.api_key:
            _raise_missing_secret("MiniMax TTS", "MINIMAX_API_KEY")
        if not self.group_id:
            raise RuntimeError("MiniMax TTS requires group_id. Set it in tts_extra_configs or $MINIMAX_GROUP_ID.")
        out_path = self._output_path(file_path)
        payload = {
            "model": kwargs.get("model", self.model),
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": kwargs.get("voice_id", self.voice_id),
                "speed": float(kwargs.get("speed", 1.0)),
                "vol": float(kwargs.get("volume", 1.0)),
                "pitch": int(kwargs.get("pitch", 0)),
            },
            "audio_setting": {
                "sample_rate": self.sample_rate,
                "bitrate": self.bitrate,
                "format": self.audio_format,
                "channel": 1,
            },
        }
        try:
            response = requests.post(
                f"{self.base_url}/t2a_v2",
                params={"GroupId": self.group_id},
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            audio_hex = (((data or {}).get("data") or {}).get("audio") or "")
            if not audio_hex:
                raise RuntimeError(f"MiniMax TTS returned no audio: {data}")
            with open(out_path, "wb") as f:
                f.write(binascii.unhexlify(audio_hex))
            return out_path if os.path.exists(out_path) else None
        except Exception as e:
            print(f"MiniMax TTS generation failed: {e}")
            return None

    def switch_model(self, model_info):
        if not model_info:
            return
        if model_info.get("model"):
            self.model = model_info["model"]
        if model_info.get("voice_id"):
            self.voice_id = model_info["voice_id"]


class FishAudioTTSAdapter(TTSAdapter):
    """Online TTS via Fish Audio's HTTP API."""

    requires_reference_audio = False

    def __init__(
        self,
        api_key: str = "",
        reference_id: str = "",
        model: str = "",
        base_url: str = "https://api.fish.audio",
        audio_format: str = "mp3",
        mp3_bitrate: int = 128,
        latency: str = "normal",
        timeout: int = 90,
        **_ignored,
    ):
        self.api_key = api_key or os.environ.get("FISH_AUDIO_API_KEY", "")
        self.reference_id = reference_id or os.environ.get("FISH_AUDIO_REFERENCE_ID", "")
        self.model = model or ("s2" if self.reference_id else "s2-pro")
        self.base_url = _clean_url(base_url, "https://api.fish.audio")
        self.audio_format = (audio_format or "mp3").lstrip(".")
        self.mp3_bitrate = int(mp3_bitrate or 128)
        self.latency = latency or "normal"
        self.timeout = int(timeout or 90)
        self.last_error = ""

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "api_key": {"type": "password", "label": "Fish Audio API key", "default": ""},
            "reference_id": {"type": "str", "label": "Reference ID", "default": ""},
            "model": {"type": "str", "label": "Model", "default": "s2"},
            "base_url": {"type": "str", "label": "Base URL", "default": "https://api.fish.audio"},
            "audio_format": {"type": "str", "label": "Format", "default": "mp3"},
            "mp3_bitrate": {"type": "int", "label": "MP3 bitrate", "default": 128, "min": 64, "max": 320, "step": 16},
            "latency": {"type": "str", "label": "Latency", "default": "normal"},
            "timeout": {"type": "int", "label": "Timeout seconds", "default": 90, "min": 5, "max": 600},
        }

    def _output_path(self, file_path: str | None) -> str:
        suffix = "." + (self.audio_format or "mp3").lstrip(".")
        path = Path(file_path or os.path.join("temp", f"fish_audio_tts_{os.urandom(4).hex()}{suffix}"))
        path = path.with_suffix(suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path.resolve())

    def _tts_url(self) -> str:
        if self.base_url.endswith("/v1/tts"):
            return self.base_url
        return f"{self.base_url}/v1/tts"

    def generate_speech(self, text, file_path=None, **kwargs):
        self.last_error = ""
        text = str(text or "").strip()
        if not text:
            return None
        if not self.api_key:
            _raise_missing_secret("Fish Audio TTS", "FISH_AUDIO_API_KEY")
        out_path = self._output_path(file_path)
        payload = {
            "text": text,
            "format": self.audio_format,
        }
        if self.audio_format == "mp3":
            payload["mp3_bitrate"] = self.mp3_bitrate
        if self.latency:
            payload["latency"] = self.latency
        reference_id = kwargs.get("reference_id", self.reference_id)
        if reference_id:
            payload["reference_id"] = reference_id
        model = str(kwargs.get("model") or self.model or ("s2" if reference_id else "s2-pro")).strip()
        try:
            response = requests.post(
                self._tts_url(),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                    "model": model,
                },
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            with open(out_path, "wb") as f:
                f.write(response.content)
            return out_path if os.path.exists(out_path) else None
        except Exception as e:
            self.last_error = str(e)
            print(f"Fish Audio TTS generation failed: {e}")
            return None

    def switch_model(self, model_info):
        if model_info and model_info.get("model"):
            self.model = model_info["model"]
        if model_info and model_info.get("reference_id"):
            self.reference_id = model_info["reference_id"]
