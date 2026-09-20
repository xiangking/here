from __future__ import annotations

from typing import Any

from bridge import hooks
from bridge.deps import (
    AgentDialogMessage,
    AgentResponseStreamParser,
    DeliveryMessage,
    NARR_ALIASES,
    Path,
    SYSTEM_CHARACTER_NAME,
    SelfieRequest,
    base64,
    build_agent_context,
    build_hermes_user_message,
    is_placeholder_character_name,
    json,
    match_bgm_name,
    match_cg_name,
    match_choice_name,
    match_cot_name,
    match_scene_name,
    match_stat_name,
    mimetypes,
    normalize_character_name,
    re,
    resolve_character_asset_path,
    resolve_sprite_index,
    threading,
    time,
    uuid,
)


def _is_reserved_dialog_name(name: str) -> bool:
    normalized = normalize_character_name(name)
    return bool(
        match_cot_name(normalized)
        or match_choice_name(normalized)
        or match_stat_name(normalized)
        or match_scene_name(normalized)
        or match_bgm_name(normalized)
        or match_cg_name(normalized)
        or normalized in NARR_ALIASES
    )


def _handle_system_action(
    self,
    dialog: AgentDialogMessage,
    *,
    active_character: str,
    user_text: str,
) -> AgentDialogMessage:
    action = dialog.system_action or {}
    if not isinstance(action, dict) or str(action.get("type") or "").strip() != "rename_active_character":
        return dialog
    old_name = str(active_character or "").strip()
    new_name = str(action.get("name") or action.get("new_name") or "").strip()
    if (
        not old_name
        or not new_name
        or old_name == new_name
        or old_name == SYSTEM_CHARACTER_NAME
        or not is_placeholder_character_name(old_name)
    ):
        return dialog
    if new_name not in str(user_text or "") and new_name not in str(dialog.text or ""):
        return dialog
    before_home = self.memory.agent_home(old_name)
    renamed = self.config.rename_character(old_name, new_name)
    if renamed != new_name:
        return dialog
    try:
        if before_home.exists():
            self.memory.rename_character(old_name, new_name)
    except Exception as exc:
        hooks.event("status", {"text": f"角色已重命名，但记忆目录迁移失败：{exc}", "busy": False})
    self.agent.reset_session()
    hooks.event("character", {"name": new_name})
    hooks.event("status", {"text": f"已将 {old_name} 命名为 {new_name}", "busy": False})
    return dialog.model_copy(update={"name": new_name})


def _emit_dialog(
    self,
    dialog: AgentDialogMessage,
    request_id: str = "",
    *,
    publish: bool = True,
) -> None:
    name = normalize_character_name(str(dialog.name or ""))
    text = str(dialog.text or "")
    if match_cot_name(name):
        preview = re.sub(r"<[^>]+>", " ", text)
        if publish:
            hooks.event("status", {"text": re.sub(r"\s+", " ", preview).strip()[:200] or "正在思考", "busy": True})
        return
    if match_choice_name(name):
        self._append_history("assistant", "CHOICE", text, request_id=request_id)
        if publish:
            hooks.event("options", {"options": [part.strip() for part in text.split("/") if part.strip()], "request_id": request_id})
        return
    if match_stat_name(name):
        if publish:
            hooks.event("numeric", {"text": text, "request_id": request_id})
        return
    if match_scene_name(name):
        path = self._background_asset(dialog.asset_id)
        self.config.config.system_config.background_path = path
        self.config.save_system_config()
        if publish:
            hooks.event("background", {"path": path, "request_id": request_id})
        return
    if match_bgm_name(name):
        path = self._bgm_asset(dialog.asset_id)
        self.config.config.system_config.bgm_path = path
        self.config.save_system_config()
        if publish:
            hooks.event("bgm", {"path": path, "request_id": request_id})
        return
    if match_cg_name(name):
        path = ""
        if self.t2i is not None and text:
            if publish:
                hooks.event("status", {"text": "正在生成场景图…", "busy": True})
            path = str(self.t2i.t2i(text) or "")
        if publish:
            hooks.event("cg", {
                "path": path,
                "caption": text,
                "background_only": "no person" in text.lower(),
                "request_id": request_id,
            })
        return
    item = self._append_history(
        "assistant",
        str(dialog.name or self.config.resolve_active_character_name()),
        text,
        emotion=str(dialog.emotion or "neutral"),
        asset_id=dialog.asset_id,
        request_id=request_id,
    )
    if publish:
        hooks.event("dialog", {**item, "translate": dialog.translate or "", "effect": dialog.effect or ""})
    if publish and name not in NARR_ALIASES and item["text"]:
        if self.tts is not None:
            threading.Thread(
                target=self._emit_tts,
                args=(item["character_name"], dialog.translate or item["text"], request_id),
                daemon=True,
            ).start()
        else:
            character = self.config.get_character_by_name(item["character_name"])
            sprite_index = resolve_sprite_index(character, str(dialog.emotion or "neutral")) if character else -1
            if character is not None and 0 <= sprite_index < len(character.sprites):
                sprite = character.sprites[sprite_index]
                voice_path = sprite.get("voice_path", "") if isinstance(sprite, dict) else getattr(sprite, "voice_path", "")
                if voice_path:
                    hooks.event("audio", {
                        "path": str(voice_path),
                        "request_id": request_id,
                        "character_name": item["character_name"],
                        "segment_index": 0,
                        "segment_count": 1,
                    })


