from __future__ import annotations

import sys
from PIL.ImageChops import screen
import numpy as np
import threading
import pygame
import yaml
import time
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QRect,
    QTimer,
    Qt,
    QThread,
    Signal,
    QObject,
    QSize,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    QPoint,
)
from PySide6.QtGui import QAction, QCursor, QFont, QFontMetrics, QImage, QMouseEvent, QPixmap, QTextDocument
from PySide6.QtWidgets import QGraphicsColorizeEffect, QGridLayout, QSlider, QFileDialog, QMessageBox
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QTextBrowser,
    QWidget,
    QVBoxLayout,
    QMenu,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QButtonGroup,
    QRadioButton,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QSizePolicy,
)
import os
from services.i18n import tr


# 交叉渐变立绘组件
# 交叉渐变立绘组件
class CrossFadeSprite(QWidget):
    def __init__(self, original_width, original_height, parent=None):
        super().__init__(parent)
        # 外部尺寸只作为安全上限参考；立绘显示尺寸由图片自身像素和角色 scale 决定。
        self.original_width = original_width
        self.original_height = original_height
        self.setMinimumSize(1, 1)
        self.setMaximumSize(16777215, 16777215)
        self._last_source_image: np.ndarray | None = None
        self._last_character_rate = None
        self._animation_frames: list[np.ndarray] = []
        self._animation_index = 0
        self._animation_rate = None
        self._animation_interval_ms = 120
        self._visible_bounds = QRect()
        self.current_character: str | None = None  # 当前显示的角色名
        
        # 布局，确保两个 QLabel 重叠
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0) # 确保没有间距 
        
        # --- 两个重叠的 QLabel ---
        
        # 1. '旧' 立绘标签 - 用于淡出
        self.label_old = QLabel(self)
        self.label_old.setAlignment(
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter
        )
        self.label_old.setScaledContents(False) 
        self.old_opacity_effect = QGraphicsOpacityEffect(self.label_old)
        self.old_opacity_effect.setOpacity(1.0)
        self.label_old.setGraphicsEffect(self.old_opacity_effect)
        
        # 2. '新' 立绘标签 - 用于淡入
        self.label_new = QLabel(self)
        self.label_new.setAlignment(
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter
        )
        self.label_new.setScaledContents(False)
        self.new_opacity_effect = QGraphicsOpacityEffect(self.label_new)
        self.new_opacity_effect.setOpacity(0.0)
        self.label_new.setGraphicsEffect(self.new_opacity_effect)
        
        # 将两个 QLabel 都添加到布局中（它们会自动重叠）
        layout.addWidget(self.label_old, 0, 0)
        layout.addWidget(self.label_new, 0, 0)
        
        # 动画和状态
        self.fade_duration = 300  # 渐变持续时间 (毫秒)
        self.is_animating = False
        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self._advance_frame)

    def _get_scaled_pixmap(self, image: np.ndarray, character_rate=None) -> QPixmap:
        """
        将 numpy 图像转换为缩放后的 QPixmap。
        立绘不再按窗口高度放大；默认使用图片原始像素 * character_rate。
        只有在图片超出屏幕可用区域时，才等比压缩到安全范围内。
        """
        # 1. 转换为 QImage/QPixmap
        height, width, channel = image.shape
        # bytes_per_line = 4 * width # 假设输入图像是 RGBA8888 格式
        # QImage 构造函数可以直接处理 buffer，但如果使用 fromBuffer，
        # 需要确保数据类型和步长正确。此处我们沿用您提供的 QImage(data, w, h, bpl, format) 构造
        bytes_per_line = width * channel  # 实际的字节数，4*width 仅适用于 RGBA8888
        
        # 确保格式匹配：4 通道 (RGBA) 使用 QImage.Format.Format_RGBA8888
        qimg = QImage(
            image.data, width, height, bytes_per_line, QImage.Format.Format_RGBA8888
        )
        pixmap = QPixmap.fromImage(qimg)
        
        img_width = pixmap.width()
        img_height = pixmap.height()
        if img_width <= 0 or img_height <= 0:
            return QPixmap()

        try:
            rate = float(1 if character_rate is None else character_rate)
        except (TypeError, ValueError):
            rate = 1.0
        rate = max(0.05, rate)

        target_w = img_width * rate
        target_h = img_height * rate

        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            max_width = max(1.0, avail.width() * 0.82)
            max_height = max(1.0, avail.height() * 0.76)
        else:
            max_width = max(1.0, float(self.original_width))
            max_height = max(1.0, float(self.original_height))

        clamp = min(1.0, max_width / target_w, max_height / target_h)
        final_w = max(1, int(round(target_w * clamp)))
        final_h = max(1, int(round(target_h * clamp)))

        scaled_pixmap = pixmap.scaled(
            final_w,
            final_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        return scaled_pixmap

    def _resize_to_pixmap(self, pixmap: QPixmap) -> tuple[int, int]:
        w = max(1, int(pixmap.width()))
        h = max(1, int(pixmap.height()))
        self.resize(w, h)
        return w, h

    def _update_visible_bounds(self, image: np.ndarray, pixmap: QPixmap) -> None:
        if image.ndim < 3 or image.shape[2] < 4 or pixmap.isNull():
            self._visible_bounds = QRect(0, 0, pixmap.width(), pixmap.height())
            return
        alpha = image[:, :, 3]
        ys, xs = np.where(alpha > 8)
        if xs.size == 0 or ys.size == 0:
            self._visible_bounds = QRect(0, 0, pixmap.width(), pixmap.height())
            return
        src_h, src_w = image.shape[:2]
        scale_x = pixmap.width() / max(1, src_w)
        scale_y = pixmap.height() / max(1, src_h)
        x0 = int(xs.min() * scale_x)
        y0 = int(ys.min() * scale_y)
        x1 = int((xs.max() + 1) * scale_x)
        y1 = int((ys.max() + 1) * scale_y)
        self._visible_bounds = QRect(
            max(0, x0),
            max(0, y0),
            max(1, x1 - x0),
            max(1, y1 - y0),
        )

    def visible_bounds(self) -> QRect:
        return QRect(self._visible_bounds)

    def _stop_frame_animation(self):
        self.frame_timer.stop()
        self._animation_frames = []
        self._animation_index = 0
        self._animation_rate = None

    def _stop_transition_animation(self) -> None:
        group = getattr(self, "parallel_group", None)
        if group is not None:
            group.stop()
        self.is_animating = False

    def _set_pixmap_without_fade(self, image: np.ndarray, character_rate=None):
        scaled_pixmap = self._get_scaled_pixmap(image, character_rate)
        if scaled_pixmap.isNull():
            return 0, 0
        self._update_visible_bounds(image, scaled_pixmap)
        self.label_old.setPixmap(scaled_pixmap)
        self.label_new.clear()
        self.new_opacity_effect.setOpacity(0.0)
        self.old_opacity_effect.setOpacity(1.0)
        return self._resize_to_pixmap(scaled_pixmap)

    def _advance_frame(self):
        if not self._animation_frames:
            self.frame_timer.stop()
            return
        self._animation_index = (self._animation_index + 1) % len(self._animation_frames)
        self._set_pixmap_without_fade(
            self._animation_frames[self._animation_index],
            self._animation_rate,
        )

    def setSprite(self, image: np.ndarray, character_rate=None):
        """
        加载新立绘并开始交叉渐变动画。
        """
        self._stop_frame_animation()
        self._stop_transition_animation()
        # if self.is_animating:
        #     print("正在进行动画，忽略本次切换。")
        #     return 0, 0
            
        scaled_pixmap = self._get_scaled_pixmap(image, character_rate)
        if scaled_pixmap.isNull():
            print("错误：无法生成有效的 QPixmap。")
            return 0, 0
        self._update_visible_bounds(image, scaled_pixmap)

        if self.label_old.pixmap() is None or self.label_old.pixmap().isNull():
            self.label_old.setPixmap(scaled_pixmap)
            self.label_new.clear()
            self.new_opacity_effect.setOpacity(0.0)
            self.old_opacity_effect.setOpacity(1.0)
            self.is_animating = False
            if image.shape[0] >= 2 and image.shape[1] >= 2:
                self._last_source_image = np.ascontiguousarray(image)
                self._last_character_rate = character_rate
            return self._resize_to_pixmap(scaled_pixmap)
            
        # 1. 将新立绘设置到 '新' 标签上
        self.label_new.setPixmap(scaled_pixmap)
        self.is_animating = True
        
        # --- 创建动画 ---
        
        # 动画 1: 旧立绘淡出 (1.0 -> 0.0)
        anim_fade_out = QPropertyAnimation(self.old_opacity_effect, b"opacity")
        anim_fade_out.setDuration(self.fade_duration)
        anim_fade_out.setStartValue(1.0)
        anim_fade_out.setEndValue(0.0)
        
        # 动画 2: 新立绘淡入 (0.0 -> 1.0)
        anim_fade_in = QPropertyAnimation(self.new_opacity_effect, b"opacity")
        anim_fade_in.setDuration(self.fade_duration)
        anim_fade_in.setStartValue(0.0)
        anim_fade_in.setEndValue(1.0)

        # QSequentialAnimationGroup 用于同时播放两个动画
        self.parallel_group = QSequentialAnimationGroup(self)
        self.parallel_group.addAnimation(anim_fade_out)
        self.parallel_group.addAnimation(anim_fade_in)
        
        self.parallel_group.finished.connect(self._animationFinished)
        
        # 开始动画
        self.parallel_group.start()
        if image.shape[0] >= 2 and image.shape[1] >= 2:
            self._last_source_image = np.ascontiguousarray(image)
            self._last_character_rate = character_rate
        return self._resize_to_pixmap(scaled_pixmap)

    def setAnimation(self, frames: list[np.ndarray], frame_interval_ms: int = 120, character_rate=None):
        """
        加载多帧立绘动画。动画状态直接切到第一帧，不走单图的顺序淡出/淡入。
        """
        valid_frames = [
            np.ascontiguousarray(frame)
            for frame in (frames or [])
            if isinstance(frame, np.ndarray) and frame.size > 0
        ]
        if not valid_frames:
            return 0, 0

        self._stop_frame_animation()
        self._stop_transition_animation()
        w, h = self._set_pixmap_without_fade(valid_frames[0], character_rate)
        if w == 0 or h == 0:
            return 0, 0

        self._animation_frames = valid_frames
        self._animation_index = 0
        self._animation_rate = character_rate
        try:
            self._animation_interval_ms = max(16, int(frame_interval_ms))
        except (TypeError, ValueError):
            self._animation_interval_ms = 120
        if len(valid_frames) > 1:
            self.frame_timer.start(self._animation_interval_ms)
        return w, h

    def _animationFinished(self):
        """动画结束后的清理工作"""
        # 1. 将 '新' 标签的 Pixmap 转移到 '旧' 标签
        current_pixmap = self.label_new.pixmap()
        if current_pixmap:
            self.label_old.setPixmap(current_pixmap.copy()) # 使用 copy 确保数据独立性
        
        # 2. 重置 '旧' 标签的透明度为 1.0 
        self.old_opacity_effect.setOpacity(1.0)
        
        # 3. 清空 '新' 标签的 Pixmap 并重置透明度为 0.0
        self.label_new.clear()
        self.new_opacity_effect.setOpacity(0.0)
        
        self.is_animating = False

    def setInitialSprite(self, image: np.ndarray, character_rate=None):
        """用于程序启动时第一次设置立绘，不带动画。"""
        self._stop_frame_animation()
        scaled_pixmap = self._get_scaled_pixmap(image, character_rate)
        if scaled_pixmap and not scaled_pixmap.isNull():
            self._update_visible_bounds(image, scaled_pixmap)
            self.label_old.setPixmap(scaled_pixmap)
            if image.shape[0] >= 2 and image.shape[1] >= 2:
                self._last_source_image = np.ascontiguousarray(image)
                self._last_character_rate = character_rate
            self._resize_to_pixmap(scaled_pixmap)

    def apply_panel_resize(self, panel_w: int, panel_h: int) -> None:
        """面板尺寸变化时更新缩放参照与已显示立绘（无边框窗口拖拽缩放）。"""
        self.original_width = panel_w
        self.original_height = panel_h
        self.setMaximumSize(16777215, 16777215)
        if self._last_source_image is None:
            return
        pm = self._get_scaled_pixmap(self._last_source_image, self._last_character_rate)
        if pm.isNull():
            return
        self._update_visible_bounds(self._last_source_image, pm)
        self.label_old.setPixmap(pm)
        self.label_new.clear()
        self.new_opacity_effect.setOpacity(0.0)
        self.old_opacity_effect.setOpacity(1.0)
        pg = getattr(self, "parallel_group", None)
        if pg is not None:
            pg.stop()
        self.is_animating = False
        self._resize_to_pixmap(pm)
        if self._animation_frames:
            self.frame_timer.start(self._animation_interval_ms)

    def apply_rate(self, character_rate=None) -> None:
        """用户拖拽缩放时，以当前图片/动画帧重新计算显示尺寸。"""
        if self._last_source_image is None:
            return
        self._last_character_rate = character_rate
        pm = self._get_scaled_pixmap(self._last_source_image, character_rate)
        if pm.isNull():
            return
        self._update_visible_bounds(self._last_source_image, pm)
        self.label_old.setPixmap(pm)
        self.label_new.clear()
        self.new_opacity_effect.setOpacity(0.0)
        self.old_opacity_effect.setOpacity(1.0)
        pg = getattr(self, "parallel_group", None)
        if pg is not None:
            pg.stop()
        self.is_animating = False
        self._resize_to_pixmap(pm)

    def fadeOut(self):
        """使立绘淡出（隐藏）"""
        self._stop_frame_animation()
        self._last_source_image = None
        self._last_character_rate = None
        self.setSprite(np.zeros((1,1,4), dtype=np.uint8), 1.0)  # 传入空图像实现淡出效果

    def clear(self):
        """清除立绘"""
        self._stop_frame_animation()
        self._last_source_image = None
        self._last_character_rate = None
        self._visible_bounds = QRect()
        self.label_old.clear()
        self.label_new.clear()
        self.current_character = None

class SpritePanel(QWidget):
    """
    立绘显示面板，使用绝对定位实现立绘重叠和居中错位。
    立绘尺寸由图片自身像素和角色 scale 决定，面板只负责定位。
    """
    sprite_bounds_changed = Signal()

    def __init__(self, panel_width: int, panel_height: int, max_slots_num: int = 3, parent=None):
        super().__init__(parent)
        self.panel_width = panel_width
        self.panel_height = panel_height
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.resize(panel_width, panel_height)
        self.max_slots_num = max_slots_num
        
        # 尺寸参考 (用于 CrossFadeSprite 内部缩放高度)
        self.sprite_width_ref = panel_width  # 宽度只做参考，不限制
        self.sprite_height_ref = panel_height
        
        # --- 布局 (使用 QHBoxLayout 仅实现居中) ---
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 关键：center_widget 是立绘的父容器，用于绝对定位
        self.center_widget = QWidget(self)
        # center_widget 的尺寸应与 SpritePanel 相同，以便正确计算绝对坐标
        self.center_widget.setFixedSize(panel_width, panel_height) 
        
        # 将 center_widget 居中
        self.main_layout.addStretch(1)
        self.main_layout.addWidget(self.center_widget)
        self.main_layout.addStretch(1)

        # --- 槽位管理 ---
        self.sprite_slots = []
        self.sprite_lru = {}  # {character_id: slot_index}
        self._sprite_base_rates: dict[str, float] = {}
        self._reserved_bottom = 0
        
        # 计算水平偏移量 (用于错开立绘)
        # 将面板宽度分成 N+1 份，中心点落在第 1, 2, ..., N 份的交界处
        self.horizontal_offset_unit = self.panel_width / self.max_slots_num
        
        # 初始化槽位
        for i in range(self.max_slots_num):
            # 将 center_widget 作为父对象
            sprite = CrossFadeSprite(self.sprite_width_ref, self.sprite_height_ref, self.center_widget)
            
            # 初始尺寸：设为 0，等待 set_sprite 时调整
            sprite.setGeometry(0, 0, 0, 0)
            
            self.sprite_slots.append(sprite)
            sprite.hide()

    def active_sprite_size(self) -> QSize:
        active = self._active_scale_sprite()
        if active is None:
            return QSize(0, 0)
        _char_id, sprite = active
        return QSize(max(0, sprite.width()), max(0, sprite.height()))

    def active_sprite_geometry(self) -> QRect:
        active = self._active_scale_sprite()
        if active is None:
            return QRect()
        _char_id, sprite = active
        return sprite.geometry()

    def active_sprite_visible_geometry(self) -> QRect:
        active = self._active_scale_sprite()
        if active is None:
            return QRect()
        _char_id, sprite = active
        bounds = sprite.visible_bounds()
        if not bounds.isValid() or bounds.height() <= 0:
            return sprite.geometry()
        return QRect(
            sprite.x() + bounds.x(),
            sprite.y() + bounds.y(),
            bounds.width(),
            bounds.height(),
        )

    def set_reserved_bottom(self, px: int) -> None:
        """底部输入栏占用空间，立绘底边应停在它上方。"""
        try:
            reserved = max(0, int(px))
        except (TypeError, ValueError):
            reserved = 0
        if reserved == self._reserved_bottom:
            return
        self._reserved_bottom = reserved
        self._reposition_sprites()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        if w < 1 or h < 1:
            return
        self.panel_width = w
        self.panel_height = h
        self.center_widget.setFixedSize(w, h)
        self.horizontal_offset_unit = w / self.max_slots_num if self.max_slots_num else 1.0
        self.sprite_width_ref = w
        self.sprite_height_ref = h
        for sprite in self.sprite_slots:
            sprite.apply_panel_resize(w, h)
        self._reposition_sprites()

    def _get_or_create_slot(self, character_id: str) -> CrossFadeSprite | None:
        """
        获取或创建立绘槽位。
        """
        if character_id in self.sprite_lru:
            # 命中，更新 LRU
            slot_index = self.sprite_lru.pop(character_id)
            self.sprite_lru[character_id] = slot_index
            return self.sprite_slots[slot_index]

        # 未命中，分配新槽位
        if len(self.sprite_lru) < self.max_slots_num:
            # 还有空闲槽位，从最小索引开始找
            used_indices = set(self.sprite_lru.values())
            for i in range(self.max_slots_num):
                if i not in used_indices:
                    slot_index = i
                    break
        else:
            # LRU淘汰
            oldest_id, slot_index = next(iter(self.sprite_lru.items()))
            self.sprite_lru.pop(oldest_id)
            self.sprite_slots[slot_index].clear() # 清理被淘汰槽位

        self.sprite_lru[character_id] = slot_index
        return self.sprite_slots[slot_index]
    def _reposition_sprites(self):
        """
        重新计算并定位所有可见立绘，确保立绘组在 SpritePanel 中居中。
        """
        active_slots = []
        for char_id, slot_index in self.sprite_lru.items():
            sprite = self.sprite_slots[slot_index]
            # 获取当前立绘的实际宽度
            w = sprite.width()
            if w > 0:
                active_slots.append({'sprite': sprite, 'index': slot_index, 'w': w})

        if not active_slots:
            return

        # 1. 估算立绘组的最小/最大 X 坐标 (基于目标中心点)
        min_slot_index = min(s['index'] for s in active_slots)
        max_slot_index = max(s['index'] for s in active_slots)
        
        # 目标中心点的 X 坐标范围：从 (min_slot_index + 1) 到 (max_slot_index + 1) * offset_unit
        
        # 计算最左侧立绘的左边缘 X_min
        # X_min = 目标中心点 X[min_slot] - 0.5 * w[min_slot]
        target_center_min = self.horizontal_offset_unit * (min_slot_index + 1)
        X_min = target_center_min - (active_slots[0]['w'] / 2) # 假设第一个就是 min_slot 的立绘

        # 计算最右侧立绘的右边缘 X_max
        # X_max = 目标中心点 X[max_slot] + 0.5 * w[max_slot]
        target_center_max = self.horizontal_offset_unit * (max_slot_index + 1)
        X_max = target_center_max + (active_slots[-1]['w'] / 2) # 假设最后一个就是 max_slot 的立绘
       
        group_width = target_center_max - target_center_min + (active_slots[-1]['w'] / 2) + (active_slots[0]['w'] / 2) # 估算组宽度
        
        # 整体居中补偿 (将立绘组中心对齐到面板中心)
        # compensation = (self.panel_width / 2) - (target_center_min + target_center_max) / 2
        compensation = (self.panel_width / 2) - ((target_center_min + target_center_max) / 2) # 居中补偿
        
        # 重新定位所有立绘
        for item in active_slots:
            w = item['w']
            sprite = item['sprite']
            slot_index = item['index']
            
            # 目标中心点 X 坐标
            target_center_x = self.horizontal_offset_unit * (slot_index + 1) 
            
            # 实际左上角 X 坐标 (居中对齐) + 整体补偿
            x_pos = target_center_x - (w / 2) + compensation
            
            # Y 坐标 (底部对齐)
            y_pos = self.panel_height - self._reserved_bottom - sprite.height()
            y_pos = max(0, y_pos)

            sprite.move(int(x_pos), int(y_pos))

    def _active_scale_sprite(self) -> tuple[str, CrossFadeSprite] | None:
        if not self.sprite_lru:
            return None
        char_id = next(reversed(self.sprite_lru.keys()))
        slot_index = self.sprite_lru.get(char_id)
        if slot_index is None:
            return None
        sprite = self.sprite_slots[slot_index]
        if sprite.isHidden() or sprite.width() <= 0 or sprite.height() <= 0:
            return None
        return char_id, sprite

    def switch_sprite(self, character_id: str, image_data: np.ndarray, character_rate=None):
        """
        设置立绘并显示，动态调整其位置和尺寸。
        """
        sprite = self._get_or_create_slot(character_id)
        if sprite is None: return

        # 1. 设置立绘并获取实际的缩放尺寸
        w, h = sprite.setSprite(image_data, character_rate)
        self._sprite_base_rates[character_id] = float(character_rate or 1.0)

        if w == 0 or h == 0: return

        # 2. 重新计算立绘位置 (居中对齐到槽位中心点)
        slot_index = self.sprite_lru[character_id]
        
        # 目标中心点 X 坐标 (在 center_widget 内的绝对坐标)
        target_center_x = self.horizontal_offset_unit * (slot_index)

        # 实际左上角 X 坐标 (实现立绘在其槽位中心居中)
        x_pos = target_center_x - (w / 2) 
        
        # Y 坐标 (底部对齐)
        y_pos = 0
        
        # 3. 应用新的位置和尺寸
        sprite.setGeometry(int(x_pos), int(y_pos), int(w), int(h))
        
        self._reposition_sprites()
        # 4. 显示和层级
        sprite.show()
        sprite.raise_() # 确保新登场或切换的立绘在最前面
        self.sprite_bounds_changed.emit()

    def switch_animation(
        self,
        character_id: str,
        frames: list[np.ndarray],
        character_rate=None,
        frame_interval_ms: int = 120,
    ):
        """
        设置多帧立绘动画并显示。每个情绪仍占用一个 sprite 编号，但编号背后可以是帧序列。
        """
        sprite = self._get_or_create_slot(character_id)
        if sprite is None:
            return

        w, h = sprite.setAnimation(frames, frame_interval_ms, character_rate)
        self._sprite_base_rates[character_id] = float(character_rate or 1.0)
        if w == 0 or h == 0:
            return

        slot_index = self.sprite_lru[character_id]
        target_center_x = self.horizontal_offset_unit * (slot_index)
        x_pos = target_center_x - (w / 2)
        y_pos = 0
        sprite.setGeometry(int(x_pos), int(y_pos), int(w), int(h))

        self._reposition_sprites()
        sprite.show()
        sprite.raise_()
        self.sprite_bounds_changed.emit()

    def remove(self, character_id: str):
        """
        移除指定角色的立绘。
        """
        if character_id in self.sprite_lru:
            slot_index = self.sprite_lru.pop(character_id)
            sprite = self.sprite_slots[slot_index]
            sprite.fadeOut()
            sprite.clear()
            sprite.hide()
            self._reposition_sprites()
            self._sprite_base_rates.pop(character_id, None)
            self.sprite_bounds_changed.emit()
            
    def remove_all(self):
        """
        移除所有立绘。
        """
        for char_id in list(self.sprite_lru.keys()):
            self.remove(char_id)

    def remove_except(self, character_id: str):
        """
        单角色运行模式下，移除目标角色以外的所有立绘。
        """
        keep = str(character_id or "")
        for char_id in list(self.sprite_lru.keys()):
            if char_id != keep:
                self.remove(char_id)

    def darken_all(self, exclude_character_id: str | None = None):
        """
        使所有非当前说话者的立绘变暗。
        """
        for char_id, slot_index in self.sprite_lru.items():
            sprite = self.sprite_slots[slot_index]
            if char_id == exclude_character_id:
                # sprite.lighten()
                sprite.raise_() # 确保说话者在最前面
            # else:
                # sprite.darken()

    def clear_all(self):
        """
        清除所有立绘。
        """
        for sprite in self.sprite_slots:
            sprite.clear()
        self.sprite_lru.clear()
        self._sprite_base_rates.clear()
        self.sprite_bounds_changed.emit()

class FontSizeDialog(QDialog):
    """用于设置字体大小的对话框"""
    def __init__(self, current_base_size, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("desktop.settings_dialog.font_title"))
        self.setModal(True)
        self.current_base_size = current_base_size
        self.new_base_size = current_base_size

        self.setStyleSheet("""
            QDialog {
                background-color: rgba(0, 0, 0, 200);
                border-radius: 10px;
                color: white;
            }
            QLabel {
                color: white;
                font-size: 16px;
                padding: 5px;
            }
            QSlider::groove:horizontal {
                height: 8px;
                background: #505050;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #4CAF50;
                border: 1px solid #ddd;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QPushButton {
                background-color: rgba(76, 175, 80, 200);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(76, 175, 80, 255);
            }
        """)

        self.init_ui()
        self.adjustSize()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # 标签
        info_label = QLabel(tr("desktop.settings_dialog.font_hint"))
        layout.addWidget(info_label)

        # 滑块
        self.slider = QSlider(Qt.Orientation.Horizontal)
        # 假设最小基础字体为10px，最大为60px
        self.slider.setRange(10, 60) 
        # 初始值是当前的基础字体大小
        self.slider.setValue(self.current_base_size) 
        self.slider.setSingleStep(2)
        self.slider.valueChanged.connect(self.update_label)
        layout.addWidget(self.slider)

        # 当前值显示标签
        self.value_label = QLabel(tr("desktop.settings_dialog.font_current", value=self.current_base_size))
        layout.addWidget(self.value_label)

        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.confirm_button = QPushButton(tr("desktop.settings_dialog.ok"))
        self.confirm_button.clicked.connect(self.accept)
        button_layout.addWidget(self.confirm_button)

        self.cancel_button = QPushButton(tr("desktop.settings_dialog.cancel"))
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(200, 50, 50, 200);
            }
            QPushButton:hover {
                background-color: rgba(200, 50, 50, 255);
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def update_label(self, value):
        self.new_base_size = value
        self.value_label.setText(tr("desktop.settings_dialog.font_current", value=value))

    def get_new_font_size(self):
        return self.new_base_size

class LanguageDialog(QDialog):
    def __init__(self, parent=None, *, mode: str = "voice", current_language: str = ""):
        super().__init__(parent)
        self._mode = mode
        self._current_language = str(current_language or "").strip()
        self.setWindowTitle(
            tr("desktop.settings_dialog.language_title_ui")
            if mode == "ui"
            else tr("desktop.settings_dialog.language_title_voice")
        )
        self.setModal(True)
        
        # 设置半透明黑色背景
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(0, 0, 0, 200);
                border-radius: 10px;
                color: white;
            }
            QRadioButton {
                color: white;
                padding: 8px;
                font-size: 14px;
            }
            QRadioButton::indicator {
                width: 20px;
                height: 20px;
                border-radius: 10px;
                border: 2px solid white;
            }
            QRadioButton::indicator:checked {
                background-color: #4CAF50;
                border: 2px solid white;
            }
            QPushButton {
                background-color: rgba(76, 175, 80, 200);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(76, 175, 80, 255);
            }
            QPushButton:pressed {
                background-color: rgba(62, 142, 65, 255);
            }
        """)
        
        self.init_ui()
        self.adjustSize()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 语言选项
        self.language_group = QButtonGroup(self)

        if self._mode == "ui":
            options = [
                (0, "zh_CN", "中文"),
                (1, "en", "English"),
                (2, "ja", "日本語"),
                (3, "ko", "한국어"),
            ]
            default_code = "zh_CN"
        else:
            options = [
                (0, "en", "English"),
                (1, "zh", "中文"),
                (2, "ja", "日本語"),
                (3, "yue", "粵語"),
            ]
            default_code = "en"

        self._language_codes: dict[int, str] = {}
        checked_id = 0
        for idx, code, label in options:
            radio = QRadioButton(label)
            self.language_group.addButton(radio, idx)
            layout.addWidget(radio)
            self._language_codes[idx] = code
            if code == (self._current_language or default_code):
                checked_id = idx
        button = self.language_group.button(checked_id)
        if button is not None:
            button.setChecked(True)
        
        # 确认按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.confirm_button = QPushButton(tr("desktop.settings_dialog.ok"))
        self.confirm_button.clicked.connect(self.accept)
        button_layout.addWidget(self.confirm_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        
    def get_selected_language(self):
        selected_id = self.language_group.checkedId()
        return self._language_codes.get(selected_id, "zh_CN" if self._mode == "ui" else "en")

# 消息历史对话框
class MessageDialog(QDialog):
    def __init__(self, messages, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("desktop.settings_dialog.history_title"))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.messages = list(messages)
        self.selected_revert_user_index = None

        self.setModal(True)
        self.resize(800, 600)
        
        # 设置半透明黑背景
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(0, 0, 0, 200);
                color: white;
                border-radius: 10px;
            }
            QListWidget {
                background-color: rgba(255, 255, 255, 30);
                alternate-background-color: rgba(255, 255, 255, 50);
                color: white;
                border: none;
                border-radius: 5px;
            }
            QListWidget::item:selected {
                background-color: rgba(255, 255, 255, 100);
            }
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)  # 添加边距
        
        # 消息列表
        self.message_list = QListWidget()
        self.message_list.setAlternatingRowColors(True)
        
        # 添加消息到列表
        user_counter = 0
        for idx, msg in enumerate(self.messages):
            user_index = None
            if self.is_user_message(msg):
                user_index = user_counter
                user_counter += 1
            item_widget = self.create_message_widget(msg, idx, user_index)
            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            self.message_list.addItem(list_item)
            self.message_list.setItemWidget(list_item, item_widget)
        
        layout.addWidget(self.message_list)
        self.setLayout(layout)
    
    def create_message_widget(self, message, index, user_index=None):
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)

        message_label = QLabel()
        message_label.setMargin(10)
        message_label.setWordWrap(True)
        message_label.setTextFormat(Qt.TextFormat.RichText)

        # 设置样式 - 调整为深色主题
        message_label.setStyleSheet("""
            QLabel {
                background-color: rgba(60, 60, 60, 180);
                color: white;
                font-size: 28px;
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                border-radius: 8px;
                padding: 10px;
            }
        """)
        message_label.setText(message)

        container_layout.addWidget(message_label)
        if self.is_user_message(message) and user_index is not None:
            actions_layout = QHBoxLayout()
            actions_layout.setContentsMargins(0, 4, 0, 6)
            actions_layout.addStretch()
            revert_btn = QPushButton(tr("desktop.settings_dialog.history_revert"))
            revert_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(60, 60, 60, 180);
                    color: white;
                    border: 1px solid rgba(255, 255, 255, 60);
                    padding: 8px 16px;
                    border-radius: 8px;
                    font-size: 16px;
                    font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                }
                QPushButton:hover {
                    background-color: rgba(80, 80, 80, 200);
                }
            """)
            revert_btn.clicked.connect(lambda _, uidx=user_index: self.select_revert_user_index(uidx))
            actions_layout.addWidget(revert_btn)
            container_layout.addLayout(actions_layout)

        container.adjustSize()
        return container

    def is_user_message(self, message) -> bool:
        if not isinstance(message, str):
            return False
        return "你</b>" in message or "你</b>：" in message or "你</b>:" in message

    def select_revert_user_index(self, user_index: int):
        reply = QMessageBox.question(
            None,
            tr("desktop.settings_dialog.history_revert_title"),
            tr("desktop.settings_dialog.history_revert_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.selected_revert_user_index = user_index
            self.accept()

class ClickableLabel(QLabel):
    """可点击的标签"""
    clicked = Signal()
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            # 播放短音效使用 pygame.mixer.Sound，而不是 pygame.mixer.music
            self.click_sound = pygame.mixer.Sound('./assets/system/sound/switch.ogg')
        except Exception as e:
            print(f"Error loading sound effect: {e}")
            self.click_sound = None

    def play_click_sound(self):
        """播放点击音效"""
        if self.click_sound:
            # 使用 .play() 播放音效
            self.click_sound.play()

    def mousePressEvent(self, event):
        self.clicked.emit()
        self.play_click_sound()

class TypingLabel(QTextBrowser):
    clicked = Signal()
    typingFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.click_sound = pygame.mixer.Sound('./assets/system/sound/switch.ogg')
        except Exception as e:
            print(f"Error loading sound effect: {e}")
            self.click_sound = None
        self.setOpenExternalLinks(True)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setReadOnly(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.document().setDocumentMargin(0)
        
        # 打字机相关属性
        self._full_text = ""      # 要完整显示的文本
        self._final_html_text = ""
        self._current_char_index = 0 # 当前显示到第几个字符
        self._is_typing = False
        
        # QTimer 用于驱动逐字显示
        self.typing_timer = QTimer(self)
        self.typing_timer.timeout.connect(self._type_next_character)
        self.typing_delay = 50 # 字符之间的毫秒间隔 (可调整)
        
        # 连接跳过按钮到打字机逻辑
        self.clicked.connect(self.skip_typing)

    def play_click_sound(self):
        if self.click_sound:
            self.click_sound.play()

    def setText(self, text: str) -> None:
        self.setHtml(text or "")
        self._scroll_to_bottom()

    def text(self) -> str:
        return self.toHtml()

    def setTextFormat(self, _format) -> None:
        return None

    def setPixmap(self, pixmap) -> None:
        return None

    def setWordWrap(self, enabled: bool) -> None:
        mode = QTextBrowser.LineWrapMode.WidgetWidth if enabled else QTextBrowser.LineWrapMode.NoWrap
        self.setLineWrapMode(mode)

    def adjustSize(self) -> None:
        return None

    def _scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _plain_text_from_html(self, text: str) -> str:
        if not text:
            return ""
        doc = QTextDocument()
        doc.setHtml(text)
        plain = doc.toPlainText()
        return plain if plain.strip() else text

    # ----------------------------------------------------------------------
    # 实现打字机效果
    # ----------------------------------------------------------------------

    def setDisplayWords(self, text: str):
        """
        开始逐字显示文本。
        """
        import time as _time, re
        # _perf = logging.getLogger("here.perf")
        _t0 = _time.perf_counter()
        if not text:
            self.hide()
            return

        # 1. 初始化打字状态
        if self._is_typing:
            self.typing_timer.stop() # 如果正在打字，先停止

        self._final_html_text = text
        rich_text = bool(re.search(r"</?(?:p|div|table|ul|ol|li|h[1-6]|blockquote|pre|code|span|strong|em|br)[\s>/]", text, re.I))
        display_text = self._plain_text_from_html(text) if rich_text else text
        self._full_text = display_text

        # Find where visible text starts: after Chinese colon, or after <p> tag opening
        start = display_text.find('：')
        if start >= 0:
            start += 1  # skip the Chinese colon
        else:
            m = re.search(r'<p[^>]*>', display_text)
            if m:
                start = m.end()  # skip <p ...>
            else:
                start = 0
        self._current_char_index = start
        self._is_typing = True

        self.setText(display_text[:self._current_char_index])
        # If starting from 0, show first char immediately
        if start == 0 and len(display_text) > 0:
            self._current_char_index = 1
            self.setText(display_text[:1])

        # 5. 启动打字机
        self.typing_timer.start(self.typing_delay)
        print("[perf]","TypingLabel.setDisplayWords done | start=%d len=%d | %.1fms",
                    start, len(text), (_time.perf_counter() - _t0) * 1000)


    def _type_next_character(self):
        """
        QTimer 触发时调用的槽函数，显示下一个字符。
        """
        if self._current_char_index < len(self._full_text):
            # 获取当前已显示的文本
            current_text = self._full_text[:self._current_char_index + 1]
            self.setText(current_text)
            self._current_char_index += 1
        else:
            # 文本显示完毕
            self.typing_timer.stop()
            if self._final_html_text:
                self.setText(self._final_html_text)
            self._is_typing = False
            self.typingFinished.emit() # 发出完成信号

    def skip_typing(self):
        """
        立即显示全部文本并停止打字机。
        """
        if self._is_typing:
            self.typing_timer.stop()
            self.setText(self._final_html_text or self._full_text)
            self._is_typing = False
            self.typingFinished.emit()
            
    # 重新实现 ClickableLabel 基类的内部跳过方法，防止重复连接或冲突
    def _skip_typing_internal(self):
        self.skip_typing()

    def mousePressEvent(self, event):
        """
        点击事件：如果正在打字，则跳过；否则，传递给基类。
        """
        if self._is_typing:
            self.skip_typing()
            self.play_click_sound()
        else:
            super().mousePressEvent(event) # 传递给 ClickableLabel 的点击处理

class VolumeDialog(QDialog):
    """用于设置音量的对话框（模拟功能）"""
    def __init__(self, current_volume: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("desktop.settings_dialog.volume_title"))
        self.setModal(True)
        # 假设音量范围是 0-100
        self.current_volume = current_volume
        self.new_volume = current_volume

        # 样式与 FontSizeDialog 保持一致
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(0, 0, 0, 200);
                border-radius: 10px;
                color: white;
            }
            QLabel {
                color: white;
                font-size: 16px;
                padding: 5px;
            }
            QSlider::groove:horizontal {
                height: 8px;
                background: #505050;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #4CAF50;
                border: 1px solid #ddd;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QPushButton {
                background-color: rgba(76, 175, 80, 200);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(76, 175, 80, 255);
            }
        """)

        self.init_ui()
        self.adjustSize()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # 标签
        info_label = QLabel(tr("desktop.settings_dialog.volume_hint"))
        layout.addWidget(info_label)

        # 滑块
        self.slider = QSlider(Qt.Orientation.Horizontal)
        # 音量范围 0-100
        self.slider.setRange(0, 100) 
        # 初始值是当前的音量
        self.slider.setValue(self.current_volume) 
        self.slider.setSingleStep(1)
        self.slider.valueChanged.connect(self.update_label)
        layout.addWidget(self.slider)

        # 当前值显示标签
        self.value_label = QLabel(tr("desktop.settings_dialog.volume_current", value=self.current_volume))
        layout.addWidget(self.value_label)

        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.confirm_button = QPushButton(tr("desktop.settings_dialog.ok"))
        self.confirm_button.clicked.connect(self.accept)
        button_layout.addWidget(self.confirm_button)

        self.cancel_button = QPushButton(tr("desktop.settings_dialog.cancel"))
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(200, 50, 50, 200);
            }
            QPushButton:hover {
                background-color: rgba(200, 50, 50, 255);
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def update_label(self, value):
        """滑块值变化时更新标签和内部变量"""
        self.new_volume = value
        self.value_label.setText(tr("desktop.settings_dialog.volume_current", value=value))
        # 在实际应用中，这里可能会调用一个函数来实时改变音量

    def get_new_volume(self):
        """返回用户设置的新音量值"""
        return self.new_volume

class CGWidget(QWidget):
    """
    只用于显示全屏CG图和操作按钮的浮动Widget。
    - 负责在显示时覆盖所有下层元素（包括立绘）。
    """
    cg_display_changed = Signal(bool)  # True: CG显示, False: CG隐藏

    def __init__(self, theme_color: str, parent=None):
        super().__init__(parent)
        self.theme_color = theme_color
        self.current_cg_pixmap = None
        
        # 必须设置 WA_TranslucentBackground 和 FramelessWindowHint 才能实现完全透明
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow
        )  # 确保它浮动在父窗口之上
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. CG 图像标签 (全屏，用于显示CG)
        self.cg_label = QLabel()
        self.cg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cg_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # 设置一个黑色或半透明背景，以覆盖下层元素
        self.cg_label.setStyleSheet("background-color: rgba(0, 0, 0, 100);")
        main_layout.addWidget(self.cg_label)
        
        # 2. CG 按钮工具栏 (浮动在右上角)
        self.setup_cg_toolbar()
        
        self.hide() # 初始隐藏

    def _cg_toolbar_button_stylesheet(self) -> str:
        return f"""
            QPushButton {{
                background-color: rgba(50, 50, 50, 150);
                border: 2px solid {self.theme_color};
                border-radius: 10px;
                color: white;
                padding: 10px 20px;
                font-size: 20px;
            }}
            QPushButton:hover {{
                background-color: rgba(50, 50, 50, 200);
            }}
        """

    def set_theme_color(self, theme_color: str) -> None:
        """与主窗设置里的主题色同步。"""
        self.theme_color = theme_color
        if getattr(self, "save_cg_btn", None) is None:
            return
        bs = self._cg_toolbar_button_stylesheet()
        self.save_cg_btn.setStyleSheet(bs)
        self.close_cg_btn.setStyleSheet(bs)

    def setup_cg_toolbar(self):
        """设置 CG 模式下的操作按钮工具栏"""
        self.cg_toolbar = QWidget(self) # 以自身为父组件
        self.cg_toolbar.setStyleSheet("background-color: transparent;")
        
        toolbar_layout = QHBoxLayout(self.cg_toolbar)
        toolbar_layout.setContentsMargins(15, 15, 15, 15)
        toolbar_layout.setSpacing(10)
        toolbar_layout.addStretch(1)

        button_style = self._cg_toolbar_button_stylesheet()

        self.save_cg_btn = QPushButton(f"💾 {tr('desktop.settings_dialog.cg_save')}")
        self.save_cg_btn.setStyleSheet(button_style)
        self.save_cg_btn.clicked.connect(self.save_current_cg)
        
        self.close_cg_btn = QPushButton(f"❌ {tr('desktop.settings_dialog.cg_close')}")
        self.close_cg_btn.setStyleSheet(button_style)
        self.close_cg_btn.clicked.connect(self.hide_cg)

        toolbar_layout.addWidget(self.save_cg_btn)
        toolbar_layout.addWidget(self.close_cg_btn)
        
        self.cg_toolbar.adjustSize() # 调整工具栏大小
        self.cg_toolbar.raise_()

    def resizeEvent(self, event):
        """处理 Widget 大小变化，重新定位工具栏"""
        super().resizeEvent(event)
        
        # 确保 cg_label 覆盖整个组件
        self.cg_label.setGeometry(0,0,self.width(),self.height())
        
        # 重新缩放 CG
        if self.current_cg_pixmap:
            scaled_cg = self.current_cg_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.cg_label.setPixmap(scaled_cg)

        # 重新定位 CG 工具栏到右上角
        toolbar_width = self.cg_toolbar.sizeHint().width()
        toolbar_height = self.cg_toolbar.sizeHint().height()
        
        self.cg_toolbar.setGeometry(
            self.width() - toolbar_width - 20, # 右边距 20
            self.height()//2, # 垂直居中
            toolbar_width,
            toolbar_height
        )

    # --- Public Methods ---
    def show_cg(self, cg_path: str):
        """显示 CG 图像"""
        if not os.path.exists(cg_path):
            print(f"CG file not found: {cg_path}")
            return
        
        pixmap = QPixmap(cg_path)
        if pixmap.isNull():
            print(f"Failed to load pixmap from: {cg_path}")
            return
            
        self.current_cg_pixmap = pixmap
        
        # 缩放并设置 CG
        scaled_cg = self.current_cg_pixmap.scaled(
            self.width(),
            self.height(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        self.cg_label.setPixmap(scaled_cg)
        
        self.show()
        self.raise_() # 确保它在最顶层
        self.cg_display_changed.emit(True)

    def hide_cg(self):
        """隐藏 CG 图像"""
        self.hide()
        self.current_cg_pixmap = None
        self.cg_label.clear()
        self.cg_display_changed.emit(False)

    def save_current_cg(self):
        """保存当前显示的 CG 图像（占位符）"""
        if self.current_cg_pixmap is None:
            print("No CG image is currently displayed to save.")
            return

        # 1. 获取用户选择的目录路径
        # QFileDialog.getExistingDirectory 提示用户选择一个现有目录
        save_dir = QFileDialog.getExistingDirectory(
            self, 
            tr("desktop.settings_dialog.cg_choose_save_dir"),
            os.path.expanduser("~") # 默认目录设置为用户主目录
        )

        if save_dir:
            # 2. 生成带时间戳的唯一文件名
            file_name = "CG.png" # 默认使用 PNG 格式
            
            # 3. 组合完整的文件路径
            full_path = os.path.join(save_dir, file_name)
            
            # 4. 尝试保存 QPixmap
            # 注意：保存操作默认是异步的，但对于本地文件保存通常即时完成
            success = self.current_cg_pixmap.save(full_path, "PNG")

            if success:
                print(f"CG saved successfully to: {full_path}")
                # 可选：在这里添加一个 QDialog 提示用户保存成功
                QMessageBox.information(
                    self,
                    tr("desktop.settings_dialog.cg_save_success_title"),
                    tr("desktop.settings_dialog.cg_save_success_body", path=full_path),
                )
            else:
                print(f"Failed to save CG image to: {full_path}")
                # 可选：在这里添加一个 QMessageBox 提示保存失败
                QMessageBox.critical(
                    self,
                    tr("desktop.settings_dialog.cg_save_failed_title"),
                    tr("desktop.settings_dialog.cg_save_failed_body", path=full_path),
                )
        else:
            # 用户取消了保存操作
            print("CG save operation cancelled.")
