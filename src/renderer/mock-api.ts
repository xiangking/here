import type { BackendEvent, DesktopState, ResolvedSprite } from "../shared/backend-types";
import type { HereDesktopApi } from "../shared/types";

const systemEmotions = ["neutral", "happy", "thinking", "surprised", "sad", "angry"];

const characters = [
  {
    name: "here",
    color: "#f4a7b9",
    sprite_prefix: "here",
    sprites: [
      { path: "assets/characters/here/here_neutral.png", frames: [], state_name: "neutral", state_group: "core_emotion", frame_interval_ms: 120 },
      { path: "assets/characters/here/neutral.mp4", frames: [], state_name: "video_call", state_group: "custom", frame_interval_ms: 120 },
      { path: "assets/characters/system/system_sprite_happy.png", frames: [], state_name: "happy", state_group: "core_emotion", frame_interval_ms: 120 },
      { path: "assets/characters/system/system_sprite_thinking.png", frames: [], state_name: "thinking", state_group: "core_emotion", frame_interval_ms: 120 },
    ],
    character_profile: { identity: { occupation: "桌面伴侣" } },
    character_setting: "自然、温柔、有自己的生活节奏；记住上下文，真诚回应用户。",
    visual_reference_image: "",
    visual_identity: "白色衬衫、自然亲切的写实女性形象。",
    sprite_scale: 0.92,
    emotion_tags: "neutral / happy / thinking / surprised / sad / angry",
    speech_speed: 1,
    speech_volume: 1,
    pronunciation_map: {},
  },
  {
    name: "here_system",
    color: "#84c2d5",
    sprite_prefix: "system_sprite",
    sprites: systemEmotions.map((emotion) => ({
      path: `assets/characters/system/system_sprite_${emotion}.png`,
      frames: [],
      state_name: emotion,
      state_group: "core_emotion",
      frame_interval_ms: 120,
    })),
    character_profile: { identity: { occupation: "设置助手" } },
    character_setting: "清楚、温和、简洁地帮助用户理解设置。",
    visual_reference_image: "",
    visual_identity: "可靠的桌面设置助手。",
    sprite_scale: 0.72,
    emotion_tags: "neutral / happy / thinking / surprised / sad / angry",
    speech_speed: 1,
    speech_volume: 1,
    pronunciation_map: {},
  },
];

