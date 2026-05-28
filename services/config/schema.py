from pydantic import BaseModel, Field, HttpUrl, FilePath, BeforeValidator, field_validator
from pydantic_core import PydanticUseDefault
from typing import List, Dict, Optional, Union, Any, Annotated, TypeVar

# ----------------- 解决 YAML None 问题的工具 -----------------
def default_if_none(value: Any) -> Any:
    """
    如果输入值是 None，则抛出 PydanticUseDefault 异常，
    让 Pydantic 使用字段的默认值。
    """
    if value is None:
        raise PydanticUseDefault()
    return value

# 创建一个可复用的 Annotated 类型，用于在遇到 None 时使用默认值
T = TypeVar('T')
# 注意：该 Annotated 类型应包裹原始类型，并且只能用于设置了默认值的字段。
DefaultIfNone = Annotated[T, BeforeValidator(default_if_none)]
# -------------------------------------------------------------


# Character Config Models
class Sprite(BaseModel):
    """角色的单个立绘/语音配置"""
    path: FilePath = Field(..., description="立绘图片的文件路径")
    frames: DefaultIfNone[List[str]] = Field(default_factory=list, description="该立绘的逐帧动画图片路径列表")
    spritesheet_path: DefaultIfNone[str] = Field(default="", description="该立绘的横向或网格 spritesheet 路径")
    frame_width: DefaultIfNone[int] = Field(default=0, description="spritesheet 单帧宽度")
    frame_height: DefaultIfNone[int] = Field(default=0, description="spritesheet 单帧高度")
    frame_count: DefaultIfNone[int] = Field(default=0, description="spritesheet 帧数")
    frame_row: DefaultIfNone[int] = Field(default=0, description="spritesheet 行索引，从 0 开始")
    frame_col: DefaultIfNone[int] = Field(default=0, description="spritesheet 起始列索引，从 0 开始")
    frame_interval_ms: DefaultIfNone[int] = Field(default=120, description="动画帧间隔，毫秒")
    fps: DefaultIfNone[float] = Field(default=0.0, description="动画帧率；大于 0 时优先于 frame_interval_ms")
    state_name: DefaultIfNone[str] = Field(default="", description="here 标准化状态名，例如 neutral/happy/thinking")
    state_group: DefaultIfNone[str] = Field(
        default="",
        description="状态分组：core_emotion / system_optional_emotion / custom / mouse_event",
    )
    source_state: DefaultIfNone[str] = Field(default="", description="导入来源中的原始状态名，例如 Codex Pet 的 jumping")
    voice_path: Optional[FilePath] = Field(None, description="对应的语音文件的路径 (可选)")
    voice_text: Optional[str] = Field(None, description="语音对应的文本内容 (可选, 存在于某些条目中)")

