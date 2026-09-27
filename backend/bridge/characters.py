from __future__ import annotations

from typing import Any

from bridge import hooks
from bridge.deps import (
    Character,
    CharacterManager,
    Path,
    SYSTEM_CHARACTER_NAME,
    Sprite,
    base64,
    default_character_profile,
    find_codex_pet_dirs,
    import_codex_pet_as_character,
    mimetypes,
    normalize_character_profile,
    re,
    resolve_character_asset_path,
    shutil,
    uuid,
)
from infrastructure.asset_paths import (
    UnsafeSpritePrefixError,
    collect_referenced_asset_paths,
    is_inside_owned_dir,
    is_referenced_target,
    owned_character_dir,
    prepare_owned_character_dir,
    referenced_inside_directory,
    remove_owned_character_dir,
    validate_sprite_prefix,
)


def upload_character_sprites(self, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("character_name") or self.config.resolve_active_character_name())
    character = self.config.get_character_by_name(name)
    if character is None:
        raise ValueError(f"角色不存在：{name}。请先保存新角色，再添加立绘。")
    prefix = str(character.sprite_prefix or "").strip() or self._safe_asset_name(name, "character")
    target = prepare_owned_character_dir(self.paths.characters_dir, prefix)
    added = 0
    for attachment in list(payload.get("attachments") or []):
        data_url = str(attachment.get("dataUrl") or attachment.get("data_url") or "")
        match = re.match(r"^data:([^;,]+);base64,(.+)$", data_url, flags=re.DOTALL)
        if not match:
            continue
        extension = mimetypes.guess_extension(match.group(1)) or ".png"
        raw_name = Path(str(attachment.get("name") or f"sprite_{added + 1}{extension}")).name
        stem = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", Path(raw_name).stem).strip("_") or f"sprite_{added + 1}"
        path = target / f"{stem}_{uuid.uuid4().hex[:6]}{extension}"
        path.write_bytes(base64.b64decode(match.group(2)))
        character.sprites.append(Sprite(path=path, state_name="", state_group="custom"))
        added += 1
    if not added:
        raise ValueError("没有可用的立绘图片。")
    character.emotion_tags = str(payload.get("emotion_tags") or character.emotion_tags or "")
    self.config.save_characters_config()
    return self.state()


def create_character(self, payload: dict[str, Any]) -> dict[str, Any]:
    requested = str(payload.get("name") or "").strip()
    setting = str(payload.get("setting") or "").strip()
    raw_states = payload.get("states") if isinstance(payload.get("states"), list) else []
    states: list[dict[str, Any]] = []
    for raw_state in raw_states:
        if not isinstance(raw_state, dict):
            continue
        paths = [Path(str(value)).expanduser().resolve() for value in raw_state.get("paths", [])]
        paths = [path for path in paths if path.is_file()]
        if paths:
            states.append({**raw_state, "paths": paths})
    if not states:
        paths = [Path(str(value)).expanduser().resolve() for value in payload.get("paths", [])]
        paths = [path for path in paths if path.is_file()]
        if paths:
            states = [{
                "state_name": str(payload.get("state_name") or "neutral"),
                "state_group": str(payload.get("state_group") or "core_emotion"),
                "frame_interval_ms": int(payload.get("frame_interval_ms") or 120),
                "paths": paths,
            }]
    if not requested:
        raise ValueError("角色名不能为空。")
    if not setting:
        raise ValueError("请填写角色人设。")
    if not states:
        raise ValueError("至少需要导入一个立绘图片或动画。")
    names = {str(character.name or "").strip() for character in self.config.config.characters}
    name = requested
    if name in names:
        raise ValueError(f"角色名称已存在：{name}")
    previous_active = self.config.resolve_active_character_name()
    raw_profile = payload.get("character_profile")
    profile = normalize_character_profile(name, raw_profile) if isinstance(raw_profile, dict) else default_character_profile(name)
    character = Character(
        name=name,
        color=str(payload.get("color") or "#84c2d5"),
        sprite_prefix=f"character_{uuid.uuid4().hex[:10]}",
        sprites=[],
        character_profile=profile,
        character_setting=setting,
        visual_reference_image="",
        visual_identity=str(payload.get("visual_identity") or "").strip(),
        sprite_scale=float(
            getattr(self.config.config.system_config, "default_sprite_scale", 0.72)
            or 0.72
        ),
        emotion_tags="",
        speech_speed=1.0,
        speech_volume=1.0,
        pronunciation_map={},
    )
    self.config.config.characters.append(character)
    try:
        self.config.save_characters_config()
        self.config.set_active_character_name(name)
        for sprite_state in states:
            self.import_character_state_assets({
                "character_name": name,
                "state_name": str(sprite_state.get("state_name") or "neutral"),
                "state_group": str(sprite_state.get("state_group") or "core_emotion"),
                "frame_interval_ms": int(sprite_state.get("frame_interval_ms") or 120),
                "paths": [path.as_posix() for path in sprite_state["paths"]],
            })
        # Qt stores the first imported sprite as the visual reference and
        # seeds the emotion prompt with the imported state mapping. Keep
        # both values available to T2I and the agent immediately after
        # creating a character.
        if character.sprites:
            first_sprite = hooks.model_json(character.sprites[0])
            character.visual_reference_image = str(first_sprite.get("path") or "")
            tag_lines = [
                "状态分组：核心情绪 core_emotion、系统可选情绪 system_optional_emotion、用户自定义 custom、鼠标事件 mouse_event。",
                "核心情绪标准名：neutral/happy/thinking/surprised/sad/angry；这些状态允许缺少。",
                "",
            ]
            state_tags = {
                "neutral": "默认、平静、普通、neutral",
                "happy": "开心、欢迎、打招呼、happy",
                "thinking": "思考、等待、处理中、thinking",
                "surprised": "惊讶、被点名、注意力被拉起、surprised",
                "sad": "难过、失败、出错、sad",
                "angry": "生气、不满、抗议、angry",
            }
            for index, sprite in enumerate(character.sprites, start=1):
                raw_sprite = hooks.model_json(sprite)
                state_name = str(raw_sprite.get("state_name") or "custom").strip() or "custom"
                group = str(raw_sprite.get("state_group") or "custom").strip() or "custom"
                tags = state_tags.get(state_name, state_name)
                tag_lines.append(f"立绘 {index}：{state_name}；分组：{group}；{tags}")
            character.emotion_tags = "\n".join(tag_lines)
            self.config.save_characters_config()
        self.reload_runtime()
    except Exception:
        self.config.config.characters = [item for item in self.config.config.characters if item.name != name]
        self.config.save_characters_config()
        self.config.set_active_character_name(previous_active)
        remove_owned_character_dir(self.paths.characters_dir, character.sprite_prefix)
        raise
    hooks.event("character", {"name": name})
    return self.state()


