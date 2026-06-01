import os
import signal
from pathlib import Path

from infrastructure.paths import get_app_paths, install_user_python_packages_path, seed_defaults
import sys
import numpy as np

# 打包后须在任何会触发 ConfigManager 的 import 之前设发行根 cwd（同设置入口）
if getattr(sys, "frozen", False):
    try:
        _rel = Path(sys.executable).resolve().parent.parent
        os.environ["HERE_PROJECT_ROOT"] = str(_rel)
        os.chdir(_rel)
    except OSError:
        pass

current_script = Path(__file__).resolve()
project_root = current_script.parents[2]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

if getattr(sys, "frozen", False):
    from core.bootstrap.frozen_log import init_frozen_stdio

    init_frozen_stdio("main")

from core.sprite.template_generator import is_transparent_background
from core.sprite.text_processor import TextProcessor
from core.agent import create_agent_backend
from internal_agent.context import AgentMemoryStore
from core.delivery import (
    DeliveryAdapterRegistry,
    DeliveryCapabilityProbe,
    DeliveryRouter,
    DesktopDeliveryAdapter,
    MessagingDeliveryAdapter,
)
from core.delivery.chat_platform_bridge import start_chat_platform_bridge
from core.delivery.messaging import MessageSender, MessagingConfig, create_default_registry
from core.delivery.messaging.wechat_openclaw import monitor_manager
from core.life import DailyLifeScheduler, LifeEngine
from core.proactive import ContactPlanEngine, ProactiveContactScheduler
from core.runtime.workers import AgentWorker, TTSWorker, UIWorker
from core.runtime.app_runtime import ActiveCharacterState, AppRuntime, set_app_runtime
from core.runtime.ui_update_manager import UIUpdateManager, connect_to_desktop_window
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QIcon
from services.tts.tts_manager import TTSManager, TTSAdapterFactory
from ui.desktop import ChatUIWindow, character_entry_line, character_entry_sprite
from ui.desktop import styles
from ui.desktop.combo_style import install_combo_popup_style
from ui.desktop.qss_fusion import ensure_fusion_style
from services.config.config_manager import ConfigManager
from services.t2i.t2i_manager import T2IAdapterFactory, T2IManager
from services.selfie import SelfieRequest, SelfieService
from services.selfie.factory import build_selfie_runtime
import pygame
import traceback
from opencc import OpenCC
from queue import Queue

from core.sprite.chat_history import (
    chat_history,
    get_history,
    save_bg,
)
from core.sprite.chat_ui_service import (
    install_chat_ui_context,
    restore_session_ui,
    wire_chat_ui_bridge,
)
from core.sprite.sprite_cli import parse_sprite_args
from core.messaging.messages import TTSOutputMessage, UserInputMessage

voice_lang = "ja"
cc = OpenCC("t2s")  # 繁体到简体转换器


def _install_sigint_handler(app: QApplication) -> QTimer | None:
    """Let Ctrl+C in a console request the normal Qt shutdown path."""
    previous_handler = signal.getsignal(signal.SIGINT)

    def _handle_sigint(_signum, _frame) -> None:
        print("收到 Ctrl+C，正在退出 here…")
        try:
            app.quit()
        except RuntimeError:
            pass
        if callable(previous_handler) and previous_handler not in (
            signal.default_int_handler,
            signal.SIG_DFL,
            signal.SIG_IGN,
        ):
            previous_handler(_signum, _frame)

    try:
        signal.signal(signal.SIGINT, _handle_sigint)
    except (ValueError, RuntimeError):
        return None

    timer = QTimer(app)
    timer.setTimerType(Qt.TimerType.CoarseTimer)
    timer.timeout.connect(lambda: None)
    timer.start(100)
    return timer


