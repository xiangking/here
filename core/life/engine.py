from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from core.timezone import now_in_timezone, resolve_timezone
from internal_agent.context import AgentMemoryStore


DEFAULT_TIMEZONE = "Asia/Shanghai"


@dataclass(frozen=True)
class LifeBlock:
    start: str
    end: str
    activity: str
    location: str = ""
    goal: str = ""
    mood: str = "平静"
    availability: str = "可聊天"
    interruptibility: str = "medium"
    reply_style: str = "自然回应，必要时轻轻带到自己正在做的事。"
    emotion_hint: str = "neutral"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LifeBlock":
        return cls(
            start=str(data.get("start") or "00:00"),
            end=str(data.get("end") or "23:59"),
            activity=str(data.get("activity") or "自由活动"),
            location=str(data.get("location") or ""),
            goal=str(data.get("goal") or ""),
            mood=str(data.get("mood") or "平静"),
            availability=str(data.get("availability") or "可聊天"),
            interruptibility=str(data.get("interruptibility") or "medium"),
            reply_style=str(data.get("reply_style") or "自然回应，必要时轻轻带到自己正在做的事。"),
            emotion_hint=str(data.get("emotion_hint") or "neutral"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "start": self.start,
            "end": self.end,
            "activity": self.activity,
            "location": self.location,
            "goal": self.goal,
            "mood": self.mood,
            "availability": self.availability,
            "interruptibility": self.interruptibility,
            "reply_style": self.reply_style,
            "emotion_hint": self.emotion_hint,
        }


@dataclass
class DailyLifePlan:
    date: str
    timezone: str = DEFAULT_TIMEZONE
    day_theme: str = "普通的一天"
    blocks: list[LifeBlock] = field(default_factory=list)
    pending_promises: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    reflections: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DailyLifePlan":
        return cls(
            date=str(data.get("date") or ""),
            timezone=str(data.get("timezone") or DEFAULT_TIMEZONE),
            day_theme=str(data.get("day_theme") or "普通的一天"),
            blocks=[
                LifeBlock.from_dict(item)
                for item in data.get("blocks", [])
                if isinstance(item, dict)
            ],
            pending_promises=[
                str(item).strip()
                for item in data.get("pending_promises", [])
                if str(item).strip()
            ],
            observations=[
                str(item).strip()
                for item in data.get("observations", [])
                if str(item).strip()
            ],
            reflections=[
                str(item).strip()
                for item in data.get("reflections", [])
                if str(item).strip()
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "timezone": self.timezone,
            "day_theme": self.day_theme,
            "blocks": [block.to_dict() for block in self.blocks],
            "pending_promises": list(self.pending_promises),
            "observations": list(self.observations),
            "reflections": list(self.reflections),
        }


class LifeEngine:
    """Small daily-life layer that feeds only the current activity to chat."""

    def __init__(
        self,
        memory_store: AgentMemoryStore | None = None,
        *,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        self.memory_store = memory_store or AgentMemoryStore()
        self.timezone = timezone or DEFAULT_TIMEZONE

    def today(self, now: datetime | None = None) -> date:
        tz = resolve_timezone(self.timezone)
        return (now or datetime.now(tz)).astimezone(tz).date()

    def plan_path(self, character_name: str, day: date | str) -> Path:
        day_s = day.isoformat() if isinstance(day, date) else str(day)
        return self.memory_store.agent_home(character_name) / "life" / f"{day_s}.json"

    def ensure_daily_plan(
        self,
        character: Any,
        *,
        now: datetime | None = None,
        agent_backend: Any | None = None,
        allow_llm_generate: bool = True,
        save_template_fallback: bool = True,
    ) -> DailyLifePlan:
        character_name = str(getattr(character, "name", "") or "角色").strip() or "角色"
        current_day = self.today(now)
        path = self.plan_path(character_name, current_day)
        loaded = self._load_plan(path)
        if loaded is not None and loaded.blocks:
            return loaded

        if allow_llm_generate:
            self._finalize_previous_day(character_name, current_day)
            plan = self._generate_plan(character, current_day, agent_backend=agent_backend)
        else:
            plan = self._template_plan(character, current_day)
        if save_template_fallback or allow_llm_generate:
            self._save_plan(character_name, plan)
        return plan

    def current_life_state(
        self,
        character: Any,
        *,
        now: datetime | None = None,
        agent_backend: Any | None = None,
        allow_llm_generate: bool = True,
    ) -> str:
        plan = self.ensure_daily_plan(
            character,
            now=now,
            agent_backend=agent_backend,
            allow_llm_generate=allow_llm_generate,
        )
        current = now or now_in_timezone(plan.timezone or self.timezone)
        block = self.block_at(plan, current)
        if block is None:
            return ""
        return self.render_life_state(plan, block)

    def observe_user_message(
        self,
        character: Any,
        user_text: str,
        *,
        now: datetime | None = None,
        agent_backend: Any | None = None,
        allow_llm_generate: bool = True,
    ) -> DailyLifePlan:
        plan = self.ensure_daily_plan(
            character,
            now=now,
            agent_backend=agent_backend,
            allow_llm_generate=allow_llm_generate,
        )
        text = str(user_text or "").strip()
        if not text:
            return plan
        character_name = str(getattr(character, "name", "") or "角色").strip() or "角色"
        changed = False
        observation = self._compact_observation(text, now or now_in_timezone(plan.timezone or self.timezone))
        if observation and observation not in plan.observations:
            plan.observations.append(observation)
            plan.observations = plan.observations[-20:]
            changed = True
        promise = self._extract_promise(text)
        if promise and promise not in plan.pending_promises:
            plan.pending_promises.append(promise)
            changed = True
            self._append_unique_memory(character_name, promise)
        if changed:
            self._save_plan(character_name, plan)
        return plan

    def block_at(self, plan: DailyLifePlan, moment: datetime | time) -> LifeBlock | None:
        current = moment.timetz().replace(tzinfo=None) if isinstance(moment, datetime) else moment
        minutes = current.hour * 60 + current.minute
        fallback: LifeBlock | None = None
        for block in plan.blocks:
            start = _parse_hhmm(block.start)
            end = _parse_hhmm(block.end)
            if start is None or end is None:
                continue
            start_m = start.hour * 60 + start.minute
            end_m = end.hour * 60 + end.minute
            if end_m <= start_m:
                if minutes >= start_m or minutes < end_m:
                    return block
            elif start_m <= minutes < end_m:
                return block
            fallback = block
        return fallback

    def render_life_state(self, plan: DailyLifePlan, block: LifeBlock) -> str:
        lines = [
            "【当前生活状态】",
            f"现在她正在：{block.activity}",
        ]
        if block.location:
            lines.append(f"地点：{block.location}")
        if block.goal:
            lines.append(f"这段时间的目标：{block.goal}")
        lines.append(f"心情/精力：{block.mood}")
        lines.append(f"可联系状态：{block.availability}；被打断程度：{block.interruptibility}")
        lines.append(f"回复方式：{block.reply_style}")
        if plan.pending_promises:
            lines.append("和用户相关的近期约定：" + "；".join(plan.pending_promises[-2:]))
        lines.append("不要主动展开完整日程；只有当前对话需要时，才自然透露正在做的事。")
        return "\n".join(lines)

    def render_daily_plan(self, plan: DailyLifePlan) -> str:
        lines = [
            f"日期：{plan.date}",
            f"时区：{plan.timezone}",
            f"主题：{plan.day_theme}",
            "",
            "日程：",
        ]
        if not plan.blocks:
            lines.append("暂无日程。")
        for block in plan.blocks:
            lines.append(f"- {block.start}-{block.end}  {block.activity}")
            details = []
            if block.location:
                details.append(f"地点：{block.location}")
            if block.goal:
                details.append(f"目标：{block.goal}")
            if block.mood:
                details.append(f"心情：{block.mood}")
            if block.availability:
                details.append(f"联系状态：{block.availability}")
            if block.interruptibility:
                details.append(f"打断程度：{block.interruptibility}")
            if block.reply_style:
                details.append(f"回复方式：{block.reply_style}")
            if details:
                lines.append("  " + "；".join(details))
        if plan.pending_promises:
            lines.extend(["", "近期约定："])
            lines.extend(f"- {item}" for item in plan.pending_promises)
        if plan.reflections:
            lines.extend(["", "反思："])
            lines.extend(f"- {item}" for item in plan.reflections)
        return "\n".join(lines).strip()

    def _generate_plan(
        self,
        character: Any,
        day: date,
        *,
        agent_backend: Any | None = None,
    ) -> DailyLifePlan:
        base = self._template_plan(character, day)
        if agent_backend is None or not hasattr(agent_backend, "oneshot"):
            return base
        prompt = self._planner_prompt(character, base)
        try:
            raw = agent_backend.oneshot(
                prompt,
                system_prompt="你是日程 JSON 生成器。只输出一个 JSON 对象，不输出解释、Markdown、角色台词或聊天内容。",
                tools=False,
            )
            refined = self._parse_llm_plan(raw)
        except Exception:
            return base
        if not refined:
            return base
        return DailyLifePlan(
            date=base.date,
            timezone=base.timezone,
            day_theme=refined.get("day_theme") or base.day_theme,
            blocks=[
                LifeBlock.from_dict(item)
                for item in refined.get("blocks", [])
                if isinstance(item, dict)
            ]
            or base.blocks,
            pending_promises=base.pending_promises,
            observations=base.observations,
            reflections=base.reflections,
        )

    def _template_plan(self, character: Any, day: date) -> DailyLifePlan:
        profile = getattr(character, "character_profile", {}) or {}
        identity = profile.get("identity") if isinstance(profile.get("identity"), dict) else {}
        preferences = profile.get("preferences") if isinstance(profile.get("preferences"), dict) else {}
        life = profile.get("life") if isinstance(profile.get("life"), dict) else {}
        occupation = str(
            life.get("occupation")
            or identity.get("occupation")
            or "自由职业者"
        ).strip()
        workplace = str(life.get("workplace") or identity.get("life_status") or "自己的房间").strip()
        routine = str(life.get("routine_preference") or "").strip()
        hobbies = _join_list(life.get("hobbies") or preferences.get("hobbies")) or "整理自己的小事"
        night_owl = any(word in routine for word in ("夜", "晚睡", "夜猫", "夜型")) or any(
            word in str(getattr(character, "character_setting", "") or "")
            for word in ("夜聊", "晚睡", "夜猫")
        )
        work_label = _work_label(occupation)
        work_location = workplace if workplace else "工作地点"
        if night_owl:
            blocks = [
                LifeBlock("00:00", "02:00", "睡前放松和回消息", "床边", "把白天没说完的话慢慢收尾", "柔软但有点困", "适合轻声聊天", "low", "像视频通话快睡着那样短短回应。", "happy"),
                LifeBlock("02:00", "10:00", "睡觉", "卧室", "恢复精力", "熟睡", "通常不会主动展开聊天", "high", "如果被叫醒，迷糊但温柔地回应。", "neutral"),
                LifeBlock("10:00", "11:00", "起床和早午餐", "住处", "让自己进入状态", "慢慢清醒", "可聊天", "medium", "带一点刚醒的生活感。", "neutral"),
                LifeBlock("11:00", "15:00", work_label, work_location, f"推进{occupation}相关事项", "专注", "能短暂回复", "high", "先回应用户，再自然说明自己正在专注。", "thinking"),
                LifeBlock("15:00", "16:00", "休息、吃点东西", "附近", "补充精力", "放松", "很适合聊天", "low", "更愿意多聊几句。", "happy"),
                LifeBlock("16:00", "20:00", work_label, work_location, "完成当天最重要的一段工作", "认真", "能回消息但不宜太长", "high", "温柔设边界，像把视频挂着继续做事。", "thinking"),
                LifeBlock("20:00", "22:00", "晚饭和个人时间", "住处", "从工作里抽离", "松弛", "适合聊天", "low", "自然分享晚饭、路上或房间里的细节。", "happy"),
                LifeBlock("22:00", "00:00", f"做自己的兴趣：{hobbies}", "住处", "照顾自己的心情", "亲近、安静", "很适合聊天", "low", "像夜间视频聊天一样亲近但不喧闹。", "happy"),
            ]
        else:
            blocks = [
                LifeBlock("00:00", "07:00", "睡觉", "卧室", "恢复精力", "熟睡", "通常不会主动展开聊天", "high", "如果被叫醒，困倦但不责怪用户。", "neutral"),
                LifeBlock("07:00", "08:00", "起床、洗漱和早餐", "住处", "准备开始一天", "清醒中", "可聊天", "medium", "带一点早晨生活感。", "neutral"),
                LifeBlock("08:00", "09:00", "通勤或整理工作区", work_location, "进入工作状态", "平稳", "能短暂回复", "medium", "简短回应，必要时提到正在赶路或整理东西。", "neutral"),
                LifeBlock("09:00", "12:00", work_label, work_location, f"推进{occupation}相关事项", "专注", "能短暂回复", "high", "先回应用户，再自然说明自己正在专注。", "thinking"),
                LifeBlock("12:00", "13:00", "午饭和休息", "附近", "补充精力", "放松", "很适合聊天", "low", "更愿意多聊几句。", "happy"),
                LifeBlock("13:00", "18:00", work_label, work_location, "完成当天主要任务", "认真", "能回消息但不宜太长", "high", "温柔设边界，像把视频挂着继续做事。", "thinking"),
                LifeBlock("18:00", "20:00", "晚饭、回家和放空", "住处", "从工作里抽离", "松弛", "适合聊天", "low", "自然分享路上或房间里的细节。", "happy"),
                LifeBlock("20:00", "23:00", f"做自己的兴趣：{hobbies}", "住处", "照顾自己的心情", "亲近", "很适合聊天", "low", "像晚间聊天一样更柔和、更有陪伴感。", "happy"),
                LifeBlock("23:00", "00:00", "睡前收尾", "床边", "准备休息", "有点困", "适合短聊", "medium", "语气放轻，不把话题铺太大。", "neutral"),
            ]
        return DailyLifePlan(
            date=day.isoformat(),
            timezone=self.timezone,
            day_theme=f"围绕{occupation}和自我照顾的一天",
            blocks=blocks,
        )

    def _planner_prompt(self, character: Any, base: DailyLifePlan) -> str:
        name = str(getattr(character, "name", "") or "这个角色")
        profile = getattr(character, "character_profile", {}) or {}
        life = profile.get("life") if isinstance(profile.get("life"), dict) else {}
        return (
            "请为 here 桌面伴侣角色润色一天的生活安排，只输出 JSON。\n"
            "要求：保留 blocks 的 start/end 数量和大致时间，不写台词，不写完整故事；"
            "让活动更符合角色职业、性格、长期目标和与用户像聊天/视频通话联系的关系。\n"
            f"角色名：{name}\n"
            f"角色设定：{str(getattr(character, 'character_setting', '') or '')[:1200]}\n"
            f"生活设定：{json.dumps(life, ensure_ascii=False)}\n"
            f"基础日程：{json.dumps(base.to_dict(), ensure_ascii=False)}\n"
            "输出形如：{\"day_theme\":\"...\",\"blocks\":[{\"start\":\"09:00\",\"end\":\"12:00\","
            "\"activity\":\"...\",\"location\":\"...\",\"goal\":\"...\",\"mood\":\"...\","
            "\"availability\":\"...\",\"interruptibility\":\"low|medium|high\","
            "\"reply_style\":\"...\",\"emotion_hint\":\"neutral|happy|thinking|surprised|sad|angry\"}]}"
        )

    def _parse_llm_plan(self, raw: str) -> dict[str, Any] | None:
        text = str(raw or "").strip()
        if not text:
            return None
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            text = match.group(0)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        blocks = data.get("blocks")
        if not isinstance(blocks, list):
            return None
        valid_blocks = [
            item
            for item in blocks
            if isinstance(item, dict)
            and str(item.get("start") or "").strip()
            and str(item.get("end") or "").strip()
            and str(item.get("activity") or "").strip()
        ]
        if not valid_blocks:
            return None
        data["blocks"] = valid_blocks
        return data

    def _load_plan(self, path: Path) -> DailyLifePlan | None:
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        return DailyLifePlan.from_dict(raw)

    def _save_plan(self, character_name: str, plan: DailyLifePlan) -> None:
        path = self.plan_path(character_name, plan.date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _finalize_previous_day(self, character_name: str, current_day: date) -> None:
        previous_day = current_day - timedelta(days=1)
        path = self.plan_path(character_name, previous_day)
        plan = self._load_plan(path)
        if plan is None or plan.reflections:
            return
        reflections = self._build_reflections(plan)
        if not reflections:
            return
        plan.reflections = reflections
        self._save_plan(character_name, plan)
        for reflection in reflections:
            self._append_unique_memory(character_name, reflection)

    def _build_reflections(self, plan: DailyLifePlan) -> list[str]:
        reflections: list[str] = []
        for promise in plan.pending_promises:
            reflections.append(f"{plan.date} 的生活约定：{promise}")
        if plan.observations:
            reflections.append(f"{plan.date} 用户主动联系过她；最近一次记录是：{plan.observations[-1]}")
        if plan.day_theme:
            reflections.append(f"{plan.date} 对她来说是{plan.day_theme}。")
        clean: list[str] = []
        for item in reflections:
            text = str(item).strip()
            if text and text not in clean:
                clean.append(text)
        return clean[:5]

    def _compact_observation(self, text: str, now: datetime) -> str:
        if len(text) > 120:
            text = text[:117] + "..."
        return f"{now.strftime('%H:%M')} 用户说：{text}"

    def _extract_promise(self, text: str) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        if not clean:
            return ""
        promise_markers = (
            "今晚",
            "明天",
            "早上",
            "中午",
            "下午",
            "晚上",
            "周末",
            "下次",
            "待会",
            "等会",
            "一起",
            "约",
            "提醒",
            "记得",
            "陪我",
            "找你",
            "聊",
        )
        if not any(marker in clean for marker in promise_markers):
            return ""
        if len(clean) > 80:
            clean = clean[:77] + "..."
        return f"用户近期约定/请求：{clean}"

    def _append_unique_memory(self, character_name: str, memory: str) -> None:
        memories = self.memory_store.read_character_memories(character_name)
        if memory and memory not in memories:
            self.memory_store.append_character_memory(character_name, memory)


def _parse_hhmm(value: str) -> time | None:
    try:
        hour_s, minute_s = str(value).split(":", 1)
        hour = int(hour_s)
        minute = int(minute_s)
    except (TypeError, ValueError):
        return None
    if hour == 24 and minute == 0:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour=hour, minute=minute)


def _join_list(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _work_label(occupation: str) -> str:
    lowered = occupation.lower()
    if any(word in occupation for word in ("学生", "研究生", "大学", "高中")):
        return "上课、自习和处理课题"
    if any(word in occupation for word in ("画", "插画", "设计", "创作", "写")):
        return "创作和接单工作"
    if any(word in occupation for word in ("程序", "开发", "工程", "代码")) or "developer" in lowered:
        return "写代码和处理项目"
    if any(word in occupation for word in ("店", "咖啡", "服务")):
        return "店里的工作"
    return f"{occupation}的日常工作"