const state: DesktopState = {
  config: {
    api_config: {
      agent_backend: "auto",
      internal_agent_provider: "openai",
      internal_agent_model: "gpt-4o-mini",
      internal_agent_base_url: "https://api.openai.com/v1",
      internal_agent_api_key: "",
      tts_provider: "edge-tts",
      tts_speed: 1,
      tts_split_enabled: false,
      tts_max_sentence_length: 15,
      t2i_provider: "image-api",
      t2i_api_url: "http://127.0.0.1:7860/v1/images/generations",
      selfie_provider: "",
      hermes_streaming: true,
      hermes_max_iterations: 90,
      hermes_enabled_toolsets: ["memory", "session_search"],
      hermes_disabled_toolsets: ["telegram", "discord", "wechat", "feishu", "whatsapp", "messaging"],
      hermes_reasoning_config: {},
      hermes_max_tokens: null,
      hermes_use_internal_memory: true,
      hermes_disable_native_memory: true,
      tts_extra_configs: { "edge-tts": { voice: "zh-CN-XiaoxiaoNeural", rate: "+0%" } },
      asr_extra_configs: { vosk: { model_path: "", sample_rate: 16000, chunk_size: 8192 } },
      t2i_extra_configs: {},
      selfie_extra_configs: {},
    },
    system_config: {
      base_font_size_px: 40,
      default_sprite_scale: 0.72,
      active_character_name: "here",
      ui_language: "zh_CN",
      voice_language: "zh",
      asr_provider: "vosk",
      asr_language: "zh",
      asr_whisper_model_size: "small",
      asr_whisper_device: "auto",
      asr_whisper_compute_type: "",
      music_volumn: 30,
      theme_color: "rgba(50,50,50,200)",
      chat_ui_theme_path: "",
      bgm_path: "",
      background_path: "",
      dialog_box_width_pct: 81,
      dialog_box_height_pct: 45,
      dialog_box_collapsed: false,
      process_hint_collapsed: false,
      input_bar_collapsed: false,
      chat_delivery_channel: "desktop_chat",
      proactive_contact_enabled: false,
      external_delivery_enabled: false,
      external_delivery_channel: "desktop_chat",
      external_delivery_requires_confirmation: true,
      external_delivery_daily_limit: 1,
      external_delivery_quiet_hours: "23:00-09:00",
      external_delivery_audio_enabled: false,
      proactive_photo_enabled: false,
      proactive_photo_daily_limit: 1,
      screen_context_enabled: false,
      screen_context_interval_seconds: 300,
      screen_context_display_ids: [],
      sprite_realtime_enabled: false,
      sprite_realtime_prompt_template: "",
      sprite_realtime_cache_dir: "",
    },
    characters,
    background_list: [],
  },
  active_character_name: "here",
  selected_backend: "internal-agent",
  history: [],
  paths: { root: "/mock/here" },
  capabilities: {
    desktop_chat: { channel: "desktop_chat", label: "Desktop Chat", supported: true, configured: true, available: true, reason: "ready" },
    telegram: { channel: "telegram", label: "Telegram", supported: true, configured: false, available: false, reason: "missing_token" },
    discord: { channel: "discord", label: "Discord", supported: true, configured: false, available: false, reason: "missing_webhook" },
    wechat: { channel: "wechat", label: "WeChat", supported: true, configured: false, available: false, reason: "not_logged_in" },
    feishu: { channel: "feishu", label: "Feishu", supported: true, configured: false, available: false, reason: "missing_webhook" },
    whatsapp: { channel: "whatsapp", label: "WhatsApp", supported: true, configured: false, available: false, reason: "missing_token" },
  },
  adapter_schemas: {
    tts: {
      "edge-tts": {
        voice: { type: "str", label: "Voice", default: "zh-CN-XiaoxiaoNeural" },
        rate: { type: "str", label: "Rate", default: "+0%" },
        volume: { type: "str", label: "Volume", default: "+0%" },
        pitch: { type: "str", label: "Pitch", default: "+0Hz" },
      },
    },
    asr: { vosk: { model_path: { type: "str", label: "Vosk 模型目录", default: "" } } },
    t2i: { "image-api": { api_format: { type: "select", label: "请求格式", default: "auto", options: ["auto", "openai", "simple"] } } },
  },
  chat_ui_theme: {
    path: "/mock/here/config/chat_ui_theme.json",
    loaded: false,
    dialog_offset_y: 0,
    dialog_width_pct: 80,
    dialog_padding: 40,
    options_gap: 10,
    extras: {},
  },
  messaging: { telegram: { enabled: false }, discord: { enabled: false }, wechat: { enabled: false }, feishu: { enabled: false }, whatsapp: { enabled: false } },
  storage: { character_memory_dir: "", character_assets_dir: "" },
  memory: { character: ["你喜欢在晚上安静聊天。"], user: ["称呼你为你。"] },
  life_plan: {
    date: "2026-07-16",
    timezone: "Asia/Shanghai",
    day_theme: "工作和自我照顾的一天",
    blocks: [
      { start: "09:00", end: "12:00", activity: "专注工作", location: "窗边书桌", mood: "认真", availability: "能短暂回复" },
      { start: "12:00", end: "13:00", activity: "午饭和休息", location: "附近", mood: "放松", availability: "很适合聊天" },
      { start: "20:00", end: "23:00", activity: "阅读和听音乐", location: "住处", mood: "亲近", availability: "很适合聊天" },
    ],
  },
  contact_plan: {
    date: "2026-07-16",
    contact_style: "温柔、克制，在生活间隙自然想起你。",
    contacts: [
      { window_start: "12:15", window_end: "13:00", intent: "午休时轻轻问候", status: "pending", type: "check_in" },
      { window_start: "20:30", window_end: "21:15", intent: "分享晚上的小片刻", status: "pending", type: "share_moment" },
    ],
  },
  platform: "darwin",
  app_version: "0.1.0-preview",
  window: { always_on_top: true, close_to_tray: true },
};

