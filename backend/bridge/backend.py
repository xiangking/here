from __future__ import annotations

from bridge import asr as asr_ops
from bridge import characters as character_ops
from bridge import chat as chat_ops
from bridge import history as history_ops
from bridge import media as media_ops
from bridge import messaging as messaging_ops
from bridge import runtime as runtime_ops
from bridge import state as state_ops
from bridge import storage as storage_ops


class HereBackend:
    __init__ = runtime_ops.init_backend
    _initialize_runtime = runtime_ops._initialize_runtime
    _shutdown_runtime = runtime_ops._shutdown_runtime
    _restart_chat_platform_bridge = runtime_ops._restart_chat_platform_bridge
    _receive_platform_text = runtime_ops._receive_platform_text
    reload_runtime = runtime_ops.reload_runtime
    _system_template = runtime_ops._system_template
    _companion_context_template = runtime_ops._companion_context_template
    _proactive_enabled = runtime_ops._proactive_enabled
    _build_tts = runtime_ops._build_tts
    _build_t2i = runtime_ops._build_t2i
    shutdown = runtime_ops.shutdown
    _history = history_ops._history
    _append_history = history_ops._append_history
    _write_history = history_ops._write_history
    clear_history = history_ops.clear_history
    revert_history = history_ops.revert_history
    _is_reserved_dialog_name = staticmethod(chat_ops._is_reserved_dialog_name)
    _handle_system_action = chat_ops._handle_system_action
    _emit_dialog = chat_ops._emit_dialog
    _route_chat_dialog = chat_ops._route_chat_dialog
    _background_asset = chat_ops._background_asset
    _bgm_asset = chat_ops._bgm_asset
    _emit_tts = chat_ops._emit_tts
    _generate_tts_for_delivery = chat_ops._generate_tts_for_delivery
    _generate_photo = chat_ops._generate_photo
    _save_attachments = chat_ops._save_attachments
    chat = chat_ops.chat
    observe_screen = chat_ops.observe_screen
    _chat = chat_ops._chat
    stop_chat = chat_ops.stop_chat
    state = state_ops.state
    save_config = state_ops.save_config
    set_active_character = state_ops.set_active_character
    update_memory = state_ops.update_memory
    upload_character_sprites = character_ops.upload_character_sprites
    create_character = character_ops.create_character
    _safe_asset_name = staticmethod(character_ops._safe_asset_name)
    import_character_state_assets = character_ops.import_character_state_assets
    delete_character_sprite = character_ops.delete_character_sprite
    delete_character = character_ops.delete_character
    resolve_assets = character_ops.resolve_assets
    codex_pet_candidates = character_ops.codex_pet_candidates
    import_codex_pet = character_ops.import_codex_pet
    generate_image = media_ops.generate_image
    generate_realtime_sprite = media_ops.generate_realtime_sprite
    start_asr = asr_ops.start_asr
    stop_asr = asr_ops.stop_asr
    pause_asr = asr_ops.pause_asr
    resume_asr = asr_ops.resume_asr
    _configured_vosk_model_path = asr_ops._configured_vosk_model_path
    _download_vosk_model = asr_ops._download_vosk_model
    prepare_asr = asr_ops.prepare_asr
    dependency_status = asr_ops.dependency_status
    install_dependencies = asr_ops.install_dependencies
    wechat_login_start = messaging_ops.wechat_login_start
    wechat_login_poll = messaging_ops.wechat_login_poll
    wechat_status = messaging_ops.wechat_status
    telegram_discover = messaging_ops.telegram_discover
    list_models = messaging_ops.list_models
    save_messaging = messaging_ops.save_messaging
    save_storage = storage_ops.save_storage
    import_legacy = storage_ops.import_legacy
