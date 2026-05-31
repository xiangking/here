"""
队列消息 Pydantic 模型。

Hermes 角色对话使用 ``character_name`` / ``speech`` / ``emotion``。
系统资源消息在代码中仍用 ``asset_id`` 表示背景、BGM 等非角色资源编号。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, Optional, Union


class UserInputMessage(BaseModel):
    """用户输入队列的消息格式 (user_input_queue)。"""

    text: str = Field(..., description="用户输入的聊天文本")


class AgentDialogMessage(BaseModel):
    """Hermes Agent 输出对话片段队列的消息格式 (tts_queue)。"""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., alias="character_name", description="实体名称（角色名 / 系统关键字如 bgm/NARR 等）")
    text: Optional[str] = Field("", alias="speech", description="文本内容（台词 / 系统提示）")
    emotion: str = Field("neutral", description="角色情绪状态名，优先使用当前角色本地可用状态")
    asset_id: Optional[Union[str, int]] = Field("-1", description="系统资源编号（BGM / 背景 / CG 等），-1 表示无需变化")
    translate: Optional[str] = Field("", description="可选的翻译文本，如果存在则用于 TTS")
    effect: Optional[str] = Field("", description="特效名称")
    system_action: Optional[Dict[str, Any]] = Field(
        default=None,
        description="here 内部动作，例如确认命名后重命名当前角色；不会进入 TTS/UI 台词",
    )


class TTSOutputMessage(BaseModel):
    """TTS Worker 处理后输出的 UI 队列消息 (audio_path_queue)。"""

    model_config = ConfigDict(populate_by_name=True)

    audio_path: str = Field(..., description="生成的语音 / 资源文件的路径")
    name: str = Field(..., alias="character_name", description="实体名称")
    text: Optional[str] = Field("", alias="speech", description="文本内容")
    emotion: str = Field("neutral", description="角色情绪状态")
    asset_id: Optional[Union[str, int]] = Field("-1", description="系统资源或本地解析后的立绘编号")
    effect: Optional[str] = Field("", description="特效名称")
    is_system_message: bool = Field(False, description="是否是系统通知或非对话消息")
    is_final_segment: bool = Field(True, description="是否是多段TTS中的最后一段")
    timeout: Optional[float] = Field(None, description="可选的等待时间（秒）")
