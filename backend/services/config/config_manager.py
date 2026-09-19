from __future__ import annotations

import yaml
from pathlib import Path

from infrastructure.paths import get_app_paths, seed_defaults, defaults_dir
from services.config.video_call_state import migrate_here_video_call
from typing import Dict, Any, List, Optional, Union
from pydantic import ValidationError
from services.config.schema import AppConfig, Character, ApiConfig, SystemConfig, Background
import traceback
from core.delivery.models import DELIVERY_CHANNELS

SYSTEM_CHARACTER_NAME = "here_system"
LEGACY_SYSTEM_CHARACTER_NAMES = {"系统精灵"}


def _is_reserved_character_name(name: str) -> bool:
    normalized = str(name or "").strip()
    return normalized == SYSTEM_CHARACTER_NAME or normalized in LEGACY_SYSTEM_CHARACTER_NAMES


def _migrate_legacy_system_character_names(
    characters_data: Any,
    system_data: Any,
) -> bool:
    changed = False
    if isinstance(characters_data, list):
        has_new_name = any(
            isinstance(item, dict) and str(item.get("name") or "").strip() == SYSTEM_CHARACTER_NAME
            for item in characters_data
        )
        for item in characters_data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name not in LEGACY_SYSTEM_CHARACTER_NAMES:
                continue
            if has_new_name:
                continue
            item["name"] = SYSTEM_CHARACTER_NAME
            has_new_name = True
            changed = True
    if isinstance(system_data, dict):
        active = str(system_data.get("active_character_name") or "").strip()
        if active in LEGACY_SYSTEM_CHARACTER_NAMES:
            system_data["active_character_name"] = SYSTEM_CHARACTER_NAME
            changed = True
    return changed


def is_placeholder_character_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    return text.startswith("角色") or text.lower() in {"testchar", "default", "character"}