def _safe_asset_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", str(value or "")).strip("_")
    return cleaned or fallback


def import_character_state_assets(self, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("character_name") or self.config.resolve_active_character_name())
    character = self.config.get_character_by_name(name)
    if character is None:
        raise ValueError(f"角色不存在：{name}")
    source_paths = [Path(str(value)).expanduser().resolve() for value in payload.get("paths", [])]
    source_paths = [path for path in source_paths if path.is_file()]
    if not source_paths:
        raise ValueError("没有选择有效的立绘或动画文件。")
    state_name = self._safe_asset_name(str(payload.get("state_name") or "custom"), "custom")
    if state_name == "video_call" and (len(source_paths) != 1 or source_paths[0].suffix.lower() not in {".mp4", ".webm", ".m4v"}):
        raise ValueError("视频通话请选择一个 MP4、WebM 或 M4V 视频。")
    state_group = str(payload.get("state_group") or "custom").strip() or "custom"
    interval = max(20, min(10_000, int(payload.get("frame_interval_ms") or 120)))
    prefix = str(character.sprite_prefix or "").strip() or self._safe_asset_name(name, "character")
    character_dir = prepare_owned_character_dir(self.paths.characters_dir, prefix)
    animations_dir = character_dir / "animations"
    target_dir = animations_dir / state_name

    previous_sprites = list(character.sprites)
    target_index: int | None = None
    previous_sprite: dict[str, Any] = {}
    if payload.get("sprite_index") is not None:
        target_index = int(payload["sprite_index"])
        if target_index < 0 or target_index >= len(character.sprites):
            raise ValueError("立绘索引无效。")
        previous_sprite = hooks.model_json(character.sprites[target_index])

    # Replacing a state folder must not destroy frames another character (or
    # another sprite of this character) still points at.
    replaced_index: int | None = target_index
    if replaced_index is None:
        replaced_index = next(
            (
                index
                for index, existing in enumerate(character.sprites)
                if str(
                    getattr(existing, "state_name", "")
                    or (existing.get("state_name") if isinstance(existing, dict) else "")
                )
                == state_name
            ),
            None,
        )
    if target_dir.exists():
        referenced = collect_referenced_asset_paths(
            self.config.config.characters,
            lambda text: resolve_character_asset_path(text, self.paths),
            skip=(name, replaced_index) if replaced_index is not None else None,
        )
        if referenced_inside_directory(target_dir, referenced):
            raise UnsafeSpritePrefixError("目标目录中的文件仍被其他立绘或角色引用，已取消替换。")

    # Build every frame in a staging folder first. The previously imported
    # state stays untouched until the new assets are fully generated, so a
    # failed conversion can never destroy the working sprites.
    staging_dir = animations_dir / f".pending-{uuid.uuid4().hex}"
    backup_dir = animations_dir / f".backup-{uuid.uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    if not is_inside_owned_dir(staging_dir, character_dir, allow_root=False):
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise UnsafeSpritePrefixError("资源路径超出允许的目录。")

    def _final_path(path: Path) -> Path:
        try:
            return target_dir / path.relative_to(staging_dir)
        except ValueError:
            return path

    installed = False
    moved_old = False
    try:
        video_suffixes = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
        frames: list[Path] = []
        native_video = len(source_paths) == 1 and state_name == "video_call" and source_paths[0].suffix.lower() in {".mp4", ".webm", ".m4v"}
        if native_video:
            first_path = staging_dir / f"video_call{source_paths[0].suffix.lower()}"
            shutil.copy2(source_paths[0], first_path)
        elif len(source_paths) == 1 and source_paths[0].suffix.lower() in video_suffixes:
            try:
                import cv2
            except ImportError as exc:
                raise RuntimeError("导入视频立绘需要 opencv-python，请先在语音与依赖页安装视频支持。") from exc
            capture = cv2.VideoCapture(source_paths[0].as_posix())
            frame_index = 0
            try:
                while capture.isOpened():
                    ok, frame = capture.read()
                    if not ok:
                        break
                    destination = staging_dir / f"frame_{frame_index + 1:04d}.png"
                    if not cv2.imwrite(destination.as_posix(), frame):
                        # OpenCV reports write failures (e.g. disk full) by returning
                        # False instead of raising, so surface it as an error to keep
                        # the previous assets intact.
                        raise RuntimeError(
                            f"写入视频帧失败：{source_paths[0].name}（第 {frame_index + 1} 帧）。"
                        )
                    frames.append(destination)
                    frame_index += 1
            finally:
                capture.release()
            if not frames:
                raise RuntimeError("没有从视频中提取到有效帧。")
        elif len(source_paths) == 1 and source_paths[0].suffix.lower() in {".gif", ".webp"}:
            from PIL import Image, ImageSequence

            with Image.open(source_paths[0]) as image:
                for frame_index, frame in enumerate(ImageSequence.Iterator(image)):
                    destination = staging_dir / f"frame_{frame_index + 1:04d}.png"
                    frame.convert("RGBA").save(destination, format="PNG")
                    frames.append(destination)
                    duration = int(frame.info.get("duration") or 0)
                    if frame_index == 0 and duration > 0 and not payload.get("frame_interval_ms"):
                        interval = max(20, min(10_000, duration))
            if len(frames) <= 1:
                frames = []
        if native_video:
            pass
        elif not frames:
            copied: list[Path] = []
            for index, source in enumerate(source_paths):
                suffix = source.suffix.lower()
                if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
                    raise ValueError(f"不支持的立绘格式：{source.name}")
                destination = staging_dir / f"frame_{index + 1:04d}{suffix}"
                shutil.copy2(source, destination)
                copied.append(destination)
            frames = copied if len(copied) > 1 else []
            first_path = copied[0]
        else:
            first_path = frames[0]

        # Publish the staged folder atomically, keeping the old one as backup.
        if target_dir.exists():
            if not is_inside_owned_dir(target_dir, character_dir, allow_root=False):
                raise UnsafeSpritePrefixError("资源路径超出允许的目录。")
            target_dir.rename(backup_dir)
            moved_old = True
        staging_dir.rename(target_dir)
        installed = True

        try:
            sprite = Sprite(
                path=_final_path(first_path),
                frames=[_final_path(path).as_posix() for path in frames],
                frame_interval_ms=interval,
                state_name=state_name,
                state_group=state_group,
                source_state=state_name,
                voice_path=previous_sprite.get("voice_path") or None,
                voice_text=previous_sprite.get("voice_text") or None,
            )
            if target_index is not None:
                character.sprites[target_index] = sprite
            else:
                existing_index = next(
                    (
                        index
                        for index, existing in enumerate(character.sprites)
                        if str(getattr(existing, "state_name", "") or (existing.get("state_name") if isinstance(existing, dict) else "")) == state_name
                    ),
                    -1,
                )
                if existing_index >= 0:
                    character.sprites[existing_index] = sprite
                else:
                    character.sprites.append(sprite)
            self.config.save_characters_config()
        except Exception:
            character.sprites = previous_sprites
            if installed:
                shutil.rmtree(target_dir, ignore_errors=True)
            if moved_old and backup_dir.exists() and not target_dir.exists():
                backup_dir.rename(target_dir)
            raise
        shutil.rmtree(backup_dir, ignore_errors=True)
        return self.state()
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        if moved_old and not installed and backup_dir.exists() and not target_dir.exists():
            backup_dir.rename(target_dir)
        raise


