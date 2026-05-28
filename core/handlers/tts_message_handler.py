"""
TTS worker 用 Agent dialog 处理器（见 handler_registry.MessageHandler）。

依赖从 :func:`core.runtime.app_runtime.get_app_runtime` 取得，不引用 worker 类型。
"""

from __future__ import annotations

import re
import traceback
from pathlib import Path
from typing import List

from services.config.config_manager import ConfigManager
from core.handlers.protocols import MessageHandler
from core.messaging.dialog_tokens import (
    match_bgm_name,
    match_cg_name,
    match_cot_tts,
    match_system_dialog_tts,
    normalize_character_name,
)
from core.messaging.messages import AgentDialogMessage, TTSOutputMessage
from core.runtime.app_runtime import get_app_runtime, tts_emit_to_ui_queue
from core.sprite.emotion_resolver import resolve_sprite_index
from services.i18n import tr as tr_i18n

_config = ConfigManager()


def get_character_by_name(name: str):
    return _config.get_character_by_name(name)


def _post_tts_busy(text: str) -> None:
    try:
        get_app_runtime().ui_update_manager.post_busy_bar(text, 0.0)
    except Exception:
        pass


def _hide_tts_busy() -> None:
    try:
        get_app_runtime().ui_update_manager.hide_busy_bar()
    except Exception:
        pass


def _cc():
    return get_app_runtime().opencc


class ChainOfThoughtTtsHandler(MessageHandler):
    def can_handle(self, msg: AgentDialogMessage) -> bool:
        return match_cot_tts(_cc(), msg.name)

    def handle(self, msg: AgentDialogMessage) -> None:
        disp_name = _cc().convert(normalize_character_name(msg.name))
        tts_emit_to_ui_queue(
            disp_name,
            msg.text or "",
            str(msg.asset_id if msg.asset_id is not None else "-1"),
            "",
            is_system_message=True,
            effect=msg.effect or "",
        )


class SystemDialogTtsHandler(MessageHandler):
    def can_handle(self, msg: AgentDialogMessage) -> bool:
        return match_system_dialog_tts(_cc(), msg.name)

    def handle(self, msg: AgentDialogMessage) -> None:
        disp_name = _cc().convert(normalize_character_name(msg.name))
        tts_emit_to_ui_queue(
            disp_name,
            msg.text,
            str(msg.asset_id),
            "",
            is_system_message=True,
            effect=msg.effect,
        )


class BgmTtsHandler(MessageHandler):
    def can_handle(self, msg: AgentDialogMessage) -> bool:
        return match_bgm_name(msg.name)

    def handle(self, msg: AgentDialogMessage) -> None:
        rt = get_app_runtime()
        bgm_path = ""
        try:
            sid = int(msg.asset_id) - 1
            bgm_path = rt.bgm_list[sid]
        except Exception as e:
            print("无法得到bgm path", e)
            traceback.print_exc()
        finally:
            tts_emit_to_ui_queue(
                "bgm", "", str(msg.asset_id), bgm_path, is_system_message=True, effect=msg.effect
            )


class CgTtsHandler(MessageHandler):
    def can_handle(self, msg: AgentDialogMessage) -> bool:
        return match_cg_name(msg.name)

    def handle(self, msg: AgentDialogMessage) -> None:
        _post_tts_busy(tr_i18n("desktop.tts_busy_cg"))
        try:
            cg_path = get_app_runtime().t2i_manager.t2i(prompt=msg.text, prompt_processor=None)
            tts_emit_to_ui_queue(
                msg.name, msg.text, "-1", cg_path, is_system_message=True
            )
        except Exception as e:
            print(f"生成CG失败，{e}")
            traceback.print_exc()
        finally:
            _hide_tts_busy()