export function createMockApi(): HereDesktopApi {
  const listeners = new Set<(event: BackendEvent) => void>();
  const send = (event: BackendEvent) => listeners.forEach((listener) => listener(event));
  const resolved = (name: string): { name: string; scale: number; color: string; sprites: ResolvedSprite[] } => {
    const character = state.config.characters.find((item) => item.name === name) || state.config.characters[0];
    return {
      name,
      scale: character.sprite_scale,
      color: character.color,
      sprites: character.sprites.map((sprite, index) => ({
        index,
        path: String(sprite.path || ""),
        frames: Array.isArray(sprite.frames) ? sprite.frames.map(String) : [],
        spritesheet_path: String(sprite.spritesheet_path || ""),
        frame_count: Number(sprite.frame_count || 0),
        frame_interval_ms: Number(sprite.frame_interval_ms || 120),
        fps: Number(sprite.fps || 0),
        state_name: String(sprite.state_name || ""),
        state_group: String(sprite.state_group || ""),
      })),
    };
  };
  return {
    getState: async () => structuredClone(state),
    backendCall: async <T>(method: string, params: Record<string, unknown> = {}) => {
      if (method === "resolve_assets") return resolved(String(params.character_name || state.active_character_name)) as T;
      if (method === "update_memory") {
        const kind = String(params.kind || "character") as "character" | "user";
        state.memory[kind] = [...(params.entries as string[])];
        return structuredClone(state.memory) as T;
      }
      if (method === "generate_image") return { path: "assets/characters/here/here_neutral.png" } as T;
      if (method === "dependency_status") return { asr: { vosk: { missing: [], ready: true } }, video: { missing: [] } } as T;
      if (method === "create_character") {
        const created = structuredClone(characters[0]);
        created.name = `新角色${state.config.characters.length}`;
        created.sprite_prefix = `character_${Date.now()}`;
        created.sprites = [];
        created.character_profile = { identity: { occupation: "" } };
        created.character_setting = "";
        state.config.characters.push(created);
        state.active_character_name = created.name;
        state.config.system_config.active_character_name = created.name;
        return structuredClone(state) as T;
      }
      if (method === "revert_history") {
        const index = state.history.findIndex((item) => item.id === params.user_message_id && item.role === "user");
        if (index >= 0) state.history = state.history.slice(0, index);
        const display = [...state.history].reverse().find((item) => item.role === "assistant");
        const payload = { history: structuredClone(state.history), display };
        send({ event: "history_reverted", payload });
        return payload as T;
      }
      if (method === "start_asr") {
        setTimeout(() => send({ event: "transcript", payload: { text: "今晚想和你聊聊天", final: true } }), 600);
        return { status: "Running" } as T;
      }
      if (method === "stop_asr") return { status: "Stopped" } as T;
      return {} as T;
    },
    saveConfig: async (payload) => {
      if (payload.api_config) state.config.api_config = payload.api_config as typeof state.config.api_config;
      if (payload.system_config) state.config.system_config = payload.system_config as typeof state.config.system_config;
      if (payload.characters) state.config.characters = payload.characters as typeof state.config.characters;
      state.active_character_name = state.config.system_config.active_character_name;
      return structuredClone(state);
    },
    setActiveCharacter: async (name) => {
      state.active_character_name = name;
      state.config.system_config.active_character_name = name;
      send({ event: "character", payload: { name } });
      return structuredClone(state);
    },
    sendMessage: async (request) => {
      const now = new Date().toISOString();
      state.history.push({ id: crypto.randomUUID(), role: "user", character_name: "你", text: request.text, created_at: now });
      send({ event: "chat_start", payload: { request_id: request.requestId, character_name: request.characterName } });
      setTimeout(() => {
        const item = {
          id: crypto.randomUUID(), role: "assistant" as const, character_name: request.characterName,
          text: "我在。这个时间刚好安静下来，你今天最想从哪件事说起？", created_at: new Date().toISOString(),
          emotion: "happy", request_id: request.requestId,
        };
        state.history.push(item);
        send({ event: "dialog", payload: item });
        send({ event: "chat_done", payload: { request_id: request.requestId } });
      }, 750);
    },
    stopMessage: async () => {},
    chooseImages: async () => [],
    captureScreenshots: async () => [],
    chooseFiles: async () => [],
    openPath: async () => "",
    saveAsset: async () => "",
    clearHistory: async () => { state.history = []; return []; },
    copyHistory: async () => {},
    importLegacy: async () => ({ sourcePath: "/mock/here/.local/here", charactersImported: 2, settingsImported: true, warnings: [] }),
    importCodexPet: async () => null,
    localFileUrl: async (path) => path.startsWith("assets/") ? `./${path}` : path,
    windowAction: async (action) => {
      if (action === "toggle-pin") state.window.always_on_top = !state.window.always_on_top;
      return state.window.always_on_top;
    },
    setIgnoreMouseEvents: () => {},
    onBackendEvent: (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
  };
}
