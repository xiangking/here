from __future__ import annotations

from typing import Any

from bridge import hooks
from bridge.deps import Path, hashlib


def generate_image(self, payload: dict[str, Any]) -> dict[str, Any]:
    if self.t2i is None:
        raise RuntimeError("当前生图适配器未成功初始化。")
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("生图提示词不能为空。")
    hooks.event("status", {"text": "正在生成图片…", "busy": True})
    path = self.t2i.t2i(prompt, **dict(payload.get("options") or {}))
    hooks.event("status", {"text": "图片生成完成。" if path else "图片生成失败。", "busy": False})
    return {"path": str(path or "")}


def generate_realtime_sprite(self, payload: dict[str, Any]) -> dict[str, Any]:
    system = self.config.config.system_config
    if not bool(system.sprite_realtime_enabled):
        return {"path": "", "enabled": False}
    if self.t2i is None:
        raise RuntimeError("实时立绘已启用，但当前生图适配器未成功初始化。")
    character_name = str(payload.get("character_name") or self.config.resolve_active_character_name()).strip()
    emotion = str(payload.get("emotion") or "neutral").strip() or "neutral"
    scene = str(payload.get("scene") or "normal").strip() or "normal"
    template = str(system.sprite_realtime_prompt_template or "").strip() or (
        "{character_name}, {emotion} expression, {scene}, anime style, high quality, "
        "detailed, masterpiece, white background, full body, standing pose"
    )
    try:
        prompt = template.format(character_name=character_name, emotion=emotion, scene=scene)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"实时立绘提示词模板无效：{exc}") from exc
    cache_root = Path(str(system.sprite_realtime_cache_dir or "")).expanduser()
    if not str(system.sprite_realtime_cache_dir or "").strip():
        cache_root = self.paths.cache_dir / "sprite_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    api = self.config.config.api_config
    fingerprint = "\n".join((prompt, str(api.t2i_provider or ""), str(api.t2i_api_url or "")))
    cache_key = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    safe_name = self._safe_asset_name(character_name, "character")
    cache_path = cache_root / f"{safe_name}_{cache_key}.png"
    if not cache_path.is_file():
        hooks.event("status", {"text": f"正在生成 {character_name} 的立绘…", "busy": True})
        result = self.t2i.t2i(prompt, file_path=cache_path.as_posix())
        if not result or not Path(result).is_file():
            hooks.event("status", {"text": "实时立绘生成失败，已保留当前立绘。", "busy": False})
            return {"path": "", "enabled": True, "cached": False}
        cache_path = Path(result)
    hooks.event("status", {"text": "", "busy": False})
    character = self.config.get_character_by_name(character_name)
    return {
        "path": cache_path.as_posix(),
        "enabled": True,
        "cached": cache_path.is_file(),
        "scale": float(getattr(character, "sprite_scale", 1.0) or 1.0),
    }
