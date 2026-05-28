"""
集中定义从 worker 发往主界面的 Qt 信号，以及在此之上封装的对话/立绘/BGM/特效等操作。

这类方法从 UI 工作线程调用，内部通过信号跨线程更新主界面；BGM/音效使用 pygame，与 UIWorker 中的对话通道分离。
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from html import escape
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List, MutableSequence, Optional, Tuple

import cv2
import numpy as np
import pygame
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTextDocument

from services.config.config_manager import ConfigManager
from services.t2i.t2i_manager import T2IManager

SOUND_EFFECT_CHANNEL_ID = 6
SOUND_EFFECTS_PATH = {
    "DISAPPOINTED": "./assets/system/sound/disappointed.wav",
    "SHOCKED": "./assets/system/sound/shocked.wav",
    "ATTENTION": "./assets/system/sound/attention.wav",
}

_config_manager = ConfigManager()
_CSS_COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgba?\([0-9.,% ]+\))$")
_MARKDOWN_HINT_RE = re.compile(
    r"(^|\n)\s{0,3}(#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s+)|"
    r"(\*\*|__|`|\[.+?\]\(.+?\)|\|.+\|)"
)


def get_character_by_name(name: str):
    return _config_manager.get_character_by_name(name)


def _safe_css_color(color: str) -> str:
    color = str(color or "").strip()
    return color if _CSS_COLOR_RE.match(color) else "white"


def _speech_to_html(speech: str) -> str:
    text = str(speech or "")
    if not text.strip():
        return ""
    if not _MARKDOWN_HINT_RE.search(text):
        return escape(text).replace("\n", "<br>")
    doc = QTextDocument()
    doc.setMarkdown(text)
    body = doc.toHtml()
    match = re.search(r"<body[^>]*>(.*)</body>", body, flags=re.IGNORECASE | re.DOTALL)
    if match:
        body = match.group(1)
    body = re.sub(r"</?body[^>]*>", "", body, flags=re.IGNORECASE)
    return body.strip()


class UIUpdateManager(QObject):
    update_sprite_signal = Signal(np.ndarray, str, float)  # 图像, 角色名, 缩放
    update_sprite_animation_signal = Signal(object, str, float, int)  # 帧列表, 角色名, 缩放, 帧间隔(ms)
    update_dialog_signal = Signal(str)
    update_notification_signal = Signal(str)
    update_busy_bar_signal = Signal(str, float)  # 文案, 显示秒数（<=0 则不定时隐藏）；空文案表示关闭
    update_option_signal = Signal(list)
    update_value_signal = Signal(str)
    update_bg = Signal(str)
    update_cg = Signal(str)
    agent_reply_finished_signal = Signal()
    pause_asr_signal = Signal()

    def __init__(
        self,
        parent: Optional[QObject] = None,
        chat_history: Optional[MutableSequence[str]] = None,
        bg_group: Optional[List] = None,
        t2i_manager: Optional[T2IManager] = None,
    ) -> None:
        super().__init__(parent)
        self.chat_history: MutableSequence[str] = chat_history if chat_history is not None else []
        self.bg_group: List = list(bg_group or [])
        self.current_bgm_path: Optional[str] = None
        self.t2i_manager = t2i_manager
        self._sprite_image_cache: "OrderedDict[str, Tuple[Tuple[int, int], np.ndarray]]" = OrderedDict()
        self._sprite_image_cache_limit = 32

    # --- 低层：仅发信号 ---

    def post_sprite_update(self, image: np.ndarray, character_name: str, scale: float) -> None:
        self.update_sprite_signal.emit(image, character_name, scale)

    def post_sprite_animation_update(
        self,
        frames: List[np.ndarray],
        character_name: str,
        scale: float,
        frame_interval_ms: int,
    ) -> None:
        self.update_sprite_animation_signal.emit(frames, character_name, scale, int(frame_interval_ms))

    def post_dialog(self, formatted_html: str) -> None:
        self.update_dialog_signal.emit(formatted_html)

    def post_notification(self, text: str) -> None:
        self.update_notification_signal.emit(text)

    def post_busy_bar(self, text: str, duration_seconds: float = 3.0) -> None:
        """主线程：在聊天窗底栏上方显示加载条。duration_seconds<=0 时显示到 ``hide_busy_bar`` 为止。"""
        self.update_busy_bar_signal.emit(text, float(duration_seconds))

    def hide_busy_bar(self) -> None:
        self.update_busy_bar_signal.emit("", 0.0)

    def post_options(self, option_list: List[str]) -> None:
        self.update_option_signal.emit(option_list)

    def post_numeric_value(self, text: str) -> None:
        self.update_value_signal.emit(text)

    def post_background(self, path: str) -> None:
        self.update_bg.emit(path)

    def post_cg(self, path: str) -> None:
        self.update_cg.emit(path)

    def post_agent_reply_finished(self) -> None:
        try:
            from services.asr.asr_adapter import get_asr_log

            get_asr_log().info("UIUpdateManager: post_agent_reply_finished → agent_reply_finished_signal")
        except Exception:
            pass
        self.agent_reply_finished_signal.emit()

    def post_pause_asr(self) -> None:
        try:
            from services.asr.asr_adapter import get_asr_log

            get_asr_log().info("UIUpdateManager: post_pause_asr → pause_asr_signal")
        except Exception:
            pass
        self.pause_asr_signal.emit()

    # --- 高层：业务组装（原 UIWorker 上的逻辑） ---

    def update_dialog(self, name: str, speech: str, color: str, is_system: bool = True) -> None:
        safe_name = escape(name or "")
        speech_html = _speech_to_html(speech or "")
        safe_color = _safe_css_color(color)
        if is_system:
            formatted = (
                f"<p style='line-height: 135%; letter-spacing: 2px; color:{safe_color};'>"
                f"<b>{safe_name}</b>：</p><div style='line-height: 135%; letter-spacing: 2px; color:{safe_color};'>"
                f"{speech_html}</div>"
            )
        else:
            formatted = (
                f"<p style='line-height: 135%; letter-spacing: 2px;'>"
                f"<b style='color:{safe_color};'>{safe_name}</b>：</p>"
                f"<div style='line-height: 135%; letter-spacing: 2px;'>{speech_html}</div>"
            )
        self.chat_history.append(formatted)
        self.post_dialog(formatted)

    def _sprite_path(self, sprite: Any) -> str:
        if isinstance(sprite, dict):
            return str(sprite.get("path", ""))
        return str(getattr(sprite, "path", "") or "")

    def _sprite_has_static_image(self, sprite: Any) -> bool:
        raw_path = self._sprite_path(sprite).strip()
        return bool(raw_path) and Path(raw_path).expanduser().is_file()

    def _sprite_value(self, sprite: Any, key: str, default: Any = None) -> Any:
        if isinstance(sprite, dict):
            return sprite.get(key, default)
        return getattr(sprite, key, default)

    def _normalize_image_channels(self, cv_image: np.ndarray) -> np.ndarray:
        if cv_image.ndim == 2:
            cv_image = cv2.cvtColor(cv_image, cv2.COLOR_GRAY2RGBA)
        elif cv_image.shape[2] == 3:
            cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
            alpha_channel = np.full((cv_image.shape[0], cv_image.shape[1]), 255, dtype=np.uint8)
            cv_image = cv2.merge([cv_image, alpha_channel])
        elif cv_image.shape[2] == 4:
            cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGRA2RGBA)
        return cv_image

    def _load_rgba_image(self, image_path: Path) -> Optional[np.ndarray]:
        image_path = image_path.expanduser()
        stat = image_path.stat()
        cache_key = str(image_path.resolve())
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        cached = self._sprite_image_cache.get(cache_key)
        if cached and cached[0] == fingerprint:
            self._sprite_image_cache.move_to_end(cache_key)
            return cached[1]

        img_data = np.fromfile(str(image_path), dtype=np.uint8)
        cv_image = cv2.imdecode(img_data, cv2.IMREAD_UNCHANGED)
        if cv_image is None:
            return None
        cv_image = self._normalize_image_channels(cv_image)
        self._sprite_image_cache[cache_key] = (fingerprint, cv_image)
        self._sprite_image_cache.move_to_end(cache_key)
        while len(self._sprite_image_cache) > self._sprite_image_cache_limit:
            self._sprite_image_cache.popitem(last=False)
        return cv_image

    def _frame_interval_ms(self, sprite: Any) -> int:
        fps = self._sprite_value(sprite, "fps", 0) or 0
        try:
            fps_f = float(fps)
        except (TypeError, ValueError):
            fps_f = 0.0
        if fps_f > 0:
            return max(16, int(round(1000 / fps_f)))

        raw = self._sprite_value(sprite, "frame_interval_ms", 120) or 120
        try:
            return max(16, int(raw))
        except (TypeError, ValueError):
            return 120

    def _load_animation_frames(self, sprite: Any) -> List[np.ndarray]:
        frame_paths = self._sprite_value(sprite, "frames", []) or []
        frames: List[np.ndarray] = []
        if frame_paths:
            for raw_path in frame_paths:
                raw = str(raw_path or "").strip()
                path = Path(raw)
                if not raw or not path.expanduser().is_file():
                    print(f"UIUpdateManager: 动画帧不存在: {path}")
                    continue
                frame = self._load_rgba_image(path)
                if frame is not None:
                    frames.append(frame)
            if frames:
                return frames

        spritesheet_path = str(self._sprite_value(sprite, "spritesheet_path", "") or "")
        if not spritesheet_path:
            return []

        sheet_path = Path(spritesheet_path)
        if not sheet_path.expanduser().is_file():
            print(f"UIUpdateManager: spritesheet 不存在: {sheet_path}")
            return []
        sheet = self._load_rgba_image(sheet_path)
        if sheet is None:
            return []

        try:
            frame_w = int(self._sprite_value(sprite, "frame_width", 0) or 0)
            frame_h = int(self._sprite_value(sprite, "frame_height", 0) or 0)
            frame_count = int(self._sprite_value(sprite, "frame_count", 0) or 0)
            row = int(self._sprite_value(sprite, "frame_row", 0) or 0)
            col = int(self._sprite_value(sprite, "frame_col", 0) or 0)
        except (TypeError, ValueError):
            return []
        if frame_w <= 0 or frame_h <= 0 or frame_count <= 0:
            return []

        sheet_h, sheet_w = sheet.shape[:2]
        y = row * frame_h
        if y < 0 or y + frame_h > sheet_h:
            print(f"UIUpdateManager: spritesheet 行超出范围: row={row}, height={sheet_h}")
            return []

        for i in range(frame_count):
            x = (col + i) * frame_w
            if x < 0 or x + frame_w > sheet_w:
                break
            frames.append(np.ascontiguousarray(sheet[y:y + frame_h, x:x + frame_w]))
        return frames

    def _realtime_cache_key(self, prompt: str) -> str:
        api = _config_manager.config.api_config
        parts = [
            prompt,
            str(api.t2i_provider or ""),
            str(api.t2i_api_url or ""),
        ]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]

    def update_sprite(self, character_name: str, sprite_id: int, emotion: str = "", scene: str = "") -> None:
        """
        更新角色立绘。根据配置选择静态模式或实时生成模式。

        Args:
            character_name: 角色名
            sprite_id: 立绘编号（静态模式下使用）
            emotion: 情绪标签（实时模式下用于生成提示词）
            scene: 场景描述（实时模式下用于生成提示词）
        """
        try:
            character_config = get_character_by_name(character_name)
            if character_config is None:
                raise ValueError(f"未找到角色配置: {character_name}")

            # 检查是否启用实时生成
            realtime_enabled = _config_manager.config.system_config.sprite_realtime_enabled

            if realtime_enabled and self.t2i_manager:
                # 实时生成模式
                self._generate_realtime_sprite(character_name, emotion, scene)
            else:
                # 静态模式（原有逻辑）
                if sprite_id < 0 or sprite_id >= len(character_config.sprites):
                    print(f"UIUpdateManager: 立绘编号 {sprite_id} 超出范围 (0-{len(character_config.sprites)-1})")
                    return

                sprite = character_config.sprites[sprite_id]
                frames = self._load_animation_frames(sprite)
                if len(frames) > 1:
                    self.post_sprite_animation_update(
                        frames,
                        character_name,
                        character_config.sprite_scale,
                        self._frame_interval_ms(sprite),
                    )
                    return
                if len(frames) == 1:
                    self.post_sprite_update(frames[0], character_name, character_config.sprite_scale)
                    return

                image_path = Path(self._sprite_path(sprite))
                if not self._sprite_has_static_image(sprite):
                    print(f"UIUpdateManager: 目标状态没有可用图片，保持当前立绘: {image_path}")
                    return
                cv_image = self._load_rgba_image(image_path)
                if cv_image is not None:
                    self.post_sprite_update(cv_image, character_name, character_config.sprite_scale)
                else:
                    print(f"UIUpdateManager: 无法加载图片: {image_path}")
        except Exception as e:
            traceback.print_exc()
            print(f"UIUpdateManager: 加载图片时出错: {e}")

    def _generate_realtime_sprite(self, character_name: str, emotion: str, scene: str) -> None:
        """实时生成立绘（调用生图 API）"""
        try:
            character_config = get_character_by_name(character_name)
            if character_config is None:
                return

            # 构建提示词
            template = _config_manager.config.system_config.sprite_realtime_prompt_template
            if not template:
                # 默认模板
                template = (
                    "{character_name}, {emotion} expression, {scene}, "
                    "anime style, high quality, detailed, masterpiece, "
                    "white background, full body, standing pose"
                )

            prompt = template.format(
                character_name=character_name,
                emotion=emotion if emotion else "neutral",
                scene=scene if scene else "normal"
            )

            # 检查缓存
            cache_dir = Path(_config_manager.config.system_config.sprite_realtime_cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)

            # 缓存需包含引擎与接口信息，避免换服务后误用旧图。
            prompt_hash = self._realtime_cache_key(prompt)
            cache_file = cache_dir / f"{character_name}_{prompt_hash}.png"

            if cache_file.exists():
                # 使用缓存
                cv_image = self._load_rgba_image(cache_file)
            else:
                # 调用生图 API 生成
                print(f"Image API: 正在生成立绘 - {prompt}")
                self.post_busy_bar(f"正在生成 {character_name} 的立绘...", 0.0)

                if not self.t2i_manager:
                    print("Image API: 未配置生图管理器，无法实时生成")
                    self.hide_busy_bar()
                    return

                output_path = str(cache_file)
                result_path = self.t2i_manager.t2i(prompt, file_path=output_path)

                self.hide_busy_bar()

                if not result_path or not Path(result_path).exists():
                    print(f"Image API: 生成失败，路径: {result_path}")
                    return

                cv_image = self._load_rgba_image(Path(result_path))

            if cv_image is not None:
                self.post_sprite_update(cv_image, character_name, character_config.sprite_scale)
            else:
                print("Image API: 无法解码生成的图片")
        except Exception as e:
            traceback.print_exc()
            print(f"Image API: 生成立绘时出错: {e}")
            self.hide_busy_bar()

    def remove_character_sprite(self, character_name: str) -> None:
        self.post_sprite_update(np.empty((0,), dtype=np.uint8), character_name, 1.0)

    def switch_bgm(self, new_bgm_path: str) -> None:
        if not new_bgm_path or not Path(new_bgm_path).exists():
            return
        new_bgm_path = Path(new_bgm_path).as_posix()
        if new_bgm_path == self.current_bgm_path:
            if pygame.mixer.music.get_busy():
                return
            pygame.mixer.music.play(-1)
            print(f"BGM: 重新开始播放：{new_bgm_path}")
            return
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            pygame.mixer.music.load(new_bgm_path)
            volume = _config_manager.config.system_config.music_volumn / 100
            pygame.mixer.music.set_volume(volume)
            pygame.mixer.music.play(-1)
            self.current_bgm_path = new_bgm_path
        except pygame.error as e:
            print(f"BGM: 切换背景音乐失败 ({new_bgm_path}): {e}")
            self.current_bgm_path = None
        except Exception:
            print("切换bgm时发生错误")
            traceback.print_exc()

    def play_sound_effect(self, sound_effect_path: str) -> None:
        if not Path(sound_effect_path).exists():
            print(f"音效文件不存在: {sound_effect_path}")
            return
        try:
            effect_sound = pygame.mixer.Sound(sound_effect_path)
            sound_channel = pygame.mixer.Channel(SOUND_EFFECT_CHANNEL_ID)
            sound_channel.play(effect_sound)
        except Exception as e:
            print(f"播放音效失败: {e}")

    def resolve_effect(self, effect: str, args: Dict[str, Any], after_dialog: bool = False) -> None:
        try:
            match effect:
                case "LEAVE":
                    if after_dialog:
                        self.remove_character_sprite(args.get("character_name"))
                case _:
                    if not after_dialog:
                        path = SOUND_EFFECTS_PATH.get(effect.upper(), None)
                        if path:
                            self.play_sound_effect(path)
        except Exception as e:
            print("播放特效失败", e)


def connect_to_desktop_window(ui: UIUpdateManager, window: Any) -> None:
    """将 worker 侧 UI 更新信号全部接到主窗口上的对应槽（原 main_sprite 中分散的连接）。"""
    ui.update_sprite_signal.connect(window.update_image)
    ui.update_sprite_animation_signal.connect(window.update_sprite_animation)
    ui.update_dialog_signal.connect(window.setDisplayWords)
    ui.update_notification_signal.connect(window.setNotification)
    ui.update_busy_bar_signal.connect(window.setBusyBar)
    ui.update_option_signal.connect(window.setOptions)
    ui.update_value_signal.connect(window.update_numeric_info)
    ui.update_bg.connect(window.setBackgroundImage)
    ui.update_cg.connect(window.show_cg_image)
    # 与主窗口均为 PySide6 Signal 时可直连中继。
    ui.agent_reply_finished_signal.connect(window.agent_reply_finished)
    ui.pause_asr_signal.connect(window.pause_asr_signal)
