from __future__ import annotations

from datetime import datetime
from queue import Queue
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from services.config.schema import AppConfig
from internal_agent.context import AgentMemoryStore
from core.life import LifeEngine
from core.proactive import ContactPlanEngine, ProactiveContactScheduler
from test.conftest import make_app_config, make_character


class FakeBackend:
    system_prompt = "role"

    def __init__(self) -> None:
        self.oneshot_calls: list[dict] = []

    def oneshot(self, prompt: str, system_prompt: str = "", tools: bool = False) -> str:
        self.oneshot_calls.append({"prompt": prompt, "system_prompt": system_prompt, "tools": tools})
        if "主动联系消息生成器" in system_prompt:
            return '{"character_name":"Alice","speech":"我午休的时候突然想起你，来看看你。","emotion":"happy","system_action":null}'
        return "{}"


def _config(app_config: AppConfig):
    cfg = MagicMock()
    cfg.config = app_config
    cfg.get_character_by_name.side_effect = lambda name: next(
        (c for c in app_config.characters if c.name == name),
        None,
    )
    return cfg


class Route:
    def __init__(self, channel: str = "desktop_chat", allowed: bool = True):
        self.channel = channel
        self.allowed = allowed
        self.reason = "test"
        self.requires_confirmation = False


class StaticRouter:
    def __init__(self, channel: str):
        self.channel = channel
        self.routes = []

    def route(self, *, now=None):
        self.routes.append(now)
        return Route(self.channel)


class RecordingAdapters:
    def __init__(self, fail_external: bool = False):
        self.fail_external = fail_external
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        if message.target_channel != "desktop_chat" and self.fail_external:
            return type("Result", (), {"status": "failed"})()
        return type("Result", (), {"status": "sent"})()