def _route_chat_dialog(self, dialog: AgentDialogMessage, request_id: str, active_character: str) -> None:
    if self._is_reserved_dialog_name(str(dialog.name or "")):
        self._emit_dialog(dialog, request_id)
        return
    route = self.delivery_router.route_chat_response()
    channel = str(getattr(route, "channel", "desktop_chat") or "desktop_chat")
    if channel == "desktop_chat":
        self._emit_dialog(dialog, request_id)
        return
    delivery_result = self.delivery.send(
        DeliveryMessage(
            dialog=dialog,
            character_name=active_character or str(dialog.name or ""),
            target_channel=channel,
        )
    )
    if str(getattr(delivery_result, "status", "") or "") == "sent":
        self._emit_dialog(dialog, request_id, publish=False)
        hooks.event("external_delivery", {"channel": channel, "status": "sent", "request_id": request_id})
        return
    reason = str(getattr(delivery_result, "reason", "") or "unknown")
    hooks.event("status", {"text": f"外部渠道发送失败，已回到桌面：{reason}", "busy": False})
    self._emit_dialog(dialog, request_id)


def _background_asset(self, asset_id: Any) -> str:
    try:
        index = int(asset_id) - 1
    except (TypeError, ValueError):
        return ""
    for group in self.config.config.background_list:
        sprites = list(getattr(group, "sprites", []) or [])
        if 0 <= index < len(sprites):
            sprite = sprites[index]
            raw = sprite.get("path") if isinstance(sprite, dict) else getattr(sprite, "path", "")
            return resolve_character_asset_path(raw, self.paths).as_posix()
    return ""


def _bgm_asset(self, asset_id: Any) -> str:
    try:
        index = int(asset_id) - 1
    except (TypeError, ValueError):
        return ""
    for group in self.config.config.background_list:
        tracks = list(getattr(group, "bgm_list", []) or [])
        if 0 <= index < len(tracks):
            path = Path(str(tracks[index])).expanduser()
            return path.as_posix() if path.is_absolute() else (hooks.BACKEND_ROOT / path).as_posix()
    return ""


def _emit_tts(self, character_name: str, text: str, request_id: str = "") -> None:
    if self.tts is None:
        return
    character = self.config.get_character_by_name(character_name)
    speed = float(getattr(character, "speech_speed", 1.0) or 1.0) if character else 1.0
    try:
        api_config = self.config.config.api_config
        segments = [text]
        if bool(getattr(api_config, "tts_split_enabled", False)):
            maximum = max(5, int(getattr(api_config, "tts_max_sentence_length", 15) or 15))
            pieces = [part.strip() for part in re.split(r"(?<=[。！？，、；：\.!\?,;:])", text) if part.strip()]
            segments, current = [], ""
            for piece in pieces:
                if not current or len(current) + len(piece) <= maximum:
                    current += piece
                else:
                    segments.append(current)
                    current = piece
            if current:
                segments.append(current)
            if not segments:
                segments = [text]
        for index, segment in enumerate(segments):
            path = self.tts.generate_tts(
                segment,
                text_processor=self.text_processor,
                character_name=character_name,
                speed_factor=speed,
            )
            if path:
                hooks.event("audio", {
                    "path": str(path),
                    "request_id": request_id,
                    "character_name": character_name,
                    "segment_index": index,
                    "segment_count": len(segments),
                })
    except Exception as exc:
        hooks.event("status", {"text": f"语音生成失败：{exc}", "busy": False})


