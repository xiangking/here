from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.config.schema import Character
from internal_agent.context import AgentMemoryStore
from core.life import LifeEngine
from core.sprite.character_profile import default_character_profile


def make_life_character(name: str = "Alice", occupation: str = "自学中的程序员") -> Character:
    profile = default_character_profile(name)
    profile["identity"]["occupation"] = occupation
    profile["life"] = {
        "occupation": occupation,
        "workplace": "共享工作室",
        "routine_preference": "早睡早起",
        "long_term_goals": ["完成作品集"],
        "social_circle": ["同事小林"],
        "availability_style": "忙时短回，晚上更愿意聊天",
    }
    return Character(
        name=name,
        color="#fff",
        sprite_prefix="alice",
        character_profile=profile,
        character_setting=f"{name} 是{occupation}，喜欢把视频通话挂着陪用户。",
    )


def test_daily_plan_is_reused_for_same_date(tmp_path):
    store = AgentMemoryStore(tmp_path)
    engine = LifeEngine(store)
    character = make_life_character()
    now = datetime(2026, 5, 25, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    first = engine.ensure_daily_plan(character, now=now)
    path = engine.plan_path("Alice", first.date)
    before = path.read_text(encoding="utf-8")
    second = engine.ensure_daily_plan(character, now=now)

    assert second.date == first.date
    assert path.read_text(encoding="utf-8") == before


def test_occupation_changes_template_work_blocks(tmp_path):
    store = AgentMemoryStore(tmp_path)
    engine = LifeEngine(store)
    programmer = make_life_character("Dev", "程序员")
    student = make_life_character("Student", "研究生")
    now = datetime(2026, 5, 25, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    dev_plan = engine.ensure_daily_plan(programmer, now=now)
    student_plan = engine.ensure_daily_plan(student, now=now)

    assert any("写代码" in block.activity for block in dev_plan.blocks)
    assert any("课题" in block.activity for block in student_plan.blocks)


def test_current_life_state_contains_only_current_block(tmp_path):
    store = AgentMemoryStore(tmp_path)
    engine = LifeEngine(store)
    character = make_life_character()
    now = datetime(2026, 5, 25, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    state = engine.current_life_state(character, now=now)

    assert "【私有运行状态】" in state
    assert "activity=" in state
    assert "写代码" in state
    assert "午饭" not in state
    assert "不得复述、表演或写入台词" in state


def test_user_promise_updates_life_plan_and_character_memory(tmp_path):
    store = AgentMemoryStore(tmp_path)
    engine = LifeEngine(store)
    character = make_life_character()
    now = datetime(2026, 5, 25, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    plan = engine.observe_user_message(character, "今晚陪我聊一会儿，记得提醒我喝水", now=now)

    assert plan.pending_promises == ["用户近期约定/请求：今晚陪我聊一会儿，记得提醒我喝水"]
    assert store.read_character_memories("Alice") == plan.pending_promises
    saved = engine.ensure_daily_plan(character, now=now)
    assert saved.pending_promises == plan.pending_promises


def test_new_day_finalizes_previous_day_reflections_to_memory(tmp_path):
    store = AgentMemoryStore(tmp_path)
    engine = LifeEngine(store)
    character = make_life_character()
    day_one = datetime(2026, 5, 25, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    day_two = datetime(2026, 5, 26, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    engine.observe_user_message(character, "今晚记得陪我聊一会儿", now=day_one)
    engine.ensure_daily_plan(character, now=day_two)

    previous = engine.ensure_daily_plan(character, now=day_one)
    assert previous.reflections
    memories = store.read_character_memories("Alice")
    assert "用户近期约定/请求：今晚记得陪我聊一会儿" in memories
    assert any("2026-05-25 的生活约定" in item for item in memories)
