from __future__ import annotations

from unittest.mock import MagicMock

import core.timezone as timezone_helpers
from internal_agent.context import AgentMemoryStore
from core.life import DailyLifeScheduler, LifeEngine
from test.conftest import make_character


def test_daily_life_scheduler_generates_plans_for_characters(tmp_path):
    config = MagicMock()
    config.config.characters = [make_character(name="Alice")]
    backend = MagicMock()
    backend.oneshot.return_value = "{}"
    engine = LifeEngine(
        memory_store=AgentMemoryStore(tmp_path / "agent_memory"),
        timezone="Asia/Shanghai",
    )
    scheduler = DailyLifeScheduler(
        config_manager=config,
        life_engine=engine,
        agent_backend=backend,
    )

    scheduler.generate_today()

    assert backend.oneshot.called
    assert "只输出一个 JSON 对象" in backend.oneshot.call_args.kwargs["system_prompt"]
    life_dir = engine.memory_store.agent_home("Alice") / "life"
    assert any(path.name.endswith(".json") for path in life_dir.iterdir())


def test_daily_life_scheduler_falls_back_when_helper_returns_non_plan(tmp_path):
    config = MagicMock()
    config.config.characters = [make_character(name="Alice")]
    backend = MagicMock()
    backend.oneshot.return_value = '{"note": "设定和要求：只输出 JSON"}'
    engine = LifeEngine(
        memory_store=AgentMemoryStore(tmp_path / "agent_memory"),
        timezone="Asia/Shanghai",
    )
    scheduler = DailyLifeScheduler(
        config_manager=config,
        life_engine=engine,
        agent_backend=backend,
    )

    scheduler.generate_today()

    plan_path = next((engine.memory_store.agent_home("Alice") / "life").glob("*.json"))
    text = plan_path.read_text(encoding="utf-8")
    assert "设定和要求" not in text
    assert "blocks" in text


def test_daily_life_scheduler_midnight_delay_survives_missing_tzdata(monkeypatch, tmp_path):
    def missing_zoneinfo(_name: str):
        raise timezone_helpers.ZoneInfoNotFoundError("missing tzdata")

    monkeypatch.setattr(timezone_helpers, "ZoneInfo", missing_zoneinfo)
    timezone_helpers.clear_timezone_cache()
    config = MagicMock()
    config.config.characters = []
    scheduler = DailyLifeScheduler(
        config_manager=config,
        life_engine=LifeEngine(AgentMemoryStore(tmp_path / "agent_memory")),
        agent_backend=MagicMock(),
    )

    assert scheduler._seconds_until_next_midnight() > 0


def test_daily_life_scheduler_safe_generate_today_catches_unexpected_errors(tmp_path):
    config = MagicMock()
    config.config.characters = []
    scheduler = DailyLifeScheduler(
        config_manager=config,
        life_engine=LifeEngine(AgentMemoryStore(tmp_path / "agent_memory")),
        agent_backend=MagicMock(),
    )
    scheduler.generate_today = MagicMock(side_effect=RuntimeError("boom"))

    scheduler._safe_generate_today()