def test_scheduler_disabled_does_not_generate_contact_plans(tmp_path):
    alice = make_character(name="Alice")
    app_config = make_app_config(characters=[alice])
    cfg = _config(app_config)
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    contact_engine = ContactPlanEngine(store, life_engine)
    out = Queue()
    scheduler = ProactiveContactScheduler(
        config_manager=cfg,
        life_engine=life_engine,
        contact_engine=contact_engine,
        agent_backend=FakeBackend(),
        active_character_name=lambda: "Alice",
        emit_dialog=out.put,
        enabled_getter=lambda: False,
        memory_store=store,
    )

    assert scheduler.tick(datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai"))) is False
    assert not (store.agent_home("Alice") / "life_contacts").exists()
    assert out.empty()


def test_scheduler_generates_all_plans_but_only_active_character_speaks(tmp_path):
    alice = make_character(name="Alice")
    bob = make_character(name="Bob")
    app_config = make_app_config(characters=[alice, bob])
    cfg = _config(app_config)
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    contact_engine = ContactPlanEngine(store, life_engine)
    backend = FakeBackend()
    out = Queue()
    scheduler = ProactiveContactScheduler(
        config_manager=cfg,
        life_engine=life_engine,
        contact_engine=contact_engine,
        agent_backend=backend,
        active_character_name=lambda: "Alice",
        emit_dialog=out.put,
        enabled_getter=lambda: True,
        memory_store=store,
    )
    now = datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert scheduler.tick(now) is True

    assert (store.agent_home("Alice") / "life_contacts" / "2026-05-26.json").is_file()
    assert (store.agent_home("Bob") / "life_contacts" / "2026-05-26.json").is_file()
    item = out.get_nowait()
    assert item.name == "Alice"
    assert "午休" in item.text


def test_recent_user_message_suppresses_due_contact(tmp_path):
    alice = make_character(name="Alice")
    app_config = make_app_config(characters=[alice])
    cfg = _config(app_config)
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    contact_engine = ContactPlanEngine(store, life_engine)
    out = Queue()
    scheduler = ProactiveContactScheduler(
        config_manager=cfg,
        life_engine=life_engine,
        contact_engine=contact_engine,
        agent_backend=FakeBackend(),
        active_character_name=lambda: "Alice",
        emit_dialog=out.put,
        enabled_getter=lambda: True,
        memory_store=store,
    )
    now = datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
    scheduler.note_user_message(now)

    assert scheduler.tick(now) is False
    assert out.empty()


def test_scheduler_uses_delivery_router_for_external_channel(tmp_path):
    alice = make_character(name="Alice")
    app_config = make_app_config(characters=[alice])
    cfg = _config(app_config)
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    contact_engine = ContactPlanEngine(store, life_engine)
    out = Queue()
    adapters = RecordingAdapters()
    scheduler = ProactiveContactScheduler(
        config_manager=cfg,
        life_engine=life_engine,
        contact_engine=contact_engine,
        agent_backend=FakeBackend(),
        active_character_name=lambda: "Alice",
        emit_dialog=out.put,
        enabled_getter=lambda: True,
        delivery_router=StaticRouter("telegram"),
        delivery_adapters=adapters,
        memory_store=store,
    )

    assert scheduler.tick(datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai"))) is True

    assert out.empty()
    assert adapters.messages[0].target_channel == "telegram"
    assert adapters.messages[0].character_name == "Alice"
    plan = contact_engine.ensure_contact_plan(alice, now=datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert plan.contacts[0].delivery_channel == "telegram"
    assert plan.contacts[0].delivery_status == "sent"


def test_scheduler_does_not_generate_audio_for_external_channel_by_default(tmp_path):
    alice = make_character(name="Alice")
    app_config = make_app_config(characters=[alice])
    cfg = _config(app_config)
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    contact_engine = ContactPlanEngine(store, life_engine)
    adapters = RecordingAdapters()
    audio_calls = []
    scheduler = ProactiveContactScheduler(
        config_manager=cfg,
        life_engine=life_engine,
        contact_engine=contact_engine,
        agent_backend=FakeBackend(),
        active_character_name=lambda: "Alice",
        emit_dialog=lambda _: None,
        enabled_getter=lambda: True,
        delivery_router=StaticRouter("telegram"),
        delivery_adapters=adapters,
        audio_generator=lambda name, text: audio_calls.append((name, text)) or "/tmp/voice.wav",
        memory_store=store,
    )

    assert scheduler.tick(datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai"))) is True

    assert audio_calls == []
    assert adapters.messages[0].audio_path == ""


def test_scheduler_generates_audio_for_external_channel_when_enabled(tmp_path):
    alice = make_character(name="Alice")
    app_config = make_app_config(characters=[alice])
    app_config.system_config.external_delivery_audio_enabled = True
    cfg = _config(app_config)
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    contact_engine = ContactPlanEngine(store, life_engine)
    adapters = RecordingAdapters()
    audio_calls = []
    scheduler = ProactiveContactScheduler(
        config_manager=cfg,
        life_engine=life_engine,
        contact_engine=contact_engine,
        agent_backend=FakeBackend(),
        active_character_name=lambda: "Alice",
        emit_dialog=lambda _: None,
        enabled_getter=lambda: True,
        delivery_router=StaticRouter("telegram"),
        delivery_adapters=adapters,
        audio_generator=lambda name, text: audio_calls.append((name, text)) or "/tmp/voice.wav",
        memory_store=store,
    )

    assert scheduler.tick(datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai"))) is True

    assert audio_calls[0][0] == "Alice"
    assert "午休" in audio_calls[0][1]
    assert adapters.messages[0].audio_path == "/tmp/voice.wav"


def test_scheduler_attaches_photo_only_when_contact_has_photo_intent(tmp_path):
    alice = make_character(name="Alice")
    app_config = make_app_config(characters=[alice])
    app_config.system_config.proactive_photo_enabled = True
    cfg = _config(app_config)
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    contact_engine = ContactPlanEngine(store, life_engine)
    adapters = RecordingAdapters()
    photo_calls = []
    scheduler = ProactiveContactScheduler(
        config_manager=cfg,
        life_engine=life_engine,
        contact_engine=contact_engine,
        agent_backend=FakeBackend(),
        active_character_name=lambda: "Alice",
        emit_dialog=lambda _: None,
        enabled_getter=lambda: True,
        delivery_router=StaticRouter("telegram"),
        delivery_adapters=adapters,
        photo_generator=lambda request: photo_calls.append(request) or "/tmp/alice_selfie.png",
        memory_store=store,
    )

    assert scheduler.tick(datetime(2026, 5, 26, 20, 20, tzinfo=ZoneInfo("Asia/Shanghai"))) is True

    assert photo_calls
    assert "当前生活状态" in photo_calls[0].life_state
    assert adapters.messages[0].image_path == "/tmp/alice_selfie.png"
    plan = contact_engine.ensure_contact_plan(alice, now=datetime(2026, 5, 26, 20, 20, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert plan.contacts[-1].photo_status == "generated"
    assert plan.contacts[-1].photo_path == "/tmp/alice_selfie.png"


def test_scheduler_does_not_attach_photo_when_disabled(tmp_path):
    alice = make_character(name="Alice")
    app_config = make_app_config(characters=[alice])
    app_config.system_config.proactive_photo_enabled = False
    cfg = _config(app_config)
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    contact_engine = ContactPlanEngine(store, life_engine)
    adapters = RecordingAdapters()
    photo_calls = []
    scheduler = ProactiveContactScheduler(
        config_manager=cfg,
        life_engine=life_engine,
        contact_engine=contact_engine,
        agent_backend=FakeBackend(),
        active_character_name=lambda: "Alice",
        emit_dialog=lambda _: None,
        enabled_getter=lambda: True,
        delivery_router=StaticRouter("telegram"),
        delivery_adapters=adapters,
        photo_generator=lambda request: photo_calls.append(request) or "/tmp/alice_selfie.png",
        memory_store=store,
    )

    assert scheduler.tick(datetime(2026, 5, 26, 20, 20, tzinfo=ZoneInfo("Asia/Shanghai"))) is True

    assert photo_calls == []
    assert adapters.messages[0].image_path == ""


def test_scheduler_falls_back_to_desktop_when_external_delivery_fails(tmp_path):
    alice = make_character(name="Alice")
    app_config = make_app_config(characters=[alice])
    cfg = _config(app_config)
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    contact_engine = ContactPlanEngine(store, life_engine)
    adapters = RecordingAdapters(fail_external=True)
    scheduler = ProactiveContactScheduler(
        config_manager=cfg,
        life_engine=life_engine,
        contact_engine=contact_engine,
        agent_backend=FakeBackend(),
        active_character_name=lambda: "Alice",
        emit_dialog=lambda _: None,
        enabled_getter=lambda: True,
        delivery_router=StaticRouter("telegram"),
        delivery_adapters=adapters,
        memory_store=store,
    )

    assert scheduler.tick(datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai"))) is True

    assert [m.target_channel for m in adapters.messages] == ["telegram", "desktop_chat"]
    plan = contact_engine.ensure_contact_plan(alice, now=datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert plan.contacts[0].delivery_channel == "desktop_chat"
    assert plan.contacts[0].delivery_status == "sent"
    assert plan.contacts[0].delivery_reason.startswith("fallback_after_")


def test_scheduler_falls_back_when_external_daily_limit_reached(tmp_path):
    alice = make_character(name="Alice")
    app_config = make_app_config(characters=[alice])
    app_config.system_config.external_delivery_daily_limit = 0
    cfg = _config(app_config)
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    contact_engine = ContactPlanEngine(store, life_engine)
    adapters = RecordingAdapters()
    scheduler = ProactiveContactScheduler(
        config_manager=cfg,
        life_engine=life_engine,
        contact_engine=contact_engine,
        agent_backend=FakeBackend(),
        active_character_name=lambda: "Alice",
        emit_dialog=lambda _: None,
        enabled_getter=lambda: True,
        delivery_router=StaticRouter("telegram"),
        delivery_adapters=adapters,
        memory_store=store,
    )
    now = datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert scheduler.tick(now) is True

    assert [m.target_channel for m in adapters.messages] == ["desktop_chat"]
    plan = contact_engine.ensure_contact_plan(alice, now=now)
    assert plan.contacts[0].delivery_channel == "desktop_chat"
    assert plan.contacts[0].delivery_reason == "external_daily_limit_fallback"
