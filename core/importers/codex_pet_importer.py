"""Import Codex/agent-pet spritesheets as here characters."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from infrastructure.paths import get_app_paths

from services.config.config_manager import ConfigManager
from services.config.schema import Character, Sprite
from internal_agent.context import AgentMemoryStore
from core.sprite.character_profile import (
    build_character_setting_from_profile,
    default_character_profile,
    normalize_character_profile,
)


STATE_GROUP_CORE_EMOTION = "core_emotion"
STATE_GROUP_SYSTEM_OPTIONAL_EMOTION = "system_optional_emotion"
STATE_GROUP_CUSTOM = "custom"
STATE_GROUP_MOUSE_EVENT = "mouse_event"

CORE_EMOTION_STATES: tuple[str, ...] = ("neutral", "happy", "thinking", "surprised", "sad", "angry")

SYSTEM_OPTIONAL_EMOTION_STATES: tuple[str, ...] = (
    "working",
    "reviewing",
)

MOUSE_EVENT_STATES: tuple[str, ...] = (
    "moving_right",
    "moving_left",
)

CODEX_PET_STATE_ROWS: tuple[tuple[str, str], ...] = (
    ("idle", "待机、普通、平静"),
    ("running-right", "向右移动、活跃"),
    ("running-left", "向左移动、活跃"),
    ("waving", "打招呼、欢迎"),
    ("jumping", "被点名、惊讶、注意力被拉起"),
    ("failed", "难过、失败、出错"),
    ("waiting", "等待、处理中"),
    ("running", "忙碌、执行中"),
    ("review", "检查、回顾、分析"),
)

CODEX_PET_DIALOG_STATE_MAP: dict[str, str] = {
    "idle": "neutral",
    "waving": "happy",
    "waiting": "thinking",
    "jumping": "surprised",
    "failed": "sad",
    "running": "working",
    "review": "reviewing",
    "running-right": "moving_right",
    "running-left": "moving_left",
}

CODEX_PET_STATE_TAGS: dict[str, str] = {
    "neutral": "默认、平静、普通、neutral",
    "happy": "开心、欢迎、打招呼、happy",
    "thinking": "思考、等待、处理中、thinking",
    "surprised": "惊讶、被点名、注意力被拉起、surprised",
    "sad": "难过、失败、出错、sad",
    "angry": "生气、不满、抗议、angry",
    "working": "忙碌、执行中、working",
    "reviewing": "检查、回顾、分析、reviewing",
    "moving_right": "向右移动、活跃、moving_right",
    "moving_left": "向左移动、活跃、moving_left",
}

CODEX_PET_FALLBACK_RULES = (
    "状态分组：核心情绪 core_emotion、系统可选情绪 system_optional_emotion、用户自定义 custom、鼠标事件 mouse_event。",
    "核心情绪标准名：neutral/happy/thinking/surprised/sad/angry；这些状态允许缺少，不会强行复制素材补齐。",
    "没有系统映射规则的导入状态保留原始名称，并标记为 custom。",
)


@dataclass(frozen=True)
class CodexPetImportResult:
    character_name: str
    pet_id: str
    asset_dir: Path
    spritesheet_path: Path
    frame_count: int
    state_count: int
    created: bool


def default_codex_pet_search_dirs() -> list[Path]:
    """Common local folders used by Codex pet and agent-pet assets."""
    home = Path.home()
    candidates = [
        home / ".codex" / "pets",
        home / "Library" / "Application Support" / "agent-pet" / "pets",
        home / ".config" / "agent-pet" / "pets",
    ]
    return [p for p in candidates if p.exists()]


def find_codex_pet_dirs() -> list[Path]:
    """Return directories containing a ``pet.json`` file."""
    found: list[Path] = []
    for base in default_codex_pet_search_dirs():
        if (base / "pet.json").exists():
            found.append(base)
        try:
            for child in base.iterdir():
                if child.is_dir() and (child / "pet.json").exists():
                    found.append(child)
        except OSError:
            continue
    return found


def import_codex_pet_as_character(
    pet_dir: str | Path,
    *,
    config_manager: ConfigManager | None = None,
    make_active: bool = True,
) -> CodexPetImportResult:
    """Import an agent-pet/Codex pet folder into here.

    The importer expands the 8x9 spritesheet into PNG frame folders because
    the current desktop renderer already consumes ``Sprite.frames`` directly.
    """
    cfg = config_manager or ConfigManager()
    source_dir = Path(pet_dir).expanduser().resolve()
    metadata = _load_pet_metadata(source_dir)
    sheet_src = _find_spritesheet(source_dir, metadata)
    pet_id = _safe_slug(str(metadata.get("id") or metadata.get("name") or source_dir.name))
    display_name = _unique_character_name(
        _display_name(metadata, source_dir),
        [str(c.name or "").strip() for c in cfg.config.characters],
    )

    asset_dir = get_app_paths().characters_dir / "codex_pets" / pet_id
    frames_dir = asset_dir / "animations"
    asset_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_dir / "pet.json", asset_dir / "pet.json")
    sheet_dst = asset_dir / f"spritesheet{sheet_src.suffix.lower()}"
    shutil.copy2(sheet_src, sheet_dst)

    image = Image.open(sheet_src).convert("RGBA")
    columns = int(metadata.get("columns") or metadata.get("cols") or 8)
    rows = int(metadata.get("rows") or 9)
    frame_width = int(metadata.get("frameWidth") or metadata.get("frame_width") or image.width // columns)
    frame_height = int(metadata.get("frameHeight") or metadata.get("frame_height") or image.height // rows)
    frame_count = int(metadata.get("frameCount") or metadata.get("frame_count") or columns)
    frame_count = max(1, min(columns, frame_count))
    interval_ms = _frame_interval_ms(metadata)

    extracted: dict[str, Sprite] = {}
    for row_index, (state_name, tags) in enumerate(CODEX_PET_STATE_ROWS):
        if row_index >= rows:
            break
        state_dir = frames_dir / state_name
        state_dir.mkdir(parents=True, exist_ok=True)
        frame_paths: list[str] = []
        for col_index in range(frame_count):
            left = col_index * frame_width
            top = row_index * frame_height
            if left >= image.width or top >= image.height:
                continue
            frame = image.crop(
                (
                    left,
                    top,
                    min(left + frame_width, image.width),
                    min(top + frame_height, image.height),
                )
            )
            if _is_transparent_frame(frame):
                continue
            out_path = state_dir / f"frame_{col_index + 1:02d}.png"
            frame.save(out_path)
            frame_paths.append(out_path.as_posix())
        if not frame_paths:
            continue
        extracted[state_name] = Sprite(
            path=frame_paths[0],
            frames=frame_paths,
            spritesheet_path=sheet_dst.as_posix(),
            frame_width=frame_width,
            frame_height=frame_height,
            frame_count=len(frame_paths),
            frame_row=row_index,
            frame_col=0,
            frame_interval_ms=interval_ms,
        )

    if not extracted:
        raise ValueError(f"未能从 Codex Pet spritesheet 切出有效帧：{sheet_src}")

    sprites, sprite_state_rows = _mapped_dialog_sprites(extracted)

    profile = _character_profile(display_name, metadata)
    character = Character(
        name=display_name,
        color=str(metadata.get("color") or "#84C2D5"),
        sprite_prefix=f"codex_pet_{pet_id}",
        sprites=sprites,
        character_profile=profile,
        character_setting=build_character_setting_from_profile(display_name, profile),
        visual_reference_image=str(sprites[0].path),
        visual_identity=_visual_identity(display_name, metadata),
        sprite_scale=float(metadata.get("hereSpriteScale") or 0.72),
        emotion_tags=_emotion_tags(sprite_state_rows),
    )

    cfg.config.characters.append(character)
    cfg.save_characters_config()
    _ensure_character_memory(display_name, metadata)
    if make_active:
        cfg.set_active_character_name(display_name)
    return CodexPetImportResult(
        character_name=display_name,
        pet_id=pet_id,
        asset_dir=asset_dir,
        spritesheet_path=sheet_dst,
        frame_count=sum(len(s.frames or []) for s in sprites),
        state_count=len(sprites),
        created=True,
    )


def _load_pet_metadata(source_dir: Path) -> dict[str, Any]:
    pet_json = source_dir / "pet.json"
    if not pet_json.exists():
        raise FileNotFoundError(f"不是有效 Codex Pet 目录，缺少 pet.json：{source_dir}")
    try:
        data = json.loads(pet_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"pet.json 格式无效：{pet_json}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"pet.json 顶层必须是对象：{pet_json}")
    return data


def _find_spritesheet(source_dir: Path, metadata: dict[str, Any]) -> Path:
    candidates: list[Path] = []
    for key in ("spritesheet", "spritesheetPath", "image", "imagePath", "texture"):
        value = metadata.get(key)
        if value:
            candidates.append(source_dir / str(value))
    candidates.extend(
        [
            source_dir / "spritesheet.webp",
            source_dir / "spritesheet.png",
            source_dir / "spritesheet.jpg",
            source_dir / "spritesheet.jpeg",
        ]
    )
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Codex Pet 目录缺少 spritesheet.webp/png：{source_dir}")


def _display_name(metadata: dict[str, Any], source_dir: Path) -> str:
    for key in ("displayName", "display_name", "name", "title"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return source_dir.name


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", value.strip())
    slug = slug.strip("._-")
    return slug or "codex_pet"


def _unique_character_name(base_name: str, existing_names: list[str]) -> str:
    base = str(base_name or "Codex Pet").strip() or "Codex Pet"
    used = {n for n in existing_names if n}
    if base not in used:
        return base
    index = 2
    while f"{base} {index}" in used:
        index += 1
    return f"{base} {index}"


def _frame_interval_ms(metadata: dict[str, Any]) -> int:
    fps = metadata.get("fps")
    if fps:
        try:
            f = float(fps)
            if f > 0:
                return max(16, int(1000 / f))
        except (TypeError, ValueError):
            pass
    interval = metadata.get("frameIntervalMs") or metadata.get("frame_interval_ms")
    try:
        return max(16, int(interval or 120))
    except (TypeError, ValueError):
        return 120


def _is_transparent_frame(frame: Image.Image) -> bool:
    if frame.mode != "RGBA":
        frame = frame.convert("RGBA")
    alpha = frame.getchannel("A")
    return alpha.getbbox() is None


def _character_profile(name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    raw_profile = metadata.get("hereCharacterProfile") or metadata.get("character_profile")
    profile = normalize_character_profile(name, raw_profile, preset="pet")
    if isinstance(metadata.get("mbti"), str):
        profile["personality"]["mbti"] = metadata["mbti"].upper()
    if metadata.get("personality"):
        profile["personality"]["custom_traits"] = [str(metadata["personality"]).strip()]
    return profile


def _visual_identity(name: str, metadata: dict[str, Any]) -> str:
    return f"{name} 是像素风格的桌面精灵，动作轻快，表情清晰，适合在桌面上陪伴用户。"


def _clone_sprite(sprite: Sprite) -> Sprite:
    return Sprite.model_validate(sprite.model_dump())


def _state_group(state_name: str) -> str:
    if state_name in CORE_EMOTION_STATES:
        return STATE_GROUP_CORE_EMOTION
    if state_name in SYSTEM_OPTIONAL_EMOTION_STATES:
        return STATE_GROUP_SYSTEM_OPTIONAL_EMOTION
    if state_name in MOUSE_EVENT_STATES:
        return STATE_GROUP_MOUSE_EVENT
    return STATE_GROUP_CUSTOM


def _mapped_dialog_sprites(extracted: dict[str, Sprite]) -> tuple[list[Sprite], list[tuple[str, str, str, str]]]:
    """Return sprites ordered by here state concepts, not raw pet rows."""
    mapped: dict[str, str] = {}
    custom: list[tuple[str, str]] = []
    for source_state in extracted:
        state_name = CODEX_PET_DIALOG_STATE_MAP.get(source_state)
        if state_name:
            mapped.setdefault(state_name, source_state)
        else:
            custom.append((source_state, source_state))

    ordered_state_names = (
        *CORE_EMOTION_STATES,
        *SYSTEM_OPTIONAL_EMOTION_STATES,
        *MOUSE_EVENT_STATES,
    )
    ordered_pairs: list[tuple[str, str]] = [
        (state_name, mapped[state_name])
        for state_name in ordered_state_names
        if state_name in mapped
    ]
    ordered_pairs.extend(custom)

    rows: list[tuple[str, str, str, str]] = []
    sprites: list[Sprite] = []
    used_pairs: set[tuple[str, str]] = set()

    def add(dialog_state: str, source_state: str) -> None:
        key = (dialog_state, source_state)
        if key in used_pairs:
            return
        source_sprite = extracted.get(source_state)
        if source_sprite is None:
            return
        sprite = _clone_sprite(source_sprite)
        group = _state_group(dialog_state)
        sprite.state_name = dialog_state
        sprite.state_group = group
        sprite.source_state = source_state
        sprites.append(sprite)
        rows.append((dialog_state, group, source_state, CODEX_PET_STATE_TAGS.get(dialog_state, dialog_state)))
        used_pairs.add(key)

    for dialog_state, source_state in ordered_pairs:
        add(dialog_state, source_state)

    return sprites, rows


def _emotion_tags(sprite_state_rows: list[tuple[str, str, str, str]]) -> str:
    lines: list[str] = []
    lines.extend(CODEX_PET_FALLBACK_RULES)
    lines.append("")
    for idx, (dialog_state, group, source_state, tags) in enumerate(sprite_state_rows, start=1):
        source_note = "" if source_state == dialog_state else f"；来源 Codex Pet 状态：{source_state}"
        lines.append(f"立绘 {idx}：{dialog_state}；分组：{group}；{tags}{source_note}")
    return "\n".join(lines)


def _ensure_character_memory(name: str, metadata: dict[str, Any]) -> None:
    store = AgentMemoryStore()
    if store.read_character_memories(name):
        return
    source = str(metadata.get("name") or metadata.get("id") or "").strip()
    memories = [
        f"- {name} 是从 Codex Pet 导入的桌面精灵角色。",
    ]
    if source:
        memories.append(f"- 原始 pet 标识：{source}")
    store.write_character_memories(name, memories)
