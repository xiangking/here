"""
Shared test fixtures: mock adapters, mock AppRuntime, test data factories.

All test files automatically import fixtures defined here — no manual import needed.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# MUST be first: reconfigure stdout/stderr to UTF-8 BEFORE any project code
# runs and prints non-ASCII text.  Otherwise pytest's capture tempfile will
# contain mixed-encoding bytes and fail during cleanup.
# ---------------------------------------------------------------------------
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass  # Python < 3.7 or non-reconfigurable streams (e.g. IDLE)

from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock

import pytest

# Make project root importable (tests run from repo root)
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.messaging.messages import UserInputMessage, AgentDialogMessage, TTSOutputMessage

# Re-export mock adapters from the importable module so fixtures work
from test.mocks import MockTTSAdapter, MockT2IAdapter, MockASRAdapter


# =========================================================================
# Test Data Factories — create valid Pydantic model instances with defaults
# =========================================================================

from services.config.schema import (
    Sprite,
    Character,
    Background,
    ApiConfig,
    SystemConfig,
    AppConfig,
)
from core.sprite.character_profile import default_character_profile


def make_sprite(path: str = "", voice_path: str = "", voice_text: str = "") -> Sprite:
    """Create a Sprite with an actual temp file if no path given."""
    if not path:
        import tempfile
        f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        path = f.name
        f.close()
    return Sprite(path=path, voice_path=voice_path or None, voice_text=voice_text or None)


def make_character(
    name: str = "TestChar",
    color: str = "#ffffff",
    sprite_prefix: str = "test",
    character_setting: str = "You are a test character.",
    **overrides,
) -> Character:
    kw = {
        "name": name,
        "color": color,
        "sprite_prefix": sprite_prefix,
        "character_profile": default_character_profile(name),
        "character_setting": character_setting,
    }
    kw.update(overrides)
    return Character(**kw)


def make_background(name: str = "TestBg", sprite_prefix: str = "test_bg", **overrides) -> Background:
    kw = {"name": name, "sprite_prefix": sprite_prefix}
    kw.update(overrides)
    return Background(**kw)


def make_api_config(
    **overrides,
) -> ApiConfig:
    kw = {
        "hermes_streaming": True,
    }
    kw.update(overrides)
    return ApiConfig(**kw)


def make_system_config(**overrides) -> SystemConfig:
    kw = {
        "ui_language": "zh_CN",
        "voice_language": "ja",
        "base_font_size_px": 56,
    }
    kw.update(overrides)
    return SystemConfig(**kw)


def make_app_config(
    characters: list = None,
    api_config: ApiConfig = None,
    system_config: SystemConfig = None,
    background_list: list = None,
) -> AppConfig:
    return AppConfig(
        characters=characters or [make_character()],
        background_list=background_list or [make_background()],
        api_config=api_config or make_api_config(),
        system_config=system_config or make_system_config(),
    )


def make_user_input(text: str = "Hello") -> UserInputMessage:
    return UserInputMessage(text=text)


def make_agent_dialog(
    name: str = "TestChar",
    text: str = "Hello from Hermes Agent",
    emotion: str = "neutral",
    asset_id: str = "-1",
    translate: str = "",
    effect: str = "",
) -> AgentDialogMessage:
    return AgentDialogMessage(
        name=name, text=text, emotion=emotion, asset_id=asset_id, translate=translate, effect=effect
    )


def make_tts_output(
    audio_path: str = "/tmp/fake.wav",
    name: str = "TestChar",
    text: str = "Spoken text",
    asset_id: str = "-1",
    is_system_message: bool = False,
    is_final_segment: bool = True,
) -> TTSOutputMessage:
    return TTSOutputMessage(
        audio_path=audio_path,
        name=name,
        text=text,
        asset_id=asset_id,
        is_system_message=is_system_message,
        is_final_segment=is_final_segment,
    )


# =========================================================================
# Fixtures — shared across all test files
# =========================================================================


@pytest.fixture
def mock_tts_adapter():
    return MockTTSAdapter()


@pytest.fixture
def mock_t2i_adapter():
    return MockT2IAdapter()


@pytest.fixture
def mock_asr_adapter():
    return MockASRAdapter(language="zh")


@pytest.fixture
def sample_app_config():
    """A fully valid AppConfig built from factory functions."""
    return make_app_config()


@pytest.fixture
def sample_agent_dialog():
    return make_agent_dialog()


@pytest.fixture
def sample_tts_output():
    return make_tts_output()


@pytest.fixture
def sample_user_input():
    return make_user_input()


# =========================================================================
# AppRuntime fixture — for tests that need the global singleton
# =========================================================================

from core.runtime.app_runtime import AppRuntime, set_app_runtime


class MockAgentBackend:
    def __init__(self, response: str = '[{"character_name":"TestChar","speech":"Mock reply.","emotion":"neutral","asset_id":"-1"}]') -> None:
        self.response = response
        self.calls: list[dict] = []
        self.oneshot_calls: list[dict] = []
        self.interrupted = False

    def chat(self, user_text: str, system_prompt: str = "", *, context=None, stream: bool = True):
        self.calls.append(
            {
                "user_text": user_text,
                "system_prompt": system_prompt,
                "context": context,
                "stream": stream,
            }
        )
        if stream:
            return iter([self.response])
        return self.response

    def oneshot(self, prompt: str, system_prompt: str = "", tools: bool = False) -> str:
        self.oneshot_calls.append({"prompt": prompt, "system_prompt": system_prompt, "tools": tools})
        return self.response

    def interrupt(self) -> None:
        self.interrupted = True

    def reset_session(self) -> None:
        self.calls.clear()


@pytest.fixture
def mock_agent_backend():
    return MockAgentBackend()


@pytest.fixture
def mock_app_runtime(mock_agent_backend, sample_app_config, tmp_path):
    """Set up a minimal AppRuntime as the global singleton; cleaned up after test.

    All queues are real queue.Queue instances so worker-like tests can push/pop.
    """
    from services.config.config_manager import ConfigManager

    # Build a ConfigManager that returns our sample config
    config_mgr = MagicMock(spec=ConfigManager)
    config_mgr.config = sample_app_config
    active_name = (
        sample_app_config.system_config.active_character_name
        or sample_app_config.characters[0].name
        if sample_app_config.characters
        else "here_system"
    )
    active_name_holder = {"name": active_name}

    def _get_character_by_name(name: str):
        wanted = str(name or "").strip().lower()
        for character in sample_app_config.characters:
            if str(character.name or "").strip().lower() == wanted:
                return character
        return None

    def _resolve_active_character_name():
        names = [str(c.name or "").strip() for c in sample_app_config.characters if str(c.name or "").strip()]
        active = str(active_name_holder["name"] or "").strip()
        if active in names:
            return active
        return names[0] if names else "here_system"

    def _set_active_character_name(name: str):
        active_name_holder["name"] = str(name or "").strip()
        sample_app_config.system_config.active_character_name = active_name_holder["name"]
        return _resolve_active_character_name()

    def _rename_character(old_name: str, new_name: str):
        target = _get_character_by_name(old_name)
        if target is None or _get_character_by_name(new_name) is not None:
            return _resolve_active_character_name()
        target.name = str(new_name or "").strip()
        if active_name_holder["name"] == old_name:
            active_name_holder["name"] = target.name
            sample_app_config.system_config.active_character_name = target.name
        return target.name

    config_mgr.get_character_by_name.side_effect = _get_character_by_name
    config_mgr.resolve_active_character_name.side_effect = _resolve_active_character_name
    config_mgr.set_active_character_name.side_effect = _set_active_character_name
    config_mgr.rename_character.side_effect = _rename_character

    ui_update_manager = MagicMock()

    from core.runtime.app_runtime import ActiveCharacterState

    rt = AppRuntime(
        config=config_mgr,
        ui_update_manager=ui_update_manager,
        agent_backend=mock_agent_backend,
        tts_manager=None,
        t2i_manager=None,
        bgm_list=[],
        user_input_queue=Queue(),
        tts_queue=Queue(),
        audio_path_queue=Queue(),
        text_processor=MagicMock(),
        opencc=MagicMock(),
    )
    rt.active_character = ActiveCharacterState(config_mgr)
    from internal_agent.context import AgentMemoryStore
    rt.agent_memory_store = AgentMemoryStore(tmp_path / "agent_memory")
    # opencc.convert returns input unchanged by default
    rt.opencc.convert.side_effect = lambda s: s

    set_app_runtime(rt)
    yield rt
    set_app_runtime(None)


# =========================================================================
# Custom options
# =========================================================================

def pytest_addoption(parser):
    parser.addoption(
        "--run-ui",
        action="store_true",
        default=False,
        help="Run tests that require a real UI (ChatUIWindow + Qt signalling)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "ui: mark test as requiring a real Qt UI (deselect with '-m \"not ui\"')",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-ui"):
        return  # allow all
    skip_ui = pytest.mark.skip(reason="need --run-ui flag to run UI tests")
    for item in items:
        if "ui" in item.keywords:
            item.add_marker(skip_ui)
