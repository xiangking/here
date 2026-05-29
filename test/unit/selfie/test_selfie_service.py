from __future__ import annotations

from datetime import datetime

from services.selfie import SelfieRequest, SelfieService
from services.selfie.factory import build_selfie_runtime
from test.conftest import make_app_config, make_character


class FakeT2IManager:
    def __init__(self) -> None:
        self.calls = []

    def t2i(self, prompt: str, **kwargs):
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        file_path = kwargs.get("file_path")
        if file_path:
            from pathlib import Path

            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            Path(file_path).write_bytes(b"fake png")
        return file_path


def test_selfie_service_builds_prompt_from_character_and_life_state(tmp_path):
    t2i = FakeT2IManager()
    character = make_character(
        name="Alice",
        visual_identity="short silver hair, blue cardigan",
        visual_reference_image="/ref/alice.png",
    )
    service = SelfieService(t2i_manager=t2i, provider_name="xai-grok-imagine", output_dir=tmp_path)

    result = service.generate(
        SelfieRequest(
            character=character,
            life_state="现在她正在：午饭和休息\n地点：咖啡店\n心情/精力：放松",
            photo_intent="拍一张坐在窗边的自然自拍。",
            contact_text="我午休的时候突然想起你。",
            emotion="happy",
            now=datetime(2026, 5, 26, 12, 20),
        )
    )

    assert result is not None
    assert result.provider == "xai-grok-imagine"
    assert "Alice" in result.prompt
    assert "咖啡店" in result.prompt
    assert result.path.endswith(".png")
    assert t2i.calls[0]["kwargs"]["file_path"] == result.path
    assert t2i.calls[0]["kwargs"]["reference_image_path"] == "/ref/alice.png"
    assert len(result.prompt) < 500
    assert "No chat UI" in result.prompt


def test_selfie_service_resolves_legacy_default_reference_path(tmp_path, monkeypatch):
    from infrastructure.paths import save_storage_paths

    app_home = tmp_path / "home"
    assets_dir = tmp_path / "assets"
    monkeypatch.setenv("HERE_APP_HOME", str(app_home))
    save_storage_paths(character_assets_dir=str(assets_dir))
    t2i = FakeT2IManager()
    character = make_character(
        name="Alice",
        visual_identity="",
        visual_reference_image="defaults/characters/here/animations/neutral/frame_001.png",
    )
    service = SelfieService(t2i_manager=t2i, provider_name="xai-grok-imagine", output_dir=tmp_path)

    service.generate(
        SelfieRequest(
            character=character,
            life_state="地点：住处",
            photo_intent="拍一张自然自拍。",
            now=datetime(2026, 5, 26, 12, 20),
        )
    )

    assert t2i.calls[0]["kwargs"]["reference_image_path"] == (
        assets_dir / "here" / "animations" / "neutral" / "frame_001.png"
    ).as_posix()


def test_selfie_service_preserves_explicit_size_extra(tmp_path):
    t2i = FakeT2IManager()
    character = make_character(name="Alice", visual_identity="short silver hair")
    service = SelfieService(
        t2i_manager=t2i,
        provider_name="openai-gpt-image",
        output_dir=tmp_path,
        default_kwargs={"size": "auto"},
    )

    service.generate(
        SelfieRequest(
            character=character,
            life_state="地点：住处",
            photo_intent="拍一张自然自拍。",
            now=datetime(2026, 5, 26, 12, 20),
        )
    )

    assert t2i.calls[0]["kwargs"]["size"] == "auto"
    assert "width" not in t2i.calls[0]["kwargs"]
    assert "height" not in t2i.calls[0]["kwargs"]


def test_build_selfie_runtime_uses_selfie_provider_when_photo_enabled(monkeypatch):
    app_config = make_app_config()
    app_config.system_config.proactive_photo_enabled = True
    app_config.api_config.selfie_provider = "xai-grok-imagine"
    app_config.api_config.t2i_provider = "image-api"
    app_config.api_config.selfie_extra_configs = {"width": 768, "height": 1024}
    app_config.api_config.t2i_extra_configs = {
        "xai-grok-imagine": {
            "api_key": "test-key",
            "api_url": "https://openrouter.ai/x-ai/grok-imagine-image-quality/api",
            "api_style": "openrouter",
        },
    }
    config = type("Config", (), {"config": app_config})()
    created: list[dict] = []

    def fake_create_adapter(adapter_name: str, **kwargs):
        created.append({"adapter_name": adapter_name, "kwargs": kwargs})
        return object()

    class FakeManager:
        def __init__(self, adapter) -> None:
            self.adapter = adapter
            self.switched = []

        def set_t2i_adapter(self, adapter) -> None:
            self.switched.append(adapter)
            self.adapter = adapter

    monkeypatch.setattr("services.selfie.factory.T2IAdapterFactory.create_adapter", fake_create_adapter)
    monkeypatch.setattr("services.selfie.factory.T2IManager", FakeManager)
    monkeypatch.setattr(
        config,
        "merged_t2i_factory_kwargs",
        lambda provider, base: {**base, **app_config.api_config.t2i_extra_configs.get(provider, {})},
        raising=False,
    )

    service, manager = build_selfie_runtime(config)

    assert service is not None
    assert isinstance(manager, FakeManager)
    assert service.provider_name == "xai-grok-imagine"
    assert service.default_kwargs == {"width": 768, "height": 1024}
    assert created == [
        {
            "adapter_name": "xai-grok-imagine",
            "kwargs": {
                "api_key": "test-key",
                "api_url": "https://openrouter.ai/x-ai/grok-imagine-image-quality/api",
                "api_style": "openrouter",
            },
        }
    ]


def test_build_selfie_runtime_does_not_create_adapter_when_photo_disabled(monkeypatch):
    app_config = make_app_config()
    app_config.system_config.proactive_photo_enabled = False
    config = type("Config", (), {"config": app_config})()

    def fail_create_adapter(*_args, **_kwargs):
        raise AssertionError("adapter should not be created")

    monkeypatch.setattr("services.selfie.factory.T2IAdapterFactory.create_adapter", fail_create_adapter)

    service, manager = build_selfie_runtime(config, enabled_only=True)

    assert service is None
    assert manager is None
