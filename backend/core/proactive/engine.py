from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.timezone import resolve_timezone
from internal_agent.context import AgentMemoryStore
from core.life import DEFAULT_TIMEZONE, DailyLifePlan, LifeBlock, LifeEngine
from core.proactive.models import ContactPlanItem, DailyContactPlan


class ContactPlanEngine:
    """Generate and persist daily proactive-contact plans."""

    def __init__(
        self,
        memory_store: AgentMemoryStore | None = None,
        life_engine: LifeEngine | None = None,
        *,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        self.memory_store = memory_store or AgentMemoryStore()
        self.life_engine = life_engine or LifeEngine(self.memory_store, timezone=timezone)
        self.timezone = timezone or DEFAULT_TIMEZONE

    def today(self, now: datetime | None = None) -> date:
        tz = resolve_timezone(self.timezone)
        return (now or datetime.now(tz)).astimezone(tz).date()

    def plan_path(self, character_name: str, day: date | str) -> Path:
        day_s = day.isoformat() if isinstance(day, date) else str(day)
        return self.memory_store.agent_home(character_name) / "life_contacts" / f"{day_s}.json"

    def ensure_contact_plan(
        self,
        character: Any,
        life_plan: DailyLifePlan | None = None,
        *,
        now: datetime | None = None,
        agent_backend: Any | None = None,
        allow_llm_generate: bool = True,
    ) -> DailyContactPlan:
        name = str(getattr(character, "name", "") or "角色").strip() or "角色"
        current_day = self.today(now)
        path = self.plan_path(name, current_day)
        loaded = self._load_plan(path)
        if loaded is not None:
            return loaded
        if life_plan is None:
            life_plan = self.life_engine.ensure_daily_plan(
                character,
                now=now,
                agent_backend=agent_backend,
                allow_llm_generate=allow_llm_generate,
            )
        plan = self._template_contact_plan(character, life_plan)
        if allow_llm_generate and agent_backend is not None and hasattr(agent_backend, "oneshot"):
            plan = self._refine_contact_plan(character, life_plan, plan, agent_backend)
        self._save_plan(name, plan)
        return plan

    def render_contact_plan(self, plan: DailyContactPlan) -> str:
        lines = [
            f"日期：{plan.date}",
            f"时区：{plan.timezone}",
            f"风格：{plan.contact_style}",
            f"今日上限：{plan.daily_contact_limit}",
            "",
            "可能联系你的时机：",
        ]
        if not plan.contacts:
            lines.append("暂无主动联系计划。")
        for item in plan.contacts:
            lines.append(f"- {item.window_start}-{item.window_end}  {item.intent or item.message_seed}")
            details = []
            if item.type:
                details.append(f"类型：{item.type}")
            if item.priority:
                details.append(f"优先级：{item.priority}")
            if item.status:
                details.append(f"状态：{item.status}")
            if item.skipped_reason:
                details.append(f"跳过原因：{item.skipped_reason}")
            if details:
                lines.append("  " + "；".join(details))
        return "\n".join(lines).strip()

    def mark_sent(self, character_name: str, plan: DailyContactPlan, item: ContactPlanItem, sent_at: datetime) -> None:
        item.status = "sent"
        item.sent_at = sent_at.isoformat()
        item.skipped_reason = None
        self._save_plan(character_name, plan)

    def mark_skipped(self, character_name: str, plan: DailyContactPlan, item: ContactPlanItem, reason: str) -> None:
        item.status = "skipped"
        item.skipped_reason = reason
        self._save_plan(character_name, plan)

    def mark_delivery_attempt(
        self,
        character_name: str,
        plan: DailyContactPlan,
        item: ContactPlanItem,
        *,
        channel: str,
        status: str,
        reason: str,
        attempted_at: datetime,
    ) -> None:
        item.delivery_channel = channel
        item.delivery_status = status
        item.delivery_reason = reason
        item.delivery_attempted_at = attempted_at.isoformat()
        self._save_plan(character_name, plan)

    def _template_contact_plan(self, character: Any, life_plan: DailyLifePlan) -> DailyContactPlan:
        profile = getattr(character, "character_profile", {}) or {}
        life = profile.get("life") if isinstance(profile.get("life"), dict) else {}
        style = str(life.get("proactive_style") or life.get("availability_style") or "").strip()
        contact_style = style or "温柔、克制，像在自己的生活间隙自然想起你。"
        memories = self.memory_store.read_character_memories(str(getattr(character, "name", "") or "角色"))[-4:]
        contacts = self._candidate_contacts(life_plan, memories)
        return DailyContactPlan(
            date=life_plan.date,
            timezone=life_plan.timezone or self.timezone,
            daily_contact_limit=_daily_limit_from_style(style),
            contact_style=contact_style,
            contacts=contacts[:3],
        )

    def _candidate_contacts(
        self,
        life_plan: DailyLifePlan,
        memories: list[str],
    ) -> list[ContactPlanItem]:
        candidates: list[ContactPlanItem] = []
        for block in life_plan.blocks:
            activity = block.activity
            start, end = _window_inside(block, minutes_after=15, window_minutes=45)
            block_id = f"{block.start}-{block.end}"
            lower = activity.lower()
            if any(word in activity for word in ("午饭", "休息", "吃点", "早午餐")):
                candidates.append(ContactPlanItem(
                    id=f"{_slug(block_id)}_checkin",
                    window_start=start,
                    window_end=end,
                    source_block_id=block_id,
                    type="check_in",
                    intent="休息时轻轻问候你，看看你今天过得怎么样。",
                    memory_basis=memories[-2:],
                    message_seed="问问你上午或现在的状态，语气轻，不追问太多。",
                    priority="medium",
                ))
            elif any(word in activity for word in ("晚饭", "个人时间", "兴趣", "睡前")):
                candidates.append(ContactPlanItem(
                    id=f"{_slug(block_id)}_share",
                    window_start=start,
                    window_end=end,
                    source_block_id=block_id,
                    type="share_moment",
                    intent="在自己的生活间隙分享一个小片刻，让你感觉她想起了你。",
                    memory_basis=memories[-2:],
                    message_seed="分享她此刻的小状态，再自然把话递给你。",
                    photo_intent="把此刻的地点、心情和正在做的小事拍成一张自然自拍，作为这次分享的附图。",
                    priority="medium",
                ))
            elif "sleep" in lower or "睡" in activity:
                continue
        if not candidates and life_plan.blocks:
            block = life_plan.blocks[-1]
            start, end = _window_inside(block, minutes_after=10, window_minutes=30)
            candidates.append(ContactPlanItem(
                id=f"{_slug(block.start + '-' + block.end)}_moment",
                window_start=start,
                window_end=end,
                source_block_id=f"{block.start}-{block.end}",
                type="share_moment",
                intent="找一个不打扰的时刻向用户分享近况。",
                memory_basis=memories[-2:],
                message_seed="短短说一句自己的近况，像自然想起用户。",
                photo_intent="如果此刻有值得分享的生活细节，可以附一张自然自拍。",
                priority="low",
            ))
        return _dedupe_contact_ids(candidates)

    def _refine_contact_plan(
        self,
        character: Any,
        life_plan: DailyLifePlan,
        base: DailyContactPlan,
        agent_backend: Any,
    ) -> DailyContactPlan:
        try:
            raw = agent_backend.oneshot(
                self._planner_prompt(character, life_plan, base),
                system_prompt="你是主动联系计划 JSON 生成器。只输出一个 JSON 对象，不输出解释、Markdown 或角色台词。",
                tools=False,
            )
            data = self._parse_plan(raw)
        except Exception:
            return base
        if not data:
            return base
        contacts = [
            ContactPlanItem.from_dict(item)
            for item in data.get("contacts", [])
            if isinstance(item, dict)
        ]
        return DailyContactPlan(
            date=base.date,
            timezone=base.timezone,
            daily_contact_limit=int(data.get("daily_contact_limit") or base.daily_contact_limit),
            contact_style=str(data.get("contact_style") or base.contact_style),
            contacts=contacts or base.contacts,
        )

    def _planner_prompt(self, character: Any, life_plan: DailyLifePlan, base: DailyContactPlan) -> str:
        profile = getattr(character, "character_profile", {}) or {}
        life = profile.get("life") if isinstance(profile.get("life"), dict) else {}
        memories = self.memory_store.read_character_memories(str(getattr(character, "name", "") or "角色"))[-6:]
        return (
            "请基于角色日程和少量记忆，润色今天主动联系用户的计划，只输出 JSON。\n"
            "要求：不要写最终台词；不要增加超过 3 个 contacts；主动联系要克制、像真人自然想起用户。\n"
            f"角色名：{getattr(character, 'name', '角色')}\n"
            f"生活设定：{json.dumps(life, ensure_ascii=False)}\n"
            f"近期记忆：{json.dumps(memories, ensure_ascii=False)}\n"
            f"今日日程：{json.dumps(life_plan.to_dict(), ensure_ascii=False)}\n"
            f"候选计划：{json.dumps(base.to_dict(), ensure_ascii=False)}\n"
            "输出形如：{\"daily_contact_limit\":2,\"contact_style\":\"...\",\"contacts\":["
            "{\"id\":\"...\",\"window_start\":\"12:20\",\"window_end\":\"13:10\","
            "\"source_block_id\":\"12:00-13:00\",\"type\":\"check_in|share_moment|promise_followup|goodnight_or_morning\","
            "\"intent\":\"...\",\"memory_basis\":[\"...\"],\"message_seed\":\"...\","
            "\"photo_intent\":\"可选；只有这次主动联系自然适合附自拍/当前状态照片时填写，否则留空\","
            "\"priority\":\"low|medium|high\",\"cooldown_hours\":4,"
            "\"skip_if_recent_user_message_minutes\":45,\"requires_user_available\":false,\"status\":\"pending\"}]}"
        )

    def _parse_plan(self, raw: str) -> dict[str, Any] | None:
        text = str(raw or "").strip()
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            text = match.group(0)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("contacts"), list):
            return None
        valid = [
            item for item in data["contacts"]
            if isinstance(item, dict)
            and str(item.get("window_start") or "").strip()
            and str(item.get("window_end") or "").strip()
            and (str(item.get("intent") or "").strip() or str(item.get("message_seed") or "").strip())
        ]
        if not valid:
            return None
        data["contacts"] = valid[:3]
        return data

    def _load_plan(self, path: Path) -> DailyContactPlan | None:
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        return DailyContactPlan.from_dict(raw)

    def _save_plan(self, character_name: str, plan: DailyContactPlan) -> None:
        path = self.plan_path(character_name, plan.date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def _daily_limit_from_style(style: str) -> int:
    text = str(style or "")
    if any(word in text for word in ("低频", "少", "克制")):
        return 1
    if any(word in text for word in ("高频", "黏", "亲密")):
        return 3
    return 2


def _window_inside(block: LifeBlock, *, minutes_after: int, window_minutes: int) -> tuple[str, str]:
    start = _parse_hhmm(block.start) or datetime.strptime("09:00", "%H:%M")
    base = datetime(2000, 1, 1, start.hour, start.minute) + timedelta(minutes=minutes_after)
    end = base + timedelta(minutes=window_minutes)
    return base.strftime("%H:%M"), end.strftime("%H:%M")


def _parse_hhmm(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%H:%M")
    except ValueError:
        return None


def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_") or "contact"


def _dedupe_contact_ids(items: list[ContactPlanItem]) -> list[ContactPlanItem]:
    seen: set[str] = set()
    out: list[ContactPlanItem] = []
    for item in items:
        base = item.id or "contact"
        item_id = base
        i = 2
        while item_id in seen:
            item_id = f"{base}_{i}"
            i += 1
        item.id = item_id
        seen.add(item_id)
        out.append(item)
    return out