class ConfigManager:
    """
    配置管理器：负责加载、保存和管理应用的全局配置。
    使用单例模式确保全局只有一个配置实例。
    """
    _instance: Optional['ConfigManager'] = None
    _config: Optional[AppConfig] = None
    
    _VERSION_PATH = Path("VERSION")

    def _refresh_paths(self) -> None:
        self._paths = get_app_paths()
        seed_defaults(self._paths)
        self._API_CONFIG_PATH = self._paths.config_dir / "api.yaml"
        self._CHARACTERS_CONFIG_PATH = self._paths.config_dir / "characters.yaml"
        self._SYSTEM_CONFIG_PATH = self._paths.config_dir / "system_config.yaml"
        self._BACKGOUND_CONFIG_PATH = self._paths.config_dir / "background.yaml"

    def __new__(cls, *args, **kwargs):
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._refresh_paths()
            cls._instance._load_all_configs()
        return cls._instance

    @property
    def version(self) -> str:
        """读取项目根目录 VERSION 文件，缺失时返回占位字符串。"""
        try:
            text = self._VERSION_PATH.read_text(encoding="utf-8").strip()
            return text if text else "unknown"
        except Exception:
            return "unknown"

    @property
    def config(self) -> AppConfig:
        """提供对 Pydantic AppConfig 实例的访问"""
        if self._config is None:
            # 如果配置尚未加载，尝试重新加载或抛出错误
            self._load_all_configs()
            if self._config is None:
                 raise RuntimeError("配置加载失败，无法访问配置数据。")
        return self._config

    # --- 内部加载/合并逻辑 ---
    def _load_yaml(self, file_path: Path) -> Dict[str, Any]:
        """加载单个 YAML 文件"""
        if not file_path.exists():
            print(f"警告：配置文件未找到：{file_path}")
            return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise IOError(f"加载配置文件 {file_path} 失败: {e}")

    def _load_all_configs(self) -> None:
        """加载所有配置并合并到一个结构中"""
        try:
            # 加载单个配置文件
            api_data = self._load_yaml(self._API_CONFIG_PATH)
            characters_data = self._load_yaml(self._CHARACTERS_CONFIG_PATH)
            system_data = self._load_yaml(self._SYSTEM_CONFIG_PATH)
            background_data = self._load_yaml(self._BACKGOUND_CONFIG_PATH)
            migrated_legacy_names = _migrate_legacy_system_character_names(characters_data, system_data)

            # 通过 Pydantic 进行验证和结构化
            api_config = ApiConfig.model_validate(api_data)
            system_config = SystemConfig.model_validate(system_data)

            # 对于 characters.yaml，它是一个列表，直接传递给 List[Character]
            if not isinstance(characters_data, list):
                characters_data = [] # 处理文件为空或格式错误的情况
            video_call_marker = self._paths.config_dir / ".here-video-call-v1"
            migrated_video_call = not video_call_marker.exists() and migrate_here_video_call(
                characters_data, self._paths.characters_dir, defaults_dir() / "characters",
            )
            if not isinstance(background_data, list):
                background_data = [] # 处理文件为空或格式错误的情况
                
            character_list = [Character.model_validate(item) for item in characters_data]
            background = [Background.model_validate(item) for item in background_data]

            # 构建顶层 AppConfig 实体
            self._config = AppConfig(
                api_config=api_config,
                system_config=system_config,
                characters=character_list,
                background_list=background
            )
            if migrated_legacy_names:
                self.save_characters_config()
                self.save_system_config()
            elif migrated_video_call:
                self.save_characters_config()
            if not video_call_marker.exists():
                video_call_marker.write_text("1\n", encoding="utf-8")
            print("配置加载成功！")
        except ValidationError as e:
            self._config = None
            traceback.print_exc()
            raise ValueError(f"配置验证失败，请检查配置文件格式: \n {e.json()}") from e
        except Exception as e:
            self._config = None
            raise Exception(f"初始化配置管理器时发生错误: {e}")
            
    # --- 公共方法 ---

    def reload(self) -> None:
        """重新加载所有配置文件"""
        self._refresh_paths()
        self._load_all_configs()
        
    def save_api_config(self) -> None:
        """独立保存 API 配置到 api.yaml"""
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存 API 配置。")
            return
        
        print("正在保存 api.yaml...")
        # 将 Pydantic 实体转换为字典进行保存
        self._save_single_config(
            self._API_CONFIG_PATH, 
            self.config.api_config.model_dump(by_alias=True, mode="json")
        )
        print("api.yaml 保存完成。")

    def save_system_config(self) -> None:
        """独立保存系统配置到 system_config.yaml"""
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存系统配置。")
            return
            
        print("正在保存 system_config.yaml...")
        self._save_single_config(
            self._SYSTEM_CONFIG_PATH, 
            self.config.system_config.model_dump(by_alias=True, mode="json")
        )
        print("system_config.yaml 保存完成。")

    def set_ui_language(self, code: str) -> None:
        """更新界面语言并写入 system_config.yaml。"""
        if self._config is None:
            return
        from services.i18n.lang import normalize_lang

        sc = self.config.system_config.model_copy(deep=True)
        sc.ui_language = normalize_lang(code)
        self.config.system_config = sc
        self.save_system_config()

    def set_proactive_contact_enabled(self, enabled: bool) -> None:
        """更新主动联系开关并写入 system_config.yaml。"""
        if self._config is None:
            return
        sc = self.config.system_config.model_copy(deep=True)
        sc.proactive_contact_enabled = bool(enabled)
        self.config.system_config = sc
        self.save_system_config()

    def set_proactive_photo_enabled(self, enabled: bool) -> None:
        """更新主动联系附图开关并写入 system_config.yaml。"""
        if self._config is None:
            return
        sc = self.config.system_config.model_copy(deep=True)
        sc.proactive_photo_enabled = bool(enabled)
        self.config.system_config = sc
        self.save_system_config()

    def set_external_delivery_channel(self, channel: str, *, enabled: bool | None = None) -> None:
        """更新外部主动联系渠道并写入 system_config.yaml。"""
        if self._config is None:
            return
        normalized = str(channel or "desktop_chat").strip().lower()
        if normalized not in DELIVERY_CHANNELS:
            normalized = "desktop_chat"
        sc = self.config.system_config.model_copy(deep=True)
        sc.external_delivery_channel = normalized
        if enabled is not None:
            sc.external_delivery_enabled = bool(enabled)
        self.config.system_config = sc
        self.save_system_config()

    def set_chat_delivery_channel(self, channel: str) -> None:
        """更新普通聊天的收发平台并写入 system_config.yaml。"""
        if self._config is None:
            return
        normalized = str(channel or "desktop_chat").strip().lower()
        if normalized not in DELIVERY_CHANNELS:
            normalized = "desktop_chat"
        sc = self.config.system_config.model_copy(deep=True)
        sc.chat_delivery_channel = normalized
        self.config.system_config = sc
        self.save_system_config()

    def resolve_active_character_name(self) -> str:
        """返回当前有效角色名；配置无效时回退到第一个角色。"""
        characters = list(self.config.characters or [])
        names = [str(c.name or "").strip() for c in characters if str(c.name or "").strip()]
        active = str(getattr(self.config.system_config, "active_character_name", "") or "").strip()
        if active and active in names:
            return active
        if names:
            return names[0]
        return SYSTEM_CHARACTER_NAME

    def set_active_character_name(self, name: str) -> str:
        """设置并保存当前角色；若传入无效角色则回退到有效角色。"""
        wanted = str(name or "").strip()
        names = [str(c.name or "").strip() for c in self.config.characters if str(c.name or "").strip()]
        if wanted not in names:
            wanted = names[0] if names else SYSTEM_CHARACTER_NAME
        sc = self.config.system_config.model_copy(deep=True)
        sc.active_character_name = wanted
        self.config.system_config = sc
        self.save_system_config()
        return wanted

    def rename_character(self, old_name: str, new_name: str) -> str:
        """重命名角色并保存 characters.yaml / active_character_name。

        返回最终角色名；不允许自动重命名内置系统角色，也不允许覆盖已有角色。
        """
        old = str(old_name or "").strip()
        new = str(new_name or "").strip()
        if not old or not new:
            return self.resolve_active_character_name()
        if old == new:
            return old
        if _is_reserved_character_name(old):
            return old
        if not is_placeholder_character_name(old):
            return old
        characters = list(self.config.characters or [])
        target = None
        for character in characters:
            name = str(character.name or "").strip()
            if name == new:
                return old
            if name == old:
                target = character
        if target is None:
            return self.resolve_active_character_name()
        target.name = new
        self.save_characters_config()
        active = self.resolve_active_character_name()
        if active == old or str(getattr(self.config.system_config, "active_character_name", "") or "").strip() == old:
            return self.set_active_character_name(new)
        return new

    def delete_character(self, name: str) -> str:
        """删除角色配置并保存，返回删除后解析出的 active 角色名。"""
        wanted = str(name or "").strip()
        if not wanted:
            return self.resolve_active_character_name()
        if _is_reserved_character_name(wanted):
            return self.resolve_active_character_name()
        characters = list(self.config.characters or [])
        kept = [
            character
            for character in characters
            if str(getattr(character, "name", "") or "").strip() != wanted
        ]
        if len(kept) == len(characters):
            return self.resolve_active_character_name()
        self.config.characters = kept
        self.save_characters_config()
        active = str(getattr(self.config.system_config, "active_character_name", "") or "").strip()
        if active == wanted:
            names = [str(c.name or "").strip() for c in kept if str(c.name or "").strip()]
            if SYSTEM_CHARACTER_NAME in names:
                return self.set_active_character_name(SYSTEM_CHARACTER_NAME)
            return self.set_active_character_name("")
        return self.resolve_active_character_name()
    
    def save_api_config_new(
        self,
        is_streaming: str | bool,
        tts_provider: str,
        t2i_provider: str,
        t2i_url: str,
        max_iterations: int,
        enabled_toolsets: list[str] | None,
        disabled_toolsets: list[str] | None,
        reasoning_config: Dict[str, Any] | None,
        max_tokens: int | None,
        tts_split_enabled: bool = False,
        tts_max_sentence_length: int = 15,
        agent_backend: str | None = None,
        internal_agent_provider: str | None = None,
        internal_agent_model: str | None = None,
        internal_agent_base_url: str | None = None,
        internal_agent_api_key: str | None = None,
    ) -> str:
        """
        更新内存中的 ApiConfig，并将其保存到 api.yaml。
        """
        if self._config is None:
            return "错误：配置未加载或加载失败，无法保存 API 配置。"

        print("正在更新并保存 api.yaml...")
        current_api_config = self.config.api_config.model_copy(deep=True)
        current_api_config.hermes_streaming = (
            bool(is_streaming) if isinstance(is_streaming, bool) else is_streaming == "是"
        )
        current_api_config.hermes_max_iterations = int(max_iterations)
        current_api_config.hermes_enabled_toolsets = list(enabled_toolsets or [])
        current_api_config.hermes_disabled_toolsets = list(disabled_toolsets or [])
        current_api_config.hermes_reasoning_config = dict(reasoning_config or {})
        current_api_config.hermes_max_tokens = int(max_tokens) if max_tokens else None
        if agent_backend is not None:
            current_api_config.agent_backend = str(agent_backend or "auto").strip() or "auto"
        if internal_agent_provider is not None:
            current_api_config.internal_agent_provider = str(internal_agent_provider or "").strip()
        if internal_agent_model is not None:
            current_api_config.internal_agent_model = str(internal_agent_model or "").strip()
        if internal_agent_base_url is not None:
            current_api_config.internal_agent_base_url = str(internal_agent_base_url or "").strip()
        if internal_agent_api_key is not None:
            current_api_config.internal_agent_api_key = str(internal_agent_api_key or "").strip()
        def _norm_tts(v: str) -> str:
            s = (v or "").strip().lower()
            if s in ("none", "off", "disable", "disabled", "不使用"):
                return "none"
            legacy = {
                "edge": "edge-tts",
                "edge_tts": "edge-tts",
                "openai": "openai-tts",
                "openai_tts": "openai-tts",
                "eleven": "elevenlabs",
                "eleven_labs": "elevenlabs",
                "minimax": "minimax-tts",
                "minimax_tts": "minimax-tts",
                "fish": "fish-audio",
                "fish_audio": "fish-audio",
            }
            return legacy.get(s, (v or "").strip().lower())

        current_api_config.tts_provider = _norm_tts(tts_provider)

        def _norm_t2i_provider(v: str) -> str:
            s = (v or "").strip()
            if not s:
                return "image-api"
            try:
                from services.t2i.t2i_manager import T2IAdapterFactory

                lowered = s.lower()
                for k in T2IAdapterFactory._adapters:
                    if k.lower() == lowered:
                        return k
            except Exception:
                pass
            return s

        current_api_config.t2i_provider = _norm_t2i_provider(t2i_provider)
        current_api_config.t2i_api_url=t2i_url
        current_api_config.tts_split_enabled = bool(tts_split_enabled)
        current_api_config.tts_max_sentence_length = int(tts_max_sentence_length)
        self.config.api_config = current_api_config

        
        # 6. 持久化到文件
        self._save_single_config(
            self._API_CONFIG_PATH, 
            self.config.api_config.model_dump(by_alias=True, mode="json")
        )
        return "API配置已保存！"

    def save_characters_config(self) -> None:
        """独立保存角色列表配置到 characters.yaml"""
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存角色配置。")
            return
            
        print("正在保存 characters.yaml...")
        # 角色列表需要将每个 Character 实体转换为字典
        characters_data = [char.model_dump(by_alias=True, mode="json") for char in self.config.characters]
        self._save_single_config(self._CHARACTERS_CONFIG_PATH, characters_data)
        print("characters.yaml 保存完成。")
    
    def save_background_config(self) -> None:
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存角色配置。")
            return
            
        print("正在保存 background.yaml...")
        # 角色列表需要将每个 Character 实体转换为字典
        background_data = [char.model_dump(by_alias=True, mode="json") for char in self.config.background_list]
        self._save_single_config(self._BACKGOUND_CONFIG_PATH, background_data)
        print("background.yaml 保存完成。")

    def _save_single_config(self, file_path: Path, data: Union[Dict, List]) -> None:
        """保存单个配置到 YAML 文件"""
        file_path.parent.mkdir(parents=True, exist_ok=True) # 确保目录存在
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                # 使用 default_flow_style=False 提高 YAML 的可读性
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            print(f"错误：保存配置到 {file_path} 失败: {e}")

    def get_background_by_name(self, name: str) -> Optional[Background]:
        for char in self.config.background_list:
            if char.name.lower() == name.lower():
                return char
        return None

    def get_character_by_name(self, name: str) -> Optional[Character]:
        """根据角色名称获取角色配置实体"""
        for char in self.config.characters:
            if char.name.lower() == name.lower():
                return char
        return None

    def get_hermes_config(self) -> Dict[str, Any]:
        api = self.config.api_config
        enabled_toolsets = list(api.hermes_enabled_toolsets or [])
        if not enabled_toolsets:
            enabled_toolsets = ["memory", "session_search"]
        if "memory" in enabled_toolsets and "session_search" not in enabled_toolsets:
            enabled_toolsets.append("session_search")
        return {
            "max_iterations": int(api.hermes_max_iterations),
            "enabled_toolsets": enabled_toolsets,
            "disabled_toolsets": list(api.hermes_disabled_toolsets or []),
            "reasoning_config": dict(api.hermes_reasoning_config or {}),
            "max_tokens": api.hermes_max_tokens,
            "stream": bool(api.hermes_streaming),
            "use_internal_memory": bool(getattr(api, "hermes_use_internal_memory", True)),
            "disable_hermes_native_memory": bool(getattr(api, "hermes_disable_native_memory", True)),
        }

    def get_agent_backend_name(self) -> str:
        return str(getattr(self.config.api_config, "agent_backend", "auto") or "auto")

    def get_internal_agent_config(self) -> Dict[str, Any]:
        api = self.config.api_config
        return {
            "provider": str(getattr(api, "internal_agent_provider", "") or "").strip(),
            "model": str(getattr(api, "internal_agent_model", "") or "").strip(),
            "base_url": str(getattr(api, "internal_agent_base_url", "") or "").strip(),
            "api_key": str(getattr(api, "internal_agent_api_key", "") or "").strip(),
        }

    def get_adapter_extra_config(self, kind: str, provider_key: str) -> Dict[str, Any]:
        """读取某类适配器在指定 provider/slug 下的扩展配置（扁平 dict）。"""
        pk = (provider_key or "").strip()
        if self._config is None:
            return {}
        ac = self.config.api_config
        if kind == "tts":
            src = ac.tts_extra_configs or {}
        elif kind == "asr":
            src = ac.asr_extra_configs or {}
        elif kind == "t2i":
            src = ac.t2i_extra_configs or {}
        else:
            return {}
        return dict(src.get(pk, {}) or {})

    def set_adapter_extra_config(self, kind: str, provider_key: str, data: Dict[str, Any]) -> None:
        """写入扩展配置到内存中的 ApiConfig（需配合 save_api_config 或 save_api_config_new 持久化）。"""
        if self._config is None:
            return
        pk = (provider_key or "").strip()
        ac = self.config.api_config.model_copy(deep=True)
        if kind == "tts":
            m = dict(ac.tts_extra_configs or {})
            m[pk] = dict(data)
            ac.tts_extra_configs = m
        elif kind == "asr":
            m = dict(ac.asr_extra_configs or {})
            m[pk] = dict(data)
            ac.asr_extra_configs = m
        elif kind == "t2i":
            m = dict(ac.t2i_extra_configs or {})
            m[pk] = dict(data)
            ac.t2i_extra_configs = m
        else:
            return
        self.config.api_config = ac

    def merged_tts_factory_kwargs(self, adapter_name: str, base_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        from services.config.adapter_extra_kwargs import filter_kwargs_for_ctor
        from services.tts.tts_manager import TTSAdapterFactory

        slug = (adapter_name or "").strip().lower()
        cls = TTSAdapterFactory._adapters.get(slug)
        out = dict(base_kwargs)
        if cls is None:
            return out
        extra = self.get_adapter_extra_config("tts", slug)
        out.update(filter_kwargs_for_ctor(cls, extra))
        return out

    def merged_t2i_factory_kwargs(self, adapter_name: str, base_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        from services.config.adapter_extra_kwargs import filter_kwargs_for_ctor
        from services.t2i.t2i_manager import T2IAdapterFactory

        name = (adapter_name or "").strip().lower()
        cls = T2IAdapterFactory._adapters.get(name)
        out = dict(base_kwargs)
        if cls is None:
            return out
        extra = self.get_adapter_extra_config("t2i", name)
        out.update(filter_kwargs_for_ctor(cls, extra))
        return out

    def get_base_font_size(self) -> int:
        """获取基础字体大小"""
        return self.config.system_config.base_font_size_px
