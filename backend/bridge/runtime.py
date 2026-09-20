from __future__ import annotations

from typing import Any

from bridge import hooks
from bridge.deps import (
    AgentMemoryStore,
    ConfigManager,
    ContactPlanEngine,
    DailyLifeScheduler,
    DeliveryAdapterRegistry,
    DeliveryCapabilityProbe,
    DeliveryRouter,
    DesktopDeliveryAdapter,
    DreamScheduler,
    LifeEngine,
    MemoryDreamer,
    MessageSender,
    MessagingConfig,
    MessagingDeliveryAdapter,
    ProactiveContactScheduler,
    T2IAdapterFactory,
    T2IManager,
    TTSAdapterFactory,
    TTSManager,
    TextProcessor,
    build_selfie_runtime,
    create_agent_backend,
    create_default_registry,
    get_app_paths,
    install_user_python_packages_path,
    name_map,
    seed_defaults,
    threading,
    traceback,
    uuid,
)


def init_backend(self) -> None:
    self.paths = get_app_paths()
    install_user_python_packages_path(self.paths)
    seed_defaults(self.paths, source_root=hooks.BACKEND_ROOT / "defaults")
    self.config = ConfigManager()
    self.memory = AgentMemoryStore()
    self.history_path = self.paths.state_dir / "electron_history.json"
    self.history_lock = threading.RLock()
    self.chat_lock = threading.RLock()
    self.screen_context_last_prompt_at = 0.0
    self.asr_adapter: Any | None = None
    self.chat_platform_bridge: Any | None = None
    self._initialize_runtime()


def _initialize_runtime(self) -> None:
    name_map.clear()
    for configured_character in self.config.config.characters:
        name_map.update(dict(getattr(configured_character, "pronunciation_map", {}) or {}))
    self.text_processor = TextProcessor()
    self.agent = create_agent_backend(
        self.config,
        system_prompt=self._system_template(),
        status_callback=lambda text: hooks.event("status", {"text": str(text), "busy": False}),
        tool_status_callback=lambda text: hooks.event("status", {"text": str(text), "busy": True}),
    )
    self.life = LifeEngine(self.memory)
    self.dream_scheduler = DreamScheduler(self.config, MemoryDreamer(self.memory, self.agent))
    self.contacts = ContactPlanEngine(self.memory, self.life)
    self.delivery_router = DeliveryRouter(self.config, DeliveryCapabilityProbe(self.config))
    self.sender = MessageSender(
        config=MessagingConfig.auto_load(),
        registry=create_default_registry(self._emit_dialog),
    )
    self.delivery = DeliveryAdapterRegistry(
        DesktopDeliveryAdapter(self._emit_dialog),
        MessagingDeliveryAdapter(self.sender),
    )
    self.tts = self._build_tts()
    self.t2i = self._build_t2i()
    try:
        self.selfie, self.selfie_t2i = build_selfie_runtime(
            self.config,
            existing_manager=self.t2i,
            enabled_only=True,
        )
    except Exception as exc:
        print(f"Selfie runtime unavailable: {exc}")
        self.selfie, self.selfie_t2i = None, self.t2i
    self.life_scheduler = DailyLifeScheduler(
        config_manager=self.config,
        life_engine=self.life,
        agent_backend=self.agent,
        allow_llm_generate_getter=self._proactive_enabled,
    )
    self.proactive = ProactiveContactScheduler(
        config_manager=self.config,
        life_engine=self.life,
        contact_engine=self.contacts,
        agent_backend=self.agent,
        active_character_name=self.config.resolve_active_character_name,
        emit_dialog=self._emit_dialog,
        enabled_getter=self._proactive_enabled,
        delivery_router=self.delivery_router,
        delivery_adapters=self.delivery,
        audio_generator=self._generate_tts_for_delivery,
        photo_generator=self._generate_photo,
        memory_store=self.memory,
    )
    if self._proactive_enabled():
        self.life_scheduler.start()
    self.dream_scheduler.start()
    self.proactive.start()
    self._restart_chat_platform_bridge()