def _generate_tts_for_delivery(self, character_name: str, text: str) -> str:
    if self.tts is None:
        return ""
    return str(self.tts.generate_tts(text, character_name=character_name) or "")


def _generate_photo(self, request: SelfieRequest) -> str:
    if self.selfie is None:
        return ""
    generated = self.selfie.generate(request)
    return generated.path if generated else ""


def _save_attachments(self, attachments: list[dict[str, Any]]) -> list[Path]:
    paths: list[Path] = []
    for attachment in attachments[:4]:
        data_url = str(attachment.get("dataUrl") or attachment.get("data_url") or "")
        match = re.match(r"^data:([^;,]+);base64,(.+)$", data_url, flags=re.DOTALL)
        if not match:
            continue
        extension = mimetypes.guess_extension(match.group(1)) or ".png"
        path = self.paths.input_images_dir / f"electron_{uuid.uuid4().hex}{extension}"
        path.write_bytes(base64.b64decode(match.group(2)))
        paths.append(path)
    return paths


def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
    with self.chat_lock:
        return self._chat(payload)


def observe_screen(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Use a temporary screen snapshot to learn durable, non-sensitive user habits."""
    name = str(payload.get("character_name") or self.config.resolve_active_character_name())
    character = self.config.get_character_by_name(name)
    if character is None:
        raise ValueError(f"角色不存在：{name}")
    paths = self._save_attachments(list(payload.get("attachments") or []))
    if not paths:
        return {"observed": False, "memories_added": 0}
    try:
        refs = "".join(f"\n[图片: {path.as_posix()}]" for path in paths)
        prompt = (
            "你是 here 的同桌观察助手。根据当前屏幕截图，判断用户是否表现出稳定、可长期帮助对话的工作习惯。\n"
            "只记录重复性或明显稳定的习惯，不记录当前文件正文、具体聊天内容、姓名、密码、验证码、账号、地址或其他敏感信息。\n"
            "同桌模式也可以主动陪伴，但只有在确实能帮上忙时才打扰用户。只输出严格 JSON 对象："
            '{"habits":[{"habit":"用户通常在晚上进行编程工作","confidence":0.82}],'
            '"should_speak":false,"message":""}。\n'
            "message 只写一句简短、自然的桌面对白；如果没有必要打扰，should_speak 必须为 false 且 message 为空。"
            "如果没有足够证据，habits 输出 []。单次画面不能证明稳定习惯。\n"
            f"{refs}"
        )
        context = build_agent_context(
            config_manager=self.config,
            memory_store=self.memory,
            system_template=self._companion_context_template(),
            session_id="screen-context",
            selected_character_names=[name],
            life_state="",
        )
        with self.chat_lock:
            raw = self.agent.chat(
                build_hermes_user_message(prompt),
                context=context,
                stream=False,
            )
        text = str(raw or "").strip()
        start = text.find("{")
        parsed: dict[str, Any] = {}
        if start >= 0:
            try:
                parsed = json.JSONDecoder().raw_decode(text[start:])[0]
            except (json.JSONDecodeError, TypeError):
                parsed = {}
        candidates = parsed.get("habits", []) if isinstance(parsed, dict) else []
        if not isinstance(candidates, list):
            candidates = []
        current = self.memory.read_user_profile(name)
        added: list[str] = []
        sensitive = re.compile(r"密码|验证码|口令|密钥|token|password|信用卡|身份证|私聊|聊天记录", re.IGNORECASE)
        for item in candidates:
            if not isinstance(item, dict):
                continue
            habit = str(item.get("habit") or "").strip()
            try:
                confidence = float(item.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0
            if not habit or confidence < 0.7 or len(habit) > 240 or sensitive.search(habit):
                continue
            if any(re.sub(r"\s+", "", habit).casefold() == re.sub(r"\s+", "", old).casefold() for old in current):
                continue
            current.append(habit)
            added.append(habit)
        if added:
            self.memory.write_user_profile(name, current[-100:])
        now = time.monotonic()
        message = str(parsed.get("message") or "").strip() if isinstance(parsed, dict) else ""
        should_speak = bool(parsed.get("should_speak")) if isinstance(parsed, dict) else False
        if should_speak and message and now - self.screen_context_last_prompt_at >= 30 * 60:
            self.screen_context_last_prompt_at = now
            self._emit_dialog(
                AgentDialogMessage(name=name, text=message, emotion="thinking"),
                request_id=f"screen-context-{uuid.uuid4().hex}",
            )
        return {"observed": True, "memories_added": len(added), "memories": added}
    finally:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _chat(self, payload: dict[str, Any]) -> dict[str, Any]:
    request_id = str(payload.get("request_id") or payload.get("requestId") or uuid.uuid4().hex)
    text = str(payload.get("text") or "").strip()
    name = str(payload.get("character_name") or payload.get("characterName") or self.config.resolve_active_character_name())
    if name != self.config.resolve_active_character_name():
        name = self.config.set_active_character_name(name)
        self.agent.reset_session()
    character = self.config.get_character_by_name(name)
    if character is None:
        raise ValueError(f"角色不存在：{name}")
    paths = self._save_attachments(list(payload.get("attachments") or []))
    message_text = text + "".join(f"\n[图片: {path.as_posix()}]" for path in paths)
    self._append_history(
        "user",
        "你",
        text or "[图片]",
        request_id=request_id,
        attachments=[path.name for path in paths],
    )
    self.proactive.note_user_message()
    hooks.event("chat_start", {"request_id": request_id, "character_name": name})
    life_state = ""
    try:
        self.life.observe_user_message(character, text, agent_backend=self.agent, allow_llm_generate=False)
        life_state = self.life.current_life_state(character, agent_backend=self.agent, allow_llm_generate=False)
    except Exception as exc:
        print(f"Life state update failed: {exc}")
    context = build_agent_context(
        config_manager=self.config,
        memory_store=self.memory,
        system_template=self._companion_context_template(),
        session_id="default",
        selected_character_names=[name],
        life_state=life_state,
    )
    raw = self.agent.chat(
        build_hermes_user_message(message_text),
        context=context,
        stream=bool(self.config.config.api_config.hermes_streaming),
    )
    chunks = raw if self.config.config.api_config.hermes_streaming else [raw]
    parser = AgentResponseStreamParser()
    dialogs: list[AgentDialogMessage] = []

    def publish_dialog(raw_dialog: AgentDialogMessage) -> None:
        current_name = self.config.resolve_active_character_name()
        dialog = self._handle_system_action(raw_dialog, active_character=current_name, user_text=text)
        current_name = self.config.resolve_active_character_name()
        if not self._is_reserved_dialog_name(str(dialog.name or "")) and str(dialog.name or "").strip() != current_name:
            dialog = dialog.model_copy(update={"name": current_name})
        dialogs.append(dialog)
        self._route_chat_dialog(dialog, request_id, current_name)

    for chunk in chunks:
        value = chunk if isinstance(chunk, str) else str(chunk or "")
        for dialog in parser.feed(value):
            publish_dialog(dialog)
    for dialog in parser.flush():
        publish_dialog(dialog)
    if not dialogs:
        for dialog in parser.recover_messages(parser.accumulated_text):
            publish_dialog(dialog)
    if not dialogs:
        fallback = parser.accumulated_text.strip() or "刚才没有拿到有效回复，我们再试一次。"
        publish_dialog(AgentDialogMessage(name=name, text=fallback, emotion="neutral"))
    hooks.event("chat_done", {"request_id": request_id})
    return {"request_id": request_id, "dialogs": [hooks.model_json(item) for item in dialogs]}


def stop_chat(self) -> None:
    self.agent.interrupt()