def delete_character_sprite(self, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("character_name") or self.config.resolve_active_character_name())
    character = self.config.get_character_by_name(name)
    if character is None:
        raise ValueError(f"角色不存在：{name}")
    index = int(payload.get("index") or 0)
    if index < 0 or index >= len(character.sprites):
        raise ValueError("立绘索引无效。")
    sprite = character.sprites[index]
    raw = hooks.model_json(sprite)
    prefix = ""
    asset_root = None
    voice_root = None
    try:
        prefix = validate_sprite_prefix(character.sprite_prefix)
        asset_root = owned_character_dir(self.paths.characters_dir, prefix)
        voice_root = owned_character_dir(self.paths.generated_dir / "voices", prefix)
    except UnsafeSpritePrefixError:
        prefix = ""
        asset_root = None
        voice_root = None
    # A file shared with another character (or another sprite of this character)
    # must survive the removal of this one reference.
    referenced = collect_referenced_asset_paths(
        self.config.config.characters,
        lambda text: resolve_character_asset_path(text, self.paths),
        skip=(name, index),
    )
    referenced_values = [raw.get("path"), *(raw.get("frames") or []), raw.get("spritesheet_path"), raw.get("voice_path")]
    for candidate in referenced_values:
        if not candidate or asset_root is None:
            continue
        try:
            path = resolve_character_asset_path(candidate, self.paths).resolve()
            if path.is_file() and is_inside_owned_dir(path, asset_root):
                if not is_referenced_target(path, referenced):
                    path.unlink(missing_ok=True)
            elif path.is_dir() and is_inside_owned_dir(path, asset_root):
                if not referenced_inside_directory(path, referenced):
                    shutil.rmtree(path, ignore_errors=True)
        except (OSError, RuntimeError, ValueError):
            continue
    voice_path = str(raw.get("voice_path") or "").strip()
    if voice_path and voice_root is not None:
        try:
            voice = Path(voice_path).expanduser().resolve()
            if voice.is_file() and is_inside_owned_dir(voice, voice_root):
                if not is_referenced_target(voice, referenced):
                    voice.unlink(missing_ok=True)
        except (OSError, RuntimeError, ValueError):
            pass
    character.sprites.pop(index)
    # Keep the legacy numbered emotion notes aligned with the sprite list.
    tags = str(character.emotion_tags or "").splitlines()
    if tags and 0 <= index < len(tags):
        del tags[index]
        normalized: list[str] = []
        for number, line in enumerate(tags, start=1):
            if "：" in line:
                detail = line.split("：", 1)[1].strip()
            elif ":" in line:
                detail = line.split(":", 1)[1].strip()
            else:
                detail = line.strip()
            normalized.append(f"立绘 {number}：{detail}" if detail else f"立绘 {number}：")
        character.emotion_tags = "\n".join(normalized)
    self.config.save_characters_config()
    return self.state()