class DefaultCharacterTtsHandler(MessageHandler):
    """有角色立绘的常规 TTS 路径（末项，始终匹配）。"""

    def can_handle(self, msg: AgentDialogMessage) -> bool:
        return True

    def _active_character_name(self) -> str:
        rt = get_app_runtime()
        if rt.active_character is not None:
            return rt.active_character.name
        return _cc().convert("")

    def handle(self, msg: AgentDialogMessage) -> None:
        rt = get_app_runtime()
        emitted_name = _cc().convert(msg.name)
        active_name = self._active_character_name()
        name_s = active_name or emitted_name
        if emitted_name and active_name and emitted_name != active_name:
            print(f"TTSWorker: 将 Hermes 输出角色「{emitted_name}」归一为当前角色「{active_name}」")
        character_config = get_character_by_name(name_s)
        if character_config is None:
            raise ValueError(f"未找到角色配置: {name_s}")
        translate = msg.translate
        speech = msg.text or ""
        emotion = msg.emotion or "neutral"
        sprite_id = resolve_sprite_index(character_config, emotion)
        asset_id = str(sprite_id + 1) if sprite_id >= 0 else "-1"
        text_processor = rt.text_processor
        speech_text = speech
        if translate:
            text_processor = None
            speech_text = rt.text_processor.remove_parentheses(translate)
            speech_text = rt.text_processor.replace_names(speech_text)
        audio_path = ""
        if rt.tts_manager:
            _post_tts_busy(tr_i18n("desktop.tts_busy_synthesizing", name=name_s))
            try:
                if text_processor:
                    speech_text = text_processor.remove_parentheses(speech_text)

                # 根据配置决定是否分句发送
                _api_cfg = _config.config.api_config
                _split_enabled = getattr(_api_cfg, "tts_split_enabled", False)
                _max_len = getattr(_api_cfg, "tts_max_sentence_length", 15)

                _sentences: list[str] = []
                if _split_enabled:
                    _pieces = re.split(r'(?<=[。！？，、；：\.!\?,;:])', speech_text)
                    _pieces = [s.strip() for s in _pieces if s.strip()]
                    _cur = ""
                    for _p in _pieces:
                        if not _cur:
                            _cur = _p
                        elif len(_cur) + len(_p) <= _max_len:
                            _cur += _p
                        else:
                            _sentences.append(_cur)
                            _cur = _p
                    if _cur:
                        _sentences.append(_cur)

                _speed = character_config.speech_speed
                if not _sentences or len(_sentences) <= 1:
                    audio_path = rt.tts_manager.generate_tts(
                        speech_text,
                        text_processor=text_processor,
                        character_name=name_s,
                        speed_factor=_speed,
                    )
                    if not audio_path:
                        reason = str(getattr(rt.tts_manager, "last_error", "") or "").strip()
                        notice = "语音合成失败"
                        if reason:
                            notice += f": {reason}"
                        _post_tts_busy(notice)
                        try:
                            rt.ui_update_manager.post_notification(notice)
                        except Exception:
                            pass
                else:
                    _asset_str = str(asset_id)
                    for _i, _sent in enumerate(_sentences):
                        _path = rt.tts_manager.generate_tts(
                            _sent,
                            text_processor=text_processor,
                            character_name=name_s,
                            speed_factor=_speed,
                        )
                        if not _path:
                            reason = str(getattr(rt.tts_manager, "last_error", "") or "").strip()
                            notice = "语音合成失败"
                            if reason:
                                notice += f": {reason}"
                            _post_tts_busy(notice)
                            try:
                                rt.ui_update_manager.post_notification(notice)
                            except Exception:
                                pass
                        _is_first = _i == 0
                        _is_last = _i == len(_sentences) - 1
                        rt.audio_path_queue.put(TTSOutputMessage(
                            audio_path=_path or "",
                            name=name_s,
                            text=speech if _is_first else "",
                            asset_id=_asset_str if _is_first else _asset_str,
                            emotion=emotion,
                            effect=msg.effect if _is_first else "",
                            is_final_segment=_is_last,
                            timeout=None if _is_first else 0,
                        ))
                    rt.tts_queue.task_done()
                    return  # already emitted per-sentence, skip final tts_emit_to_ui_queue
            finally:
                _hide_tts_busy()
        else:
            try:
                sprite_data = character_config.sprites[sprite_id]
                audio_path = sprite_data.get("voice_path", "") if isinstance(sprite_data, dict) else str(getattr(sprite_data, "voice_path", "") or "")
            except Exception:
                audio_path = ""
        tts_emit_to_ui_queue(
            name_s, speech, str(asset_id), audio_path, is_system_message=False, effect=msg.effect, emotion=emotion,
        )


def get_tts_handlers() -> List[MessageHandler]:
    return [
        ChainOfThoughtTtsHandler(),
        SystemDialogTtsHandler(),
        BgmTtsHandler(),
        CgTtsHandler(),
        DefaultCharacterTtsHandler(),
    ]
