export interface BackendCharacter {
  name: string;
  color: string;
  sprite_prefix: string;
  sprites: Array<Record<string, unknown>>;
  character_profile: Record<string, unknown>;
  character_setting: string;
  visual_reference_image: string;
  visual_identity: string;
  sprite_scale: number;
  emotion_tags: string;
  speech_speed: number;
  speech_volume: number;
  pronunciation_map: Record<string, string>;
}

export interface BackendApiConfig {
  agent_backend: string;
  internal_agent_provider: string;
  internal_agent_model: string;
  internal_agent_base_url: string;
  internal_agent_api_key: string;
  tts_provider: string;
  tts_speed: number;
  tts_split_enabled: boolean;
  tts_max_sentence_length: number;
  t2i_provider: string;
  t2i_api_url: string;
  selfie_provider: string;
  hermes_streaming: boolean;
  hermes_max_iterations: number;
  hermes_enabled_toolsets: string[];
  hermes_disabled_toolsets: string[];
  hermes_reasoning_config: Record<string, unknown>;
  hermes_max_tokens: number | null;
  hermes_use_internal_memory: boolean;
  hermes_disable_native_memory: boolean;
  tts_extra_configs: Record<string, Record<string, unknown>>;
  asr_extra_configs: Record<string, Record<string, unknown>>;
  t2i_extra_configs: Record<string, Record<string, unknown>>;
  selfie_extra_configs: Record<string, unknown>;
}

export interface BackendSystemConfig {
  base_font_size_px: number;
  default_sprite_scale: number;
  active_character_name: string;
  ui_language: string;
  voice_language: string;
  asr_provider: string;
  asr_language: string;
  asr_whisper_model_size: string;
  asr_whisper_device: string;
  asr_whisper_compute_type: string;
  music_volumn: number;
  theme_color: string;
  chat_ui_theme_path: string;
  bgm_path: string;
  background_path: string;
  dialog_box_width_pct: number;
  dialog_box_height_pct: number;
  dialog_box_collapsed: boolean;
  process_hint_collapsed: boolean;
  input_bar_collapsed: boolean;
  chat_delivery_channel: string;
  proactive_contact_enabled: boolean;
  external_delivery_enabled: boolean;
  external_delivery_channel: string;
  external_delivery_requires_confirmation: boolean;
  external_delivery_daily_limit: number;
  external_delivery_quiet_hours: string;
  external_delivery_audio_enabled: boolean;
  proactive_photo_enabled: boolean;
  proactive_photo_daily_limit: number;
  screen_context_enabled: boolean;
  screen_context_interval_seconds: number;
  screen_context_display_ids: string[];
  sprite_realtime_enabled: boolean;
  sprite_realtime_prompt_template: string;
  sprite_realtime_cache_dir: string;
  [key: string]: unknown;
}

export interface BackendHistoryItem {
  id: string;
  role: "user" | "assistant";
  character_name: string;
  text: string;
  created_at: string;
  emotion?: string;
  asset_id?: string | number | null;
  request_id?: string;
  attachments?: string[];
}

export interface DeliveryCapability {
  channel: string;
  label: string;
  supported: boolean;
  configured: boolean;
  available: boolean;
  reason: string;
}

export interface BackendState {
  config: {
    api_config: BackendApiConfig;
    system_config: BackendSystemConfig;
    characters: BackendCharacter[];
    background_list: Array<Record<string, unknown>>;
  };
  active_character_name: string;
  selected_backend: string;
  history: BackendHistoryItem[];
  paths: Record<string, string>;
  capabilities: Record<string, DeliveryCapability>;
  adapter_schemas: Record<string, Record<string, Record<string, unknown>>>;
  chat_ui_theme: ChatUiThemeSnapshot;
  messaging: Record<string, Record<string, unknown>>;
  storage: { character_memory_dir: string; character_assets_dir: string };
  memory: { character: string[]; user: string[] };
  life_plan: Record<string, unknown> | null;
  contact_plan: Record<string, unknown> | null;
}

export interface DesktopState extends BackendState {
  platform: "aix" | "android" | "darwin" | "freebsd" | "haiku" | "linux" | "openbsd" | "sunos" | "win32" | "cygwin" | "netbsd";
  app_version: string;
  window: {
    always_on_top: boolean;
    close_to_tray: boolean;
  };
}

export interface ResolvedSprite {
  index: number;
  path: string;
  frames: string[];
  spritesheet_path?: string;
  frame_width?: number;
  frame_height?: number;
  frame_count?: number;
  frame_row?: number;
  frame_col?: number;
  frame_interval_ms?: number;
  fps?: number;
  state_name?: string;
  state_group?: string;
}

export interface BackendEvent<T = unknown> {
  event: string;
  payload: T;
}

export interface ChatUiThemeSnapshot {
  path: string;
  loaded: boolean;
  dialog_offset_y: number;
  dialog_width_pct: number;
  dialog_padding: number;
  options_gap: number;
  extras: Record<string, string>;
}
