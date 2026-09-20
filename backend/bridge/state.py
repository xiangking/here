from __future__ import annotations

from typing import Any

from bridge import hooks
from bridge.deps import (
    ApiConfig,
    Character,
    DeliveryCapabilityProbe,
    MessagingConfig,
    SystemConfig,
    load_storage_paths,
)
from infrastructure.asset_paths import UnsafeSpritePrefixError, sprite_prefix_in_use, validate_sprite_prefix


def state(self) -> dict[str, Any]:
    active_name = self.config.resolve_active_character_name()
    character = self.config.get_character_by_name(active_name)
    capabilities = {
        key: hooks.model_json(value)
        for key, value in DeliveryCapabilityProbe(self.config).probe().items()
    }
    life_plan = None
    contact_plan = None
    if character is not None:
        try:
            life_plan = self.life.ensure_daily_plan(character, allow_llm_generate=False)
            contact_plan = self.contacts.ensure_contact_plan(
                character,
                life_plan,
                agent_backend=self.agent,
                allow_llm_generate=False,
            )
        except Exception as exc:
            print(f"Plan snapshot failed: {exc}")
    return {
        "config": hooks.model_json(self.config.config),
        "active_character_name": active_name,
        "selected_backend": getattr(self.agent, "selected_backend_id", type(self.agent).__name__),
        "history": self._history(),
        "paths": hooks.model_json(self.paths.__dict__),
        "capabilities": capabilities,
        "adapter_schemas": hooks.adapter_schemas(),
        "chat_ui_theme": hooks.chat_ui_theme_snapshot(
            str(getattr(self.config.config.system_config, "chat_ui_theme_path", "") or "")
        ),
        "messaging": MessagingConfig.auto_load().to_dict(),
        "storage": hooks.model_json(load_storage_paths(self.paths.root).__dict__),
        "memory": {
            "character": self.memory.read_character_memories(active_name),
            "user": self.memory.read_user_profile(active_name),
        },
        "life_plan": hooks.model_json(life_plan.to_dict()) if life_plan else None,
        "contact_plan": hooks.model_json(contact_plan.to_dict()) if contact_plan else None,
    }


def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
    rename = payload.get("character_rename") if isinstance(payload.get("character_rename"), dict) else {}
    old_name = str(rename.get("old_name") or "").strip()
    new_name = str(rename.get("new_name") or "").strip()
    if "api_config" in payload:
        self.config.config.api_config = ApiConfig.model_validate(payload["api_config"])
        self.config.save_api_config()
    if "system_config" in payload:
        self.config.config.system_config = SystemConfig.model_validate(payload["system_config"])
        self.config.save_system_config()
    if "characters" in payload:
        characters = [Character.model_validate(item) for item in payload["characters"]]
        seen: set[str] = set()
        for character in characters:
            prefix = str(character.sprite_prefix or "").strip()
            if not prefix:
                continue
            try:
                prefix = validate_sprite_prefix(prefix)
            except UnsafeSpritePrefixError as exc:
                raise ValueError(str(exc)) from exc
            if prefix in seen or sprite_prefix_in_use(characters, prefix, exclude_name=character.name):
                raise ValueError(f"资源前缀已被其他角色使用：{prefix}")
            seen.add(prefix)
            character.sprite_prefix = prefix
        self.config.config.characters = characters
        self.config.save_characters_config()
    if old_name and new_name and old_name != new_name:
        try:
            self.memory.rename_character(old_name, new_name)
        except FileNotFoundError:
            pass
    self.reload_runtime()
    return self.state()


def set_active_character(self, name: str) -> dict[str, Any]:
    active = self.config.set_active_character_name(name)
    self.agent.reset_session()
    hooks.event("character", {"name": active})
    return self.state()


def update_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("character_name") or self.config.resolve_active_character_name())
    kind = str(payload.get("kind") or "character")
    entries = [str(item).strip() for item in payload.get("entries", []) if str(item).strip()]
    if kind == "user":
        self.memory.write_user_profile(name, entries)
    else:
        self.memory.write_character_memories(name, entries)
    return {"character": self.memory.read_character_memories(name), "user": self.memory.read_user_profile(name)}