def _install_tray_icon(app: QApplication, window: ChatUIWindow, icon: QIcon, tr_i18n) -> QSystemTrayIcon | None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None

    app.setQuitOnLastWindowClosed(False)
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("here")

    menu = QMenu(window)
    show_action = QAction(tr_i18n("desktop.menu.show_from_background"), menu)
    hide_action = QAction(tr_i18n("desktop.menu.hide_to_background"), menu)
    quit_action = QAction(tr_i18n("desktop.menu.close"), menu)

    show_action.triggered.connect(window.show_from_background)
    hide_action.triggered.connect(window.hide_to_background)
    quit_action.triggered.connect(app.quit)

    menu.addAction(show_action)
    menu.addAction(hide_action)
    menu.addSeparator()
    menu.addAction(quit_action)
    menu.setStyleSheet(styles.menu_popup())
    tray.setContextMenu(menu)
    tray._here_context_menu = menu

    def _on_activated(reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if window.isVisible() and not window.isMinimized():
                window.hide_to_background()
            else:
                window.show_from_background()

    tray.activated.connect(_on_activated)
    tray.show()
    window._background_tray_available = True
    return tray


def _proactive_contact_enabled(config: ConfigManager) -> bool:
    return bool(getattr(config.config.system_config, "proactive_contact_enabled", False))


def _try_init_audio_mixer(tr_i18n) -> bool:
    try:
        pygame.mixer.init()
        return True
    except Exception as exc:
        print(tr_i18n("main.print_audio_unavailable", e=str(exc)))
        traceback.print_exc()
        return False


def _default_sprite_scale(config: ConfigManager) -> float:
    try:
        raw = getattr(config.config.system_config, "default_sprite_scale", 0.72)
        return max(0.25, min(1.5, float(raw)))
    except (TypeError, ValueError):
        return 0.72


def _generate_external_delivery_audio(rt: AppRuntime, character_name: str, text: str) -> str:
    if rt.tts_manager is None:
        return ""
    try:
        character_config = rt.config.get_character_by_name(character_name)
        speed = getattr(character_config, "speech_speed", 1.0) if character_config is not None else 1.0
        processed = rt.text_processor.remove_parentheses(text)
        return str(
            rt.tts_manager.generate_tts(
                processed,
                text_processor=rt.text_processor,
                character_name=character_name,
                speed_factor=speed,
            )
            or ""
        )
    except Exception as exc:
        print(f"External delivery TTS failed: {exc}")
        return ""


def _generate_proactive_photo(service: SelfieService | None, request: SelfieRequest) -> str:
    if service is None:
        return ""
    result = service.generate(request)
    return result.path if result is not None else ""


def _t2i_base_kwargs(config: ConfigManager, provider: str) -> dict[str, str]:
    if str(provider or "").strip().lower() == "image-api":
        return {"api_url": str(config.config.api_config.t2i_api_url)}
    return {}


def run_desktop_app():
    app_paths = get_app_paths()
    install_user_python_packages_path(app_paths)
    seed_defaults(app_paths)
    config = ConfigManager()
    from services.i18n import init_i18n, tr as tr_i18n

    init_i18n(config.config.system_config.ui_language)

    args = parse_sprite_args(tr_i18n)

    # T2I manager
    t2i_manager = None
    if args.t2i:
        raw = (args.t2i or "").strip()
        adapter_pick = (
            (config.config.api_config.t2i_provider or "image-api").strip()
            if raw.lower() in ("image-api", "api", "cg", "true", "1", "yes")
            else raw
        )
        try:
            t2i_adapter = T2IAdapterFactory.create_adapter(
                adapter_name=adapter_pick,
                **config.merged_t2i_factory_kwargs(
                    adapter_pick,
                    _t2i_base_kwargs(config, adapter_pick),
                ),
            )
            t2i_manager = T2IManager(t2i_adapter)
        except Exception as e:
            print(tr_i18n("main.print_t2i_fail", e=str(e)))
            traceback.print_exc()

    # TTS：仅当 API 中语音引擎不是「不使用」时加载；命令行 --tts 可覆盖引擎名（与 api.yaml 一致）
    config_tts_provider = config.config.api_config.tts_provider
    adapter_name = (args.tts or "").strip() or config_tts_provider
    tts_manager = None
    if adapter_name and str(adapter_name).strip().lower() not in ("none",):
        try:
            adapter = TTSAdapterFactory.create_adapter(
                adapter_name=adapter_name,
                **config.merged_tts_factory_kwargs(adapter_name, {}),
            )
            tts_manager = TTSManager()
            tts_manager.set_tts_adapter(adapter=adapter)
            _voice_lang = str(config.config.system_config.voice_language or "ja").strip() or "ja"
            tts_manager.set_language(_voice_lang)
        except Exception as e:
            print(tr_i18n("main.print_tts_fail", e=str(e)))
            traceback.print_exc()

    print(tr_i18n("main.print_load_template", a=args))

    messages = []

    user_template = ""
    with open(
        app_paths.templates_dir / f"{args.template}.txt", "r", encoding="utf-8"
    ) as f:
        user_template = f.read()

    hermes_config = config.get_hermes_config()
    print(
        f"Agent backend: {config.get_agent_backend_name()}",
        f"stream={hermes_config.get('stream')}",
        f"max_iterations={hermes_config.get('max_iterations')}",
    )
    print(f"App home: {app_paths.root}")
    print(f"API config path: {getattr(config, '_API_CONFIG_PATH', app_paths.config_dir / 'api.yaml')}")

    # Legacy flow
    image_queue = Queue()
    emotion_queue = Queue()

    # 初始化 Pygame 音频；失败时保留文本聊天和 UI 启动。
    audio_available = _try_init_audio_mixer(tr_i18n)

    # 创建三个消息队列
    user_input_queue = Queue()
    tts_queue = Queue()
    audio_path_queue = Queue()

    text_processor = TextProcessor()

    # 将角色读音映射注入 text_processor.name_map
    for _char in config.config.characters:
        _pm = getattr(_char, "pronunciation_map", None)
        if _pm:
            from core.sprite.text_processor import name_map
            name_map.update(_pm)

    # 获取背景组
    bg_group = None
    try:
        bg_group = (
            None
            if is_transparent_background(args.bg)
            else config.get_background_by_name(args.bg).sprites
        )
    except Exception:
        pass

    bgm_list = []
    try:
        bgm_list = (
            []
            if is_transparent_background(args.bg)
            else config.get_background_by_name(args.bg).bgm_list
        )
    except Exception:
        pass

    # Init UI and connect to runtime
    app = QApplication([])
    sigint_timer = _install_sigint_handler(app)
    ensure_fusion_style(app)
    install_combo_popup_style(app)
    ui_updates = UIUpdateManager(chat_history=chat_history, bg_group=bg_group or [], t2i_manager=t2i_manager)
    agent_backend = create_agent_backend(
        config,
        system_prompt=user_template,
        status_callback=ui_updates.post_notification,
        tool_status_callback=lambda text: ui_updates.post_busy_bar(str(text), 0.0),
    )
    selected_backend = getattr(agent_backend, "selected_backend_id", type(agent_backend).__name__)
    print(f"Selected agent backend: {selected_backend}")
    window = ChatUIWindow(
        image_queue,
        emotion_queue,
        agent_backend,
        sprite_mode=True,
        background_mode=(bg_group is not None),
    )
    connect_to_desktop_window(ui_updates, window)
    ui_updates.post_notification(f"Agent 后端: {selected_backend}")
    if not audio_available:
        ui_updates.post_notification(tr_i18n("main.notify_audio_unavailable"))

    rt = AppRuntime(
        config=config,
        ui_update_manager=ui_updates,
        agent_backend=agent_backend,
        tts_manager=tts_manager,
        t2i_manager=t2i_manager,
        bgm_list=bgm_list,
        user_input_queue=user_input_queue,
        tts_queue=tts_queue,
        audio_path_queue=audio_path_queue,
        text_processor=text_processor,
        opencc=cc,
    )
    rt.active_character = ActiveCharacterState(config)
    memory_store = AgentMemoryStore()
    rt.agent_memory_store = memory_store
    rt.life_engine = LifeEngine(memory_store)
    rt.life_scheduler = DailyLifeScheduler(
        config_manager=config,
        life_engine=rt.life_engine,
        agent_backend=agent_backend,
        allow_llm_generate_getter=lambda: _proactive_contact_enabled(config),
    )
    if _proactive_contact_enabled(config):
        rt.life_scheduler.start()
    rt.contact_engine = ContactPlanEngine(memory_store, rt.life_engine)
    rt.delivery_router = DeliveryRouter(config, DeliveryCapabilityProbe(config))
    messaging_sender = MessageSender(
        config=MessagingConfig.auto_load(),
        registry=create_default_registry(tts_queue.put),
    )
    try:
        monitor_manager.start_saved_accounts(
            on_status=lambda text: ui_updates.post_notification(f"WeChat: {text}"),
        )
    except Exception as exc:
        print(f"WeChat monitor start failed: {exc}")
    rt.delivery_adapters = DeliveryAdapterRegistry(
        DesktopDeliveryAdapter(tts_queue.put),
        MessagingDeliveryAdapter(messaging_sender),
    )
    selfie_service = None
    selfie_t2i_manager = None
    try:
        selfie_service, selfie_t2i_manager = build_selfie_runtime(config, enabled_only=True)
    except Exception as exc:
        print(f"Proactive photo runtime init failed: {exc}")
    rt.selfie_service = selfie_service
    rt.selfie_t2i_manager = selfie_t2i_manager
    rt.proactive_contact_scheduler = ProactiveContactScheduler(
        config_manager=config,
        life_engine=rt.life_engine,
        contact_engine=rt.contact_engine,
        agent_backend=agent_backend,
        active_character_name=lambda: rt.active_character.name if rt.active_character is not None else "",
        emit_dialog=tts_queue.put,
        enabled_getter=lambda: bool(getattr(config.config.system_config, "proactive_contact_enabled", False)),
        delivery_router=rt.delivery_router,
        delivery_adapters=rt.delivery_adapters,
        audio_generator=lambda character_name, text: _generate_external_delivery_audio(
            rt,
            character_name,
            text,
        ),
        photo_generator=lambda request: _generate_proactive_photo(
            getattr(rt, "selfie_service", None),
            request,
        ),
        memory_store=memory_store,
    )
    rt.proactive_contact_scheduler.start()
    set_app_runtime(rt)
    rt.chat_platform_bridge = start_chat_platform_bridge(
        channel=getattr(config.config.system_config, "chat_delivery_channel", "desktop_chat"),
        emit_user_text=lambda text: user_input_queue.put(UserInputMessage(text=text)),
        notify=ui_updates.post_notification,
    )

    # 创建并启动 Worker 线程（队列显式连接流水线，其馀从 app_runtime 注入）
    ui_worker = UIWorker(audio_path_queue)
    ui_worker.start()

    tts_worker = TTSWorker(tts_queue, audio_path_queue)
    tts_worker.start()

    agent_worker = AgentWorker(user_input_queue, tts_queue)
    agent_worker.start()

    active_character = rt.active_character.name
    print(f"启动角色: {active_character}")

    # 启动第一句走正常 UI 输出队列，由 CharacterDialogUiHandler 显示。
    if not messages:
        entry_sprite = character_entry_sprite(active_character, config)
        audio_path_queue.put(
            TTSOutputMessage(
                audio_path="",
                name=active_character,
                text=character_entry_line(active_character),
                asset_id=entry_sprite.asset_id,
                emotion=entry_sprite.emotion,
                is_system_message=False,
                timeout=0,
            )
        )
    window.setNotification(f"和{active_character}说点什么……")

    def emit_user_text(text: str) -> None:
        user_input_queue.put(UserInputMessage(text=text))

    # Update system_config with current session's bg/bgm so restore doesn't use stale values
    sc = config.config.system_config.model_copy(deep=True)
    if bg_group:
        sc.bgm_path = bgm_list[0] if bgm_list else ""
        sc.background_path = bg_group[0].get("path", "") if bg_group else ""
    else:
        sc.bgm_path = ""
        sc.background_path = ""
    config.config.system_config = sc
    config.save_system_config()

    chat_ui_ctx = install_chat_ui_context(window, emit_user_text=emit_user_text)

    restore_session_ui(
        messages,
        audio_path_queue=audio_path_queue,
        window=window,
        config=config,
        tr_i18n=tr_i18n,
    )

    wire_chat_ui_bridge(
        chat_ui_ctx,
        window=window,
        app=app,
        emit_user_text=emit_user_text,
        chat_history=chat_history,
        history_file=args.history,
        agent_backend=agent_backend,
        audio_path_queue=audio_path_queue,
        tts_manager=tts_manager,
        ui_worker=ui_worker,
        tr_i18n=tr_i18n,
    )

    # 确保在程序退出时停止所有线程
    appIcon = QIcon(str(project_root / "assets" / "system" / "picture" / "Icon.png"))
    try:
        app.setWindowIcon(appIcon)
    except Exception as e:
        print(tr_i18n("main.print_icon_fail", e=str(e)))
    tray_icon = _install_tray_icon(app, window, appIcon, tr_i18n)

    # 关闭顺序：TTS 服务器 → Worker 线程 → 保存数据
    app.aboutToQuit.connect(lambda: tts_manager and tts_manager.shutdown())
    app.aboutToQuit.connect(lambda: getattr(rt.chat_platform_bridge, "stop", lambda: None)())
    app.aboutToQuit.connect(rt.life_scheduler.stop)
    app.aboutToQuit.connect(rt.proactive_contact_scheduler.stop)
    app.aboutToQuit.connect(agent_worker.stop)
    app.aboutToQuit.connect(tts_worker.stop)
    app.aboutToQuit.connect(ui_worker.stop)
    app.aboutToQuit.connect(window.stop_runtime_activity)
    app.aboutToQuit.connect(
        lambda: save_bg(
            bg_path=window.current_background_path,
            bgm_path=ui_updates.current_bgm_path,
        )
    )
    if sigint_timer is not None:
        app.aboutToQuit.connect(sigint_timer.stop)
    if tray_icon is not None:
        app.aboutToQuit.connect(tray_icon.hide)

    window.show()

    app.exec()