def delete_character(self, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or self.config.resolve_active_character_name()).strip()
    if name == SYSTEM_CHARACTER_NAME:
        raise ValueError("内置系统角色不能删除。")
    if len(self.config.config.characters) <= 1:
        raise ValueError("不能删除最后一个角色。")
    message, _ = CharacterManager().delete_character(name, delete_memory=bool(payload.get("delete_memory")))
    if any(token in message for token in ("找不到", "不能", "资源前缀")):
        raise ValueError(message)
    self.reload_runtime()
    active = self.config.resolve_active_character_name()
    hooks.event("character", {"name": active})
    return self.state()


def resolve_assets(self, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("character_name") or self.config.resolve_active_character_name())
    character = self.config.get_character_by_name(name)
    if character is None:
        return {"sprites": []}
    sprites = []
    for index, sprite in enumerate(character.sprites):
        raw = hooks.model_json(sprite)
        raw["index"] = index
        raw["path"] = resolve_character_asset_path(raw.get("path"), self.paths).as_posix()
        raw["frames"] = [
            resolve_character_asset_path(path, self.paths).as_posix()
            for path in raw.get("frames", [])
        ]
        if raw.get("spritesheet_path"):
            raw["spritesheet_path"] = resolve_character_asset_path(raw["spritesheet_path"], self.paths).as_posix()
        sprites.append(raw)
    return {"name": name, "scale": character.sprite_scale, "color": character.color, "sprites": sprites}


def codex_pet_candidates(self) -> list[str]:
    return [path.as_posix() for path in find_codex_pet_dirs()]


def import_codex_pet(self, payload: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(payload.get("path") or "")).expanduser()
    imported = import_codex_pet_as_character(path, config_manager=self.config, make_active=True)
    self.reload_runtime()
    hooks.event("character", {"name": imported.character_name})
    return {
        "import": hooks.model_json(imported.__dict__),
        "state": self.state(),
    }
