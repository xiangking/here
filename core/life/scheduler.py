"""Background daily-life scheduling for desktop characters."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any

from core.life.engine import DEFAULT_TIMEZONE, LifeEngine
from core.timezone import now_in_timezone, resolve_timezone


class DailyLifeScheduler:
    """Generate character daily plans off the hot chat path."""

    def __init__(
        self,
        *,
        config_manager: Any,
        life_engine: LifeEngine,
        agent_backend: Any,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        self.config_manager = config_manager
        self.life_engine = life_engine
        self.agent_backend = agent_backend
        self.timezone = timezone or DEFAULT_TIMEZONE
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="DailyLifeScheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)

    def generate_today(self) -> None:
        characters = list(getattr(self.config_manager.config, "characters", []) or [])
        for character in characters:
            if self._stop_event.is_set():
                return
            try:
                self.life_engine.ensure_daily_plan(
                    character,
                    agent_backend=self.agent_backend,
                    allow_llm_generate=True,
                )
            except Exception as exc:
                name = str(getattr(character, "name", "") or "角色")
                print(f"DailyLifeScheduler: 生成 {name} 的日程失败: {exc}")

    def _run(self) -> None:
        self._safe_generate_today()
        while not self._stop_event.is_set():
            try:
                delay = self._seconds_until_next_midnight()
            except Exception as exc:
                print(f"DailyLifeScheduler: 计算下次日程时间失败: {exc}")
                delay = 60.0
            if self._stop_event.wait(delay):
                return
            self._safe_generate_today()

    def _safe_generate_today(self) -> None:
        try:
            self.generate_today()
        except Exception as exc:
            print(f"DailyLifeScheduler: 日程生成线程失败: {exc}")

    def _seconds_until_next_midnight(self) -> float:
        tz = resolve_timezone(self.timezone)
        now = now_in_timezone(self.timezone)
        tomorrow = (now + timedelta(days=1)).date()
        midnight = datetime.combine(tomorrow, datetime.min.time(), tzinfo=tz)
        # Delay a little after midnight so date rollover is definitely settled.
        return max(1.0, (midnight - now).total_seconds() + 5.0)
