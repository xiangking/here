"""Unit tests for Pydantic config models — validation, defaults, aliases."""

import pytest
from pydantic import ValidationError

from services.config.schema import (
    Sprite,
    Character,
    Background,
    ApiConfig,
    SystemConfig,
    AppConfig,
)
from core.sprite.character_profile import default_character_profile


class TestSprite:
    def test_minimal_sprite(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_text("fake")
        s = Sprite(path=str(img))
        assert s.path is not None
        assert s.voice_path is None
        assert s.voice_text is None

    def test_full_sprite(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_text("fake")
        frame_1 = tmp_path / "frame_1.png"
        frame_2 = tmp_path / "frame_2.png"
        frame_1.write_text("fake frame 1")
        frame_2.write_text("fake frame 2")
        voice = tmp_path / "test.wav"
        voice.write_text("fake audio")
        s = Sprite(
            path=str(img),
            frames=[str(frame_1), str(frame_2)],
            frame_interval_ms=90,
            voice_path=str(voice),
            voice_text="hello",
        )
        assert s.frames == [str(frame_1), str(frame_2)]
        assert s.frame_interval_ms == 90
        assert s.voice_path is not None
        assert s.voice_text == "hello"

    def test_spritesheet_sprite(self, tmp_path):
        img = tmp_path / "fallback.png"
        sheet = tmp_path / "sheet.webp"
        img.write_text("fake")
        sheet.write_text("fake sheet")
        s = Sprite(
            path=str(img),
            spritesheet_path=str(sheet),
            frame_width=192,
            frame_height=208,
            frame_count=6,
            frame_row=2,
            fps=8,
        )
        assert s.spritesheet_path == str(sheet)
        assert s.frame_width == 192
        assert s.frame_height == 208
        assert s.frame_count == 6
        assert s.frame_row == 2
        assert s.fps == 8

    def test_path_required(self):
        with pytest.raises(ValidationError):
            Sprite()


class TestCharacter:
    def test_minimal_character(self):
        profile = default_character_profile("Alice")
        c = Character(name="Alice", color="#fff", sprite_prefix="alice", character_profile=profile)
        assert c.name == "Alice"
        assert c.character_profile == profile
        assert c.character_setting == ""
        assert c.sprite_scale == 1.0
        assert c.sprites == []
        assert c.emotion_tags == ""

    def test_full_character(self):
        c = Character(
            name="Alice",
            color="#ff0000",
            sprite_prefix="alice",
            character_profile=default_character_profile("Alice"),
            character_setting="A brave warrior.",
            visual_reference_image="here app home characters/alice/ref.png",
            visual_identity="black hair, red coat",
            sprite_scale=1.5,
            emotion_tags="happy:0, sad:1",
            speech_speed=1.2,
        )
        assert c.character_setting == "A brave warrior."
        assert c.visual_reference_image == "here app home characters/alice/ref.png"
        assert c.visual_identity == "black hair, red coat"
        assert c.sprite_scale == 1.5
        assert c.speech_speed == 1.2

    def test_none_defaults_treated_as_default(self):
        """None values for DefaultIfNone fields should fall back to defaults."""
        c = Character(
            name="Bob",
            color="#000",
            sprite_prefix="bob",
            character_profile=default_character_profile("Bob"),
            character_setting=None,
            sprite_scale=None,
        )
        assert c.character_setting == ""
        assert c.sprite_scale == 1.0

    def test_character_profile_required(self):
        with pytest.raises(ValidationError):
            Character(name="Bob", color="#000", sprite_prefix="bob")


class TestApiConfig:
    def test_defaults(self):
        ac = ApiConfig()
        assert ac.agent_backend == "auto"
        assert ac.hermes_streaming is True
        assert ac.hermes_max_iterations == 90
        assert ac.hermes_enabled_toolsets == ["memory", "session_search"]
        assert ac.tts_provider == "edge-tts"
        assert ac.t2i_provider == "image-api"
        assert ac.selfie_provider == ""
        assert ac.selfie_extra_configs == {}

    def test_custom_hermes_runtime_policy(self):
        ac = ApiConfig(hermes_streaming=False, hermes_max_iterations=12)
        assert ac.hermes_streaming is False
        assert ac.hermes_max_iterations == 12


class TestAppConfig:
    def test_valid_app_config(self, sample_app_config):
        assert len(sample_app_config.characters) >= 1
        assert sample_app_config.api_config is not None
        assert sample_app_config.system_config is not None

    def test_empty_characters_allowed(self):
        ac = AppConfig(
            characters=[],
            background_list=[],
            api_config=ApiConfig(),
            system_config=SystemConfig(),
        )
        assert ac.characters == []
