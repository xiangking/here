from __future__ import annotations

import json
import threading
from datetime import datetime, time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from internal_agent.context import AgentMemoryStore
from core.delivery.models import DeliveryMessage
from core.life import DEFAULT_TIMEZONE, DailyLifePlan, LifeEngine
from core.proactive.engine import ContactPlanEngine
from core.proactive.models import ContactPlanItem, DailyContactPlan
from core.messaging.messages import AgentDialogMessage
from services.selfie import SelfieRequest


class ProactiveContactScheduler:
    """Generate plans for all characters, but only message from the active one."""

    def __init__(
        self,
        *,
        config_manager: Any,
        life_engine: LifeEngine,
        contact_engine: ContactPlanEngine,
        agent_backend: Any,
        active_character_name: Callable[[], str],
        emit_dialog: Callable[[AgentDialogMessage], None],
        enabled_getter: Callable[[], bool],
        delivery_router: Any | None = None,
        delivery_adapters: Any | None = None,
        audio_generator: Callable[[str, str], str] | None = None,
        photo_generator: Callable[[SelfieRequest], str] | None = None,
        timezone: str = DEFAULT_TIMEZONE,
        check_interval_seconds: float = 180.0,
        memory_store: AgentMemoryStore | None = None,
    ) -> None:
        self.config_manager = config_manager
        self.life_engine = life_engine
        self.contact_engine = contact_engine
        self.agent_backend = agent_backend
        self.active_character_name = active_character_name
        self.emit_dialog = emit_dialog
        self.enabled_getter = enabled_getter
        self.delivery_router = delivery_router
        self.delivery_adapters = delivery_adapters
        self.audio_generator = audio_generator
        self.photo_generator = photo_generator
        self.timezone = timezone or DEFAULT_TIMEZONE
        self.check_interval_seconds = max(10.0, float(check_interval_seconds))
        self.memory_store = memory_store or contact_engine.memory_store
        self.last_user_message_at: datetime | None = None
        self._generated_date: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._generate_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ProactiveContactScheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        generate_thread = self._generate_thread
        if generate_thread is not None and generate_thread.is_alive():
            generate_thread.join(timeout=2)

    def note_user_message(self, when: datetime | None = None) -> None:
        self.last_user_message_at = when or datetime.now(ZoneInfo(self.timezone))

    def request_generate_today(self) -> None:
        if not self.enabled_getter():
            return
        if self._generate_thread is not None and self._generate_thread.is_alive():
            return
        self._generate_thread = threading.Thread(
            target=self.generate_today,
            name="ProactiveContactPlanGenerate",
            daemon=True,
        )
        self._generate_thread.start()

    def generate_today(self, now: datetime | None = None) -> None:
        if not self.enabled_getter():
            return
        now = now or datetime.now(ZoneInfo(self.timezone))
        today = now.astimezone(ZoneInfo(self.timezone)).date().isoformat()
        if self._generated_date == today:
            return
        characters = list(getattr(self.config_manager.config, "characters", []) or [])
        for character in characters:
            if self._stop_event.is_set():
                return
            try:
                life_plan = self.life_engine.ensure_daily_plan(
                    character,
                    now=now,
                    agent_backend=self.agent_backend,
                    allow_llm_generate=True,
                )
                self.contact_engine.ensure_contact_plan(
                    character,
                    life_plan,
                    now=now,
                    agent_backend=self.agent_backend,
                    allow_llm_generate=True,
                )
            except Exception as exc:
                name = str(getattr(character, "name", "") or "角色")
                print(f"ProactiveContactScheduler: 生成 {name} 的主动联系计划失败: {exc}")
        self._generated_date = today

    def tick(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(ZoneInfo(self.timezone))
        if not self.enabled_getter():
            return False
        self.generate_today(now)
        active_name = str(self.active_character_name() or "").strip()
        if not active_name:
            return False
        character = self.config_manager.get_character_by_name(active_name)
        if character is None:
            return False
        life_plan = self.life_engine.ensure_daily_plan(
            character,
            now=now,
            agent_backend=self.agent_backend,
            allow_llm_generate=False,
        )
        contact_plan = self.contact_engine.ensure_contact_plan(
            character,
            life_plan,
            now=now,
            agent_backend=self.agent_backend,
            allow_llm_generate=False,
        )
        if self._sent_count(contact_plan) >= max(0, int(contact_plan.daily_contact_limit)):
            return False
        item = self._due_contact(contact_plan, now)
        if item is None:
            return False
        if self._recent_user_message(now, item):
            self.contact_engine.mark_skipped(active_name, contact_plan, item, "recent_user_message")
            return False
        block = self.life_engine.block_at(life_plan, now)
        if block is None:
            self.contact_engine.mark_skipped(active_name, contact_plan, item, "life_block_not_suitable")
            return False
        life_state = self.life_engine.render_life_state(life_plan, block)
        dialog = self.compose_dialog(character, life_plan, contact_plan, item, block, life_state=life_state)
        if dialog is None:
            return False
        if str(dialog.name or "").strip() != active_name:
            dialog = dialog.model_copy(update={"name": active_name})
        image_path = self._generate_photo(active_name, character, contact_plan, item, dialog, life_state, now)
        if not self._deliver(active_name, contact_plan, item, dialog, now, image_path=image_path):
            return False
        self.contact_engine.mark_sent(active_name, contact_plan, item, now)
        return True

    def compose_dialog(
        self,
        character: Any,
        life_plan: DailyLifePlan,
        contact_plan: DailyContactPlan,
        item: ContactPlanItem,
        block: Any,
        life_state: str | None = None,
    ) -> AgentDialogMessage | None:
        active_name = str(getattr(character, "name", "") or "角色").strip() or "角色"
        life_state = life_state or self.life_engine.render_life_state(life_plan, block)
        prompt = self._compose_prompt(active_name, contact_plan, item, life_state)
        try:
            raw = self.agent_backend.oneshot(
                prompt,
                system_prompt=(
                    "你是 Here 桌面角色的主动联系消息生成器。"
                    "只输出一个 JSON 对象，不输出解释、Markdown、思考过程或额外文本。"
                ),
                tools=False,
            )
        except Exception as exc:
            print(f"ProactiveContactScheduler: 主动消息生成失败: {exc}")
            return self._fallback_dialog(active_name, item)
        msg = self._parse_dialog(raw)
        if msg is not None:
            return msg
        return self._fallback_dialog(active_name, item)

    def _run(self) -> None:
        self.generate_today()
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                print(f"ProactiveContactScheduler: tick 失败: {exc}")
            if self._stop_event.wait(self.check_interval_seconds):
                return

    def _compose_prompt(
        self,
        active_name: str,
        contact_plan: DailyContactPlan,
        item: ContactPlanItem,
        life_state: str,
    ) -> str:
        basis = "；".join(item.memory_basis[-2:])
        return (
            "这是角色主动联系用户，不是回复用户消息。\n"
            "请只输出一个 Here 角色对话 JSON 对象，且只输出一条当前角色消息。\n"
            f"当前角色：{active_name}\n"
            f"{life_state}\n"
            f"主动联系风格：{contact_plan.contact_style}\n"
            f"主动联系类型：{item.type}\n"
            f"主动联系原因：{item.intent}\n"
            f"相关记忆依据：{basis}\n"
            f"消息种子：{item.message_seed}\n"
            "表达要求：一句自然短消息；不要提系统、计划、触发、日程表；不要连续追问；不要替用户安排。\n"
            "JSON 形如："
            "{\"character_name\":\"角色名\",\"speech\":\"一句自然短消息\",\"emotion\":\"neutral|happy|thinking|surprised|sad|angry\",\"system_action\":null}"
        )

    def _fallback_dialog(self, active_name: str, item: ContactPlanItem) -> AgentDialogMessage:
        text = item.message_seed or item.intent or "我刚刚有点想起你，就来看看你。"
        return AgentDialogMessage(name=active_name, text=text[:120], emotion="neutral")

    def _deliver(
        self,
        active_name: str,
        contact_plan: DailyContactPlan,
        item: ContactPlanItem,
        dialog: AgentDialogMessage,
        now: datetime,
        *,
        image_path: str = "",
    ) -> bool:
        if self.delivery_router is None or self.delivery_adapters is None:
            self.emit_dialog(dialog)
            self._mark_delivery(active_name, contact_plan, item, "desktop_chat", "sent", "legacy_emit", now)
            return True
        route = self.delivery_router.route(now=now)
        if not route.allowed:
            self._mark_delivery(active_name, contact_plan, item, route.channel, "skipped", route.reason, now)
            return False
        if route.requires_confirmation and route.channel != "desktop_chat":
            route_channel = "desktop_chat"
            route_reason = "confirmation_required_fallback"
        else:
            route_channel = route.channel
            route_reason = route.reason
        if route_channel != "desktop_chat" and self._external_sent_count(contact_plan) >= self._external_daily_limit():
            route_channel = "desktop_chat"
            route_reason = "external_daily_limit_fallback"
        audio_path = ""
        if route_channel != "desktop_chat" and self._external_delivery_audio_enabled():
            audio_path = self._generate_audio(active_name, dialog)
        message = DeliveryMessage(
            dialog=dialog,
            character_name=active_name,
            target_channel=route_channel,
            image_path=image_path,
            audio_path=audio_path,
        )
        result = self.delivery_adapters.send(message)
        result_status = str(getattr(result, "status", "failed") or "failed")
        result_channel = str(getattr(result, "channel", route_channel) or route_channel)
        result_reason = str(getattr(result, "reason", route_reason) or route_reason)
        if result_status == "sent":
            self._mark_delivery(active_name, contact_plan, item, result_channel, "sent", route_reason, now)
            return True
        self._mark_delivery(active_name, contact_plan, item, result_channel, result_status, result_reason, now)
        if route_channel != "desktop_chat":
            fallback = DeliveryMessage(
                dialog=dialog,
                character_name=active_name,
                target_channel="desktop_chat",
                image_path=image_path,
            )
            fallback_result = self.delivery_adapters.send(fallback)
            fallback_status = str(getattr(fallback_result, "status", "failed") or "failed")
            fallback_channel = str(getattr(fallback_result, "channel", "desktop_chat") or "desktop_chat")
            self._mark_delivery(
                active_name,
                contact_plan,
                item,
                fallback_channel,
                fallback_status,
                f"fallback_after_{result_reason}",
                now,
            )
            return fallback_status == "sent"
        return False

    def _generate_photo(
        self,
        active_name: str,
        character: Any,
        contact_plan: DailyContactPlan,
        item: ContactPlanItem,
        dialog: AgentDialogMessage,
        life_state: str,
        now: datetime,
    ) -> str:
        if not self._proactive_photo_enabled():
            return ""
        if self.photo_generator is None:
            return ""
        if self._photo_sent_count_for_day(contact_plan, item) >= self._proactive_photo_daily_limit():
            item.photo_status = "skipped"
            item.photo_reason = "daily_limit"
            return ""
        photo_intent = str(item.photo_intent or "").strip()
        if not photo_intent:
            return ""
        try:
            result = self.photo_generator(
                SelfieRequest(
                    character=character,
                    life_state=life_state,
                    photo_intent=photo_intent,
                    contact_text=str(dialog.text or ""),
                    emotion=str(dialog.emotion or ""),
                    now=now,
                )
            )
        except Exception as exc:
            print(f"ProactiveContactScheduler: 主动联系配图生成失败: {exc}")
            item.photo_status = "failed"
            item.photo_reason = str(exc)
            return ""
        path = str(result or "").strip()
        if not path:
            item.photo_status = "failed"
            item.photo_reason = "empty_result"
            return ""
        item.photo_path = path
        item.photo_status = "generated"
        item.photo_reason = "sent_with_contact"
        return path

    def _generate_audio(self, active_name: str, dialog: AgentDialogMessage) -> str:
        if self.audio_generator is None:
            return ""
        text = str(dialog.translate or dialog.text or "").strip()
        if not text:
            return ""
        try:
            return str(self.audio_generator(active_name, text) or "")
        except Exception as exc:
            print(f"ProactiveContactScheduler: 外部语音生成失败: {exc}")
            return ""

    def _mark_delivery(
        self,
        active_name: str,
        contact_plan: DailyContactPlan,
        item: ContactPlanItem,
        channel: str,
        status: str,
        reason: str,
        now: datetime,
    ) -> None:
        mark = getattr(self.contact_engine, "mark_delivery_attempt", None)
        if callable(mark):
            mark(
                active_name,
                contact_plan,
                item,
                channel=channel,
                status=status,
                reason=reason,
                attempted_at=now,
            )

    def _external_sent_count(self, plan: DailyContactPlan) -> int:
        return sum(
            1
            for item in plan.contacts
            if item.status == "sent"
            and item.delivery_status == "sent"
            and item.delivery_channel not in {"", "desktop_chat"}
        )

    def _external_daily_limit(self) -> int:
        system = self.config_manager.config.system_config
        try:
            return max(0, int(getattr(system, "external_delivery_daily_limit", 1)))
        except (TypeError, ValueError):
            return 1

    def _external_delivery_audio_enabled(self) -> bool:
        system = self.config_manager.config.system_config
        return bool(getattr(system, "external_delivery_audio_enabled", False))

    def _proactive_photo_enabled(self) -> bool:
        system = self.config_manager.config.system_config
        return bool(getattr(system, "proactive_photo_enabled", False))

    def _proactive_photo_daily_limit(self) -> int:
        system = self.config_manager.config.system_config
        try:
            return max(0, int(getattr(system, "proactive_photo_daily_limit", 1)))
        except (TypeError, ValueError):
            return 1

    def _photo_sent_count_for_day(self, plan: DailyContactPlan, current_item: ContactPlanItem) -> int:
        count = 0
        for item in plan.contacts:
            if item.id == current_item.id:
                continue
            if item.photo_status == "generated" and item.photo_path:
                count += 1
        return count

    def _parse_dialog(self, raw: Any) -> AgentDialogMessage | None:
        text = str(raw or "").strip()
        if not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            payload = payload[0]
        if not isinstance(payload, dict):
            return None
        try:
            return AgentDialogMessage(**payload)
        except Exception:
            return None

    def _due_contact(self, plan: DailyContactPlan, now: datetime) -> ContactPlanItem | None:
        for item in plan.contacts:
            if item.status != "pending":
                continue
            if _time_in_window(now.timetz().replace(tzinfo=None), item.window_start, item.window_end):
                return item
        return None

    def _sent_count(self, plan: DailyContactPlan) -> int:
        return sum(1 for item in plan.contacts if item.status == "sent")

    def _recent_user_message(self, now: datetime, item: ContactPlanItem) -> bool:
        if self.last_user_message_at is None:
            return False
        delta = now - self.last_user_message_at
        return delta >= timedelta(0) and delta.total_seconds() < item.skip_if_recent_user_message_minutes * 60


def _time_in_window(current: time, start: str, end: str) -> bool:
    start_t = _parse_hhmm(start)
    end_t = _parse_hhmm(end)
    if start_t is None or end_t is None:
        return False
    cur = current.hour * 60 + current.minute
    s = start_t.hour * 60 + start_t.minute
    e = end_t.hour * 60 + end_t.minute
    if e <= s:
        return cur >= s or cur < e
    return s <= cur < e


def _parse_hhmm(value: str) -> time | None:
    try:
        return datetime.strptime(str(value), "%H:%M").time()
    except ValueError:
        return None
