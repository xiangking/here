"""Unit tests for ASR Manager + Factory + adapter helper functions."""

import pytest

from services.asr.asr_manager import ASRAdapterFactory
from services.asr.asr_adapter import (
    ASRSetupStatus,
    VOSK_SMALL_CN_MODEL_DIRNAME,
    build_asr_setup_status,
    bundled_vosk_model_path,
    default_vosk_model_path,
    is_vosk_model_dir,
    missing_asr_requirements,
    _pcm16_rms,
    voice_ui_to_asr_lang,
    ui_lang_to_asr_lang,
    system_config_to_asr_lang,
    normalize_asr_provider_storage_key,
    _whisper_triplet_from_sys,
)
from services.asr.protocols import ASRAdapter
from test.mocks import MockASRAdapter


class TestASRAdapterFactory:
    def test_builtin_vosk_registered(self):
        assert "vosk" in ASRAdapterFactory._adapters

    def test_factory_accepts_injection(self):
        ASRAdapterFactory._adapters["mock-asr"] = MockASRAdapter
        try:
            assert "mock-asr" in ASRAdapterFactory._adapters
        finally:
            del ASRAdapterFactory._adapters["mock-asr"]

    def test_factory_values_are_adapter_subclasses(self):
        for key, cls in ASRAdapterFactory._adapters.items():
            assert issubclass(cls, ASRAdapter), f"{key} → {cls} is not an ASRAdapter subclass"


class TestPcm16Rms:
    def test_empty_audio_is_silent(self):
        assert _pcm16_rms(b"") == 0

    def test_all_zero_samples_are_silent(self):
        assert _pcm16_rms((0).to_bytes(2, "little", signed=True) * 4) == 0

    def test_known_samples(self):
        samples = [3, 4]
        data = b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples)
        assert _pcm16_rms(data) == 3

    def test_negative_samples(self):
        samples = [-3, -4]
        data = b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples)
        assert _pcm16_rms(data) == 3

    def test_ignores_incomplete_trailing_byte(self):
        data = (256).to_bytes(2, "little", signed=True) + b"\xff"
        assert _pcm16_rms(data) == 256


class TestMockASRAdapter:
    def test_init_defaults(self, mock_asr_adapter):
        assert mock_asr_adapter.language == "zh"
        assert mock_asr_adapter.get_status() == "idle"

    def test_start_changes_status(self, mock_asr_adapter):
        mock_asr_adapter.start()
        assert mock_asr_adapter.get_status() == "listening"

    def test_stop_changes_status(self, mock_asr_adapter):
        mock_asr_adapter.start()
        mock_asr_adapter.stop()
        assert mock_asr_adapter.get_status() == "stopped"

    def test_pause_changes_status(self, mock_asr_adapter):
        mock_asr_adapter.start()
        mock_asr_adapter.pause()
        assert mock_asr_adapter.get_status() == "paused"

    def test_resume_after_pause(self, mock_asr_adapter):
        mock_asr_adapter.start()
        mock_asr_adapter.pause()
        mock_asr_adapter.resume()
        assert mock_asr_adapter.get_status() == "listening"

    def test_callback_fires(self, mock_asr_adapter):
        results = []
        adapter = MockASRAdapter(language="en", callback=lambda text, is_final: results.append((text, is_final)))
        adapter.simulate_transcription("hello", is_final=True)
        assert results == [("hello", True)]

    def test_call_history_records(self, mock_asr_adapter):
        mock_asr_adapter.start()
        mock_asr_adapter.pause()
        mock_asr_adapter.resume()
        mock_asr_adapter.stop()
        assert mock_asr_adapter.call_history == ["start", "pause", "resume", "stop"]


class TestLanguageMapping:
    def test_voice_ui_zh(self):
        assert voice_ui_to_asr_lang("zh_CN") == "zh"
        assert voice_ui_to_asr_lang("zh") == "zh"

    def test_voice_ui_ja(self):
        assert voice_ui_to_asr_lang("ja") == "ja"
        assert voice_ui_to_asr_lang("JA") == "ja"

    def test_voice_ui_en(self):
        assert voice_ui_to_asr_lang("en") == "en"
        assert voice_ui_to_asr_lang("en_US") == "en"

    def test_voice_ui_default(self):
        assert voice_ui_to_asr_lang("") == "zh"
        assert voice_ui_to_asr_lang("fr") == "zh"

    def test_ui_lang_to_asr_mapping(self):
        assert ui_lang_to_asr_lang("zh_CN") == "zh"
        assert ui_lang_to_asr_lang("en") == "en"
        assert ui_lang_to_asr_lang("ja") == "ja"
        assert ui_lang_to_asr_lang(None) == "zh"
        assert ui_lang_to_asr_lang("fr") == "zh"