class Character(BaseModel):
    """单个角色配置的实体模型"""
    # 角色基本信息
    name: str = Field(..., description="角色名称")
    color: str = Field(..., description="角色对话框或名字的颜色")
    sprite_prefix: str = Field(..., description="立绘文件名的通用前缀")
    # 列表中可能包含 Sprite 模型，也可能只是原始字典
    sprites: List[Union[Sprite, dict]] = Field(default_factory=list, description="角色的立绘和对应语音的列表")
    character_profile: Dict[str, Any] = Field(..., description="结构化角色设定资料，用于生成 character_setting")
    character_setting: DefaultIfNone[str] = Field(default="", description="角色背景、性格和语言习惯的详细描述")
    visual_reference_image: DefaultIfNone[str] = Field(default="", description="角色视觉一致性参考图路径或 URL")
    visual_identity: DefaultIfNone[str] = Field(default="", description="角色外貌、穿搭、体态、视觉风格等身份描述")
    sprite_scale: DefaultIfNone[float] = Field(default=1.0, description="立绘的缩放比例 (默认值 1.0)")
    emotion_tags: DefaultIfNone[str] = Field(default="", description="情绪标签和对应的立绘编号描述")
    speech_speed: DefaultIfNone[float] = Field(default=1.0, description="角色TTS语速倍率 (默认值 1.0)")
    speech_volume: DefaultIfNone[float] = Field(default=1.0, description="角色TTS语音音量 (0.0-2.0, 默认 1.0)")
    pronunciation_map: DefaultIfNone[Dict[str, str]] = Field(default_factory=dict, description="角色名 → 日语读音映射（用于 TTS 发音替换）")

    @field_validator("character_profile")
    @classmethod
    def _validate_character_profile(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        from core.sprite.character_profile import require_character_profile

        return require_character_profile(value)

class Background(BaseModel):
    """单个背景配置的实体模型"""
    name: str = Field(..., description="背景组名称")
    sprite_prefix: str = Field(..., description="背景图片的上传目录名")
    sprites: List[Union[Sprite, dict]] = Field(default_factory=list, description="背景图片列表")
    bg_tags: DefaultIfNone[str] = Field(default="", description="背景图片的信息") # 应用 DefaultIfNone
    bgm_list: Optional[List[str]] = Field(default_factory=list, description="背景音乐列表")
    bgm_tags: DefaultIfNone[str] = Field(default="",description="背景音乐描述")

# API Config Model
class ApiConfig(BaseModel):
    """API 相关的配置，如 TTS、生图 API 和 Hermes Agent 的设置"""
    agent_backend: DefaultIfNone[str] = Field(
        default="auto",
        description="Agent 后端: hermes-agent / internal-agent / auto",
    )
    internal_agent_provider: DefaultIfNone[str] = Field(
        default="openai",
        description="Internal Agent 模型供应商标识，仅用于配置和环境变量提示",
    )
    internal_agent_model: DefaultIfNone[str] = Field(
        default="gpt-4o-mini",
        description="Internal Agent 模型名",
    )
    internal_agent_base_url: DefaultIfNone[Union[HttpUrl, str]] = Field(
        default="https://api.openai.com/v1",
        description="Internal Agent OpenAI-compatible Base URL",
    )
    internal_agent_api_key: DefaultIfNone[str] = Field(
        default="",
        description="Internal Agent API Key；留空时读取环境变量",
    )
    tts_provider: DefaultIfNone[str] = Field(
        default="edge-tts",
        description="TTS 提供器: edge-tts / openai-tts / elevenlabs / minimax-tts / fish-audio / none（不使用语音合成）",
    )
    tts_speed: DefaultIfNone[float] = Field(default=1.0, description="TTS 语速 (默认值 1.0)")

    tts_split_enabled: DefaultIfNone[bool] = Field(default=False, description="是否启用TTS分句发送")
    tts_max_sentence_length: DefaultIfNone[int] = Field(default=15, description="TTS分句最大长度（字符数）")

    t2i_provider: DefaultIfNone[str] = Field(
        default="image-api",
        description="生图引擎标识（与 T2IAdapterFactory 注册名一致）",
    )
    t2i_api_url: DefaultIfNone[Union[HttpUrl, str]] = Field(default='http://127.0.0.1:7860/v1/images/generations', description="生图 API 的访问 URL")
    selfie_provider: DefaultIfNone[str] = Field(
        default="",
        description="自拍/主动联系配图使用的生图引擎；留空则沿用 t2i_provider",
    )

    hermes_streaming: DefaultIfNone[bool] = Field(default=True, description="是否流式输出 Hermes 正文")
    hermes_max_iterations: DefaultIfNone[int] = Field(default=90, description="Hermes Agent 最大循环次数")
    hermes_enabled_toolsets: DefaultIfNone[List[str]] = Field(default_factory=lambda: ["memory", "session_search"], description="限定启用的 Hermes toolsets；默认保留 memory 与 session_search，避免桌面精灵聊天误触发文件/终端/浏览器工具")
    hermes_disabled_toolsets: DefaultIfNone[List[str]] = Field(
        default_factory=lambda: ["telegram", "discord", "wechat", "feishu", "whatsapp", "messaging"],
        description="禁用的 Hermes toolsets",
    )
    hermes_reasoning_config: DefaultIfNone[Dict[str, Any]] = Field(default_factory=dict, description="Hermes reasoning_config")
    hermes_max_tokens: Optional[int] = Field(default=None, description="Hermes 单轮 max_tokens；留空交给 provider 默认")
    hermes_use_internal_memory: DefaultIfNone[bool] = Field(default=True, description="是否使用应用维护的角色记忆目录（SOUL.md / memories）")
    hermes_disable_native_memory: DefaultIfNone[bool] = Field(default=True, description="兼容字段：不读取本机 ~/.hermes soul/memory")

    tts_extra_configs: DefaultIfNone[Dict[str, Dict[str, Any]]] = Field(
        default_factory=dict,
        description="TTS 适配器扩展参数：引擎 slug -> 字段名 -> 值",
    )
    asr_extra_configs: DefaultIfNone[Dict[str, Dict[str, Any]]] = Field(
        default_factory=dict,
        description="ASR 适配器扩展参数：后端 slug -> 字段名 -> 值",
    )
    t2i_extra_configs: DefaultIfNone[Dict[str, Dict[str, Any]]] = Field(
        default_factory=dict,
        description="生图适配器扩展参数：引擎名 -> 字段名 -> 值",
    )
    selfie_extra_configs: DefaultIfNone[Dict[str, Any]] = Field(
        default_factory=dict,
        description="自拍/主动联系配图参数，如 quality、aspect_ratio、negative_prompt 等",
    )

# System Config Model
class SystemConfig(BaseModel):
    """系统相关的通用配置"""
    # 应用 DefaultIfNone
    base_font_size_px: DefaultIfNone[int] = Field(default=56, description="基础字体大小 (像素)")
    default_sprite_scale: DefaultIfNone[float] = Field(
        default=0.72,
        description="默认精灵缩放倍率",
    )
    active_character_name: DefaultIfNone[str] = Field(
        default="",
        description="桌面精灵当前选中的角色名",
    )
    ui_language: DefaultIfNone[str] = Field(
        default="zh_CN",
        description="界面语言: zh_CN / en / ja",
    )
    voice_language: DefaultIfNone[str] = Field(default='ja', description="系统语音的默认语言 (例如: ja)")
    asr_provider: DefaultIfNone[str] = Field(
        default="vosk",
        description="麦克风语音识别后端：vosk | faster_whisper | realtime_stt",
    )
    asr_language: DefaultIfNone[str] = Field(
        default="",
        description="麦克风识别语言 UI 码（en/zh/ja/yue），留空则跟随 ui_language",
    )
    asr_whisper_model_size: DefaultIfNone[str] = Field(
        default="small",
        description="faster-whisper / RealtimeSTT 模型名（如 tiny/base/small）或本地模型目录",
    )
    asr_whisper_device: DefaultIfNone[str] = Field(
        default="auto",
        description="faster-whisper / RealtimeSTT 设备：auto | cuda | cpu",
    )
    asr_whisper_compute_type: DefaultIfNone[str] = Field(
        default="",
        description="faster-whisper / RealtimeSTT compute_type，留空则按设备自动选择",
    )
    music_volumn: DefaultIfNone[int] =Field(default=30,description="bgm 音量")
    theme_color: DefaultIfNone[str] = Field(default='rgba(50,50,50,200)',description="主题色")
    bgm_path: DefaultIfNone[str] = Field(default="",description="BGM 的路径")
    background_path: DefaultIfNone[str] = Field(default="",description="背景图片的路径")
    chat_window_geometry_b64: DefaultIfNone[str] = Field(
        default="",
        description="聊天主窗口上次关闭时的 saveGeometry Base64，留空则使用默认居中与尺寸",
    )
    chat_ui_theme_path: DefaultIfNone[str] = Field(
        default="",
        description="聊天主窗外观补丁 JSON 路径，留空则使用 here app home 中的 chat_ui_theme.json（若存在）",
    )
    dialog_box_width_pct: DefaultIfNone[int] = Field(
        default=0,
        description="桌面对话框宽度占可用覆盖区百分比；0 表示沿用主题默认宽度",
    )
    dialog_box_height_pct: DefaultIfNone[int] = Field(
        default=0,
        description="桌面对话框高度占底栏上方可用区百分比；0 表示默认跟随输入栏高度",
    )
    dialog_box_collapsed: DefaultIfNone[bool] = Field(
        default=False,
        description="桌面对话框是否处于收起状态",
    )
    process_hint_collapsed: DefaultIfNone[bool] = Field(
        default=False,
        description="思考、工具执行、语音合成等过程提示条是否处于收起状态",
    )
    input_bar_collapsed: DefaultIfNone[bool] = Field(
        default=False,
        description="底部输入栏是否处于收起状态",
    )
    chat_delivery_channel: DefaultIfNone[str] = Field(
        default="desktop_chat",
        description="普通聊天界面/收发平台: desktop_chat / telegram / discord / wechat / feishu / whatsapp",
    )
    proactive_contact_enabled: DefaultIfNone[bool] = Field(
        default=False,
        description="是否允许当前 active character 在后台按日程主动联系用户",
    )
    external_delivery_enabled: DefaultIfNone[bool] = Field(
        default=False,
        description="是否允许主动联系通过 Telegram/Discord/WeChat/Feishu/WhatsApp 等外部渠道送达",
    )
    external_delivery_channel: DefaultIfNone[str] = Field(
        default="desktop_chat",
        description="主动联系送达渠道: desktop_chat / telegram / discord / wechat / feishu / whatsapp",
    )
    external_delivery_requires_confirmation: DefaultIfNone[bool] = Field(
        default=True,
        description="外部渠道发送前是否需要确认；第一版默认保守开启",
    )
    external_delivery_daily_limit: DefaultIfNone[int] = Field(
        default=1,
        description="每天允许通过外部渠道发送的主动联系数量",
    )
    external_delivery_quiet_hours: DefaultIfNone[str] = Field(
        default="23:00-09:00",
        description="外部渠道免打扰时间段，格式 HH:MM-HH:MM",
    )
    external_delivery_audio_enabled: DefaultIfNone[bool] = Field(
        default=False,
        description="外部渠道主动联系是否附带 TTS 语音；默认关闭，仅发送文本/图片等显式内容",
    )
    proactive_photo_enabled: DefaultIfNone[bool] = Field(
        default=False,
        description="主动联系是否允许在合适场景附带自拍/当前状态照片",
    )
    proactive_photo_daily_limit: DefaultIfNone[int] = Field(
        default=1,
        description="每天主动联系最多附带多少张自拍/当前状态照片",
    )

    # 立绘实时生成开关
    sprite_realtime_enabled: DefaultIfNone[bool] = Field(
        default=False,
        description="是否启用实时立绘生成（True: 使用生图 API 实时生成; False: 使用本地静态立绘）",
    )
    sprite_realtime_prompt_template: DefaultIfNone[str] = Field(
        default="",
        description="实时立绘生成的提示词模板，可用 {character_name}, {emotion}, {scene} 占位符",
    )
    sprite_realtime_cache_dir: DefaultIfNone[str] = Field(
        default="",
        description="实时生成的立绘缓存目录；留空则使用 here app home cache/sprite_cache",
    )

# Main Config Model
class AppConfig(BaseModel):
    """应用的整体配置模型，包含角色列表、API 配置和系统配置"""
    characters: List[Character] = Field(..., description="角色配置列表")
    background_list: List[Background] = Field(..., description="背景组设置")
    api_config: ApiConfig = Field(..., description="API 相关配置")
    system_config: SystemConfig = Field(..., description="系统相关配置")