def _shutdown_runtime(self) -> None:
    hooks.stop_chat_platform_bridge(getattr(self, "chat_platform_bridge", None), wait=True)
    self.chat_platform_bridge = None
    for runtime in (
        getattr(self, "proactive", None),
        getattr(self, "life_scheduler", None),
        getattr(self, "dream_scheduler", None),
        getattr(self, "asr_adapter", None),
    ):
        stop = getattr(runtime, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass
    try:
        self.agent.interrupt()
    except Exception:
        pass


def _restart_chat_platform_bridge(self) -> None:
    hooks.stop_chat_platform_bridge(getattr(self, "chat_platform_bridge", None), wait=True)
    self.chat_platform_bridge = hooks.start_chat_platform_bridge(
        channel=str(getattr(self.config.config.system_config, "chat_delivery_channel", "desktop_chat")),
        emit_user_text=self._receive_platform_text,
        notify=lambda text: hooks.event("status", {"text": str(text), "busy": False}),
    )


def _receive_platform_text(self, text: str) -> None:
    message = str(text or "").strip()
    if not message:
        return

    def run_inbound() -> None:
        request_id = f"platform-{uuid.uuid4().hex}"
        try:
            self.chat({"request_id": request_id, "text": message, "source": "platform"})
        except Exception as exc:
            traceback.print_exc()
            hooks.event("chat_error", {"request_id": request_id, "message": str(exc)})

    threading.Thread(target=run_inbound, name="here-platform-chat", daemon=True).start()


def reload_runtime(self) -> None:
    had_asr_adapter = self.asr_adapter is not None
    self._shutdown_runtime()
    self.asr_adapter = None
    if had_asr_adapter:
        hooks.event("asr_state", {"running": False, "paused": False})
    self.config.reload()
    self._initialize_runtime()


def _system_template(self) -> str:
    path = self.paths.templates_dir / "here_companion.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _companion_context_template(self) -> str:
    """Load the project-owned runtime behavior skill only while 同桌模式 is on."""
    template = self._system_template()
    system = self.config.config.system_config
    if not bool(getattr(system, "screen_context_enabled", False)):
        return template
    skill_path = hooks.BACKEND_ROOT.parent / "skills" / "here-companion-mode" / "references" / "runtime-prompt.md"
    try:
        companion = skill_path.read_text(encoding="utf-8").strip()
    except OSError:
        companion = ""
    if companion:
        return f"{template}\n\n【同桌模式行为协议】\n{companion}"
    return template


def _proactive_enabled(self) -> bool:
    return bool(self.config.config.system_config.proactive_contact_enabled)


def _build_tts(self) -> TTSManager | None:
    provider = str(self.config.config.api_config.tts_provider or "none").strip().lower()
    if not provider or provider == "none":
        return None
    try:
        adapter = TTSAdapterFactory.create_adapter(
            provider,
            **self.config.merged_tts_factory_kwargs(provider, {}),
        )
        manager = TTSManager()
        manager.set_tts_adapter(adapter)
        manager.set_language(str(self.config.config.system_config.voice_language or "ja"))
        return manager
    except Exception as exc:
        hooks.event("status", {"text": f"TTS 初始化失败：{exc}", "busy": False})
        return None


def _build_t2i(self) -> T2IManager | None:
    provider = str(self.config.config.api_config.t2i_provider or "image-api").strip()
    base = {}
    if provider.lower() == "image-api":
        base["api_url"] = str(self.config.config.api_config.t2i_api_url)
    try:
        adapter = T2IAdapterFactory.create_adapter(
            provider,
            **self.config.merged_t2i_factory_kwargs(provider, base),
        )
        return T2IManager(adapter)
    except Exception as exc:
        hooks.event("status", {"text": f"生图初始化失败：{exc}", "busy": False})
        return None


def shutdown(self) -> None:
    self._shutdown_runtime()
