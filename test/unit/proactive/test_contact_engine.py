from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from internal_agent.context import AgentMemoryStore
from core.life import LifeEngine
from core.proactive import ContactPlanEngine
from test.conftest import make_character


def test_contact_plan_is_saved_next_to_character_memory(tmp_path):
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    engine = ContactPlanEngine(store, life_engine)
    character = make_character(name="Alice")
    now = datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai"))

    life_plan = life_engine.ensure_daily_plan(character, now=now)
    plan = engine.ensure_contact_plan(character, life_plan, now=now, allow_llm_generate=False)

    assert plan.contacts
    path = engine.plan_path("Alice", "2026-05-26")
    assert path.is_file()
    assert "life_contacts" in str(path)


def test_contact_plan_reuses_existing_file(tmp_path):
    store = AgentMemoryStore(tmp_path / "agent_memory")
    life_engine = LifeEngine(store)
    engine = ContactPlanEngine(store, life_engine)
    character = make_character(name="Alice")
    now = datetime(2026, 5, 26, 12, 20, tzinfo=ZoneInfo("Asia/Shanghai"))

    first = engine.ensure_contact_plan(character, now=now, allow_llm_generate=False)
    path = engine.plan_path("Alice", first.date)
    before = path.read_text(encoding="utf-8")
    second = engine.ensure_contact_plan(character, now=now, allow_llm_generate=False)

    assert second.date == first.date
    assert path.read_text(encoding="utf-8") == before