class TestSystemConfigToAsrLang:
    def test_explicit_asr_language_takes_priority(self):
        class FakeSysCfg:
            asr_language = "ja"
            ui_language = "zh_CN"
        assert system_config_to_asr_lang(FakeSysCfg()) == "ja"

    def test_empty_asr_language_falls_back_to_ui(self):
        class FakeSysCfg:
            asr_language = ""
            ui_language = "en"
        assert system_config_to_asr_lang(FakeSysCfg()) == "en"

    def test_none_asr_language_falls_back(self):
        class FakeSysCfg:
            asr_language = None
            ui_language = "ja"
        assert system_config_to_asr_lang(FakeSysCfg()) == "ja"


class TestNormalizeAsrProviderKey:
    def test_vosk(self):
        assert normalize_asr_provider_storage_key("vosk") == "vosk"

    def test_faster_whisper_variants(self):
        assert normalize_asr_provider_storage_key("faster_whisper") == "faster_whisper"
        assert normalize_asr_provider_storage_key("fasterwhisper") == "faster_whisper"
        assert normalize_asr_provider_storage_key("whisper") == "faster_whisper"

    def test_realtime_stt_variants(self):
        assert normalize_asr_provider_storage_key("realtime_stt") == "realtime_stt"
        assert normalize_asr_provider_storage_key("realtimestt") == "realtime_stt"

    def test_unknown_defaults_to_vosk(self):
        assert normalize_asr_provider_storage_key("unknown_xyz") == "vosk"


class TestASRSetupHelpers:
    def _make_vosk_model(self, path):
        (path / "am").mkdir(parents=True)
        (path / "am" / "final.mdl").write_text("fake", encoding="utf-8")
        (path / "conf").mkdir()
        (path / "conf" / "model.conf").write_text("fake", encoding="utf-8")
        (path / "graph").mkdir()

    def test_vosk_model_dir_rejects_empty_dir(self, tmp_path):
        assert not is_vosk_model_dir(tmp_path)

    def test_vosk_model_dir_accepts_expected_layout(self, tmp_path):
        self._make_vosk_model(tmp_path)

        assert is_vosk_model_dir(tmp_path)

    def test_default_vosk_model_prefers_bundled_model(self, tmp_path, monkeypatch):
        project_root = tmp_path / "project"
        model = project_root / "assets" / "system" / "models" / VOSK_SMALL_CN_MODEL_DIRNAME
        self._make_vosk_model(model)
        monkeypatch.setattr("infrastructure.paths.project_root", lambda: project_root)

        assert bundled_vosk_model_path() == model.as_posix()
        assert default_vosk_model_path() == model.as_posix()

    def test_setup_status_reports_missing_vosk_model(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.asr.asr_adapter.missing_asr_requirements",
            lambda _provider: [],
        )

        status = build_asr_setup_status("vosk", model_path=str(tmp_path / "missing"))

        assert not status.ready
        assert status.needs_model
        assert status.missing_model_path.endswith("missing")

    def test_setup_status_ready_for_valid_vosk_model(self, tmp_path, monkeypatch):
        self._make_vosk_model(tmp_path)
        monkeypatch.setattr(
            "services.asr.asr_adapter.missing_asr_requirements",
            lambda _provider: [],
        )

        status = build_asr_setup_status("vosk", model_path=str(tmp_path))

        assert status.ready
        assert not status.needs_dependencies
        assert not status.needs_model

    def test_missing_requirements_accepts_realtimestt_alternative(self, monkeypatch):
        def fake_find_spec(name):
            return object() if name == "realtimestt" else None

        monkeypatch.setattr("services.asr.asr_adapter.find_spec", fake_find_spec)

        assert missing_asr_requirements("realtime_stt") == []

    def test_setup_status_user_message_describes_actions(self):
        status = ASRSetupStatus(
            provider="vosk",
            missing_modules=("pyaudio",),
            missing_model_path="/tmp/model",
        )

        message = status.user_message()

        assert "pyaudio" in message
        assert "/tmp/model" in message


class TestWhisperTriplet:
    def test_returns_defaults(self):
        class FakeSysCfg:
            asr_whisper_model_size = None
            asr_whisper_device = None
            asr_whisper_compute_type = None
        sz, dev, ct = _whisper_triplet_from_sys(FakeSysCfg())
        assert sz == "small"
        assert dev == "auto"
        assert ct == ""

    def test_returns_custom_values(self):
        class FakeSysCfg:
            asr_whisper_model_size = "large-v3"
            asr_whisper_device = "cuda"
            asr_whisper_compute_type = "float16"
        sz, dev, ct = _whisper_triplet_from_sys(FakeSysCfg())
        assert sz == "large-v3"
        assert dev == "cuda"
        assert ct == "float16"
