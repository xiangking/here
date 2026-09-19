import { createIcons, icons } from "lucide";
import DOMPurify from "dompurify";
import { marked } from "marked";
import "./styles.css";
import type {
  BackendCharacter,
  BackendEvent,
  BackendHistoryItem,
  DesktopState,
  ResolvedSprite,
} from "../shared/backend-types";
import type { Attachment, HereDesktopApi } from "../shared/types";
import { createMockApi } from "./mock-api";
import { isVideoSprite, selectDisplaySprite } from "./sprite-media";
import { applyLocale, observeLocale, setLocale } from "./i18n";
import {
  normalizeThemeColor,
  PauseReasonGate,
  qtDialogBackground,
  qtDialogLayout,
  qtOverlayWidthPx,
  qtDialogResizeSize,
  waitForAudioEnd,
} from "./ui-behavior";
import type { DialogResizeEdge } from "./ui-behavior";

const api: HereDesktopApi = window.hereDesktop || createMockApi();
const $ = <T extends Element>(selector: string): T => {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing element: ${selector}`);
  return element;
};
const $$ = <T extends Element>(selector: string): T[] => Array.from(document.querySelectorAll<T>(selector));
const esc = (value: unknown): string => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");
const clone = <T>(value: T): T => structuredClone(value);
const callPixelIcons = {
  lock: { width: 6, height: 6, rows: "033300/070220/386750/697882/694682/698882", className: "lock" },
  participants: { width: 12, height: 10, rows: "000005bc8000/00003cffe600/05004defe700/3c303beed500/8c84049b7200/4b3200230000/070049ddb720/0029efffffc3/004deeeeeee8/002788888874", className: "participants" },
  more: { width: 4, height: 12, rows: "0020/07c6/08e6/0230/0230/08b5/08d5/0020/0020/08d5/28b5/0230", className: "more" },
  hangup: { width: 17, height: 12, rows: "00000000000000000/00000000000000000/000369aba97420000/05adeeeeeeedc8300/8deeda999aceeec50/dfee9300024ceeec2/eeee8000000beeed3/ceeb40000006ceea0/58420000000005840/00000000000000000/00000000000000000/00000000000000000", className: "hangup" },
} as const;
type CallPixelIconName = keyof typeof callPixelIcons;

const renderCallPixelIcons = (): void => {
  $$<SVGSVGElement>("[data-call-pixel-icon]:not([data-call-pixel-ready])").forEach((svg) => {
    const name = svg.dataset.callPixelIcon as CallPixelIconName;
    const icon = callPixelIcons[name];
    if (!icon) return;
    const rects: string[] = [];
    icon.rows.split("/").forEach((row, y) => {
      let x = 0;
      while (x < row.length) {
        const alpha = row[x];
        let end = x + 1;
        while (end < row.length && row[end] === alpha) end += 1;
        const value = Number.parseInt(alpha, 16);
        if (value) rects.push(`<rect x="${x}" y="${y}" width="${end - x}" height="1" fill="currentColor" fill-opacity="${value / 15}"/>`);
        x = end;
      }
    });
    svg.setAttribute("viewBox", `0 0 ${icon.width} ${icon.height}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("shape-rendering", "crispEdges");
    svg.innerHTML = rects.join("");
    svg.dataset.callPixelReady = "true";
  });
};

const refreshIcons = (): void => {
  createIcons({ icons });
  renderCallPixelIcons();
};

const callIconMarkup = (icon: string): string => {
  if (icon === "video" || icon === "video-off") {
    return '<span class="call-video-icon" aria-hidden="true"><i data-lucide="video"></i></span>';
  }
  if (icon === "mic" || icon === "mic-off") {
    return '<span class="call-microphone-icon" aria-hidden="true"><i data-lucide="mic"></i></span>';
  }
  const pixelName = icon;
  if (pixelName in callPixelIcons) {
    const spec = callPixelIcons[pixelName as CallPixelIconName];
    return `<svg class="call-glyph call-pixel-glyph call-glyph-${spec.className}" data-call-pixel-icon="${pixelName}" aria-hidden="true"></svg>`;
  }
  return `<i data-lucide="${icon}"></i>`;
};

const updateCallControl = (control: HTMLButtonElement, isOff: boolean): void => {
  const kind = control.dataset.callToggle;
  control.classList.toggle("is-off", isOff);
  control.setAttribute("aria-pressed", String(isOff));
  const icon = kind === "video" ? (isOff ? "video-off" : "video")
    : kind === "microphone" ? (isOff ? "mic-off" : "mic")
      : kind === "speaker" ? (isOff ? "volume-x" : "volume-2")
        : "switch-camera";
  control.innerHTML = callIconMarkup(icon);
  control.title = kind === "video" ? (isOff ? "开启视频通话" : "关闭视频通话")
    : kind === "microphone" ? (isOff ? "取消静音" : "静音")
      : kind === "speaker" ? (isOff ? "打开扬声器" : "关闭扬声器")
        : "切换摄像头";
  refreshIcons();
};

let state: DesktopState;
let attachments: Attachment[] = [];
let spriteTimer: number | null = null;
let spriteLoadToken = 0;
let currentEmotion = "neutral";
let currentLifeTab: "life" | "contact" = "life";
let activeSettingsTab = "general";
let asrRunning = false;
let asrStarting = false;
let asrOriginalText = "";
const asrPauseGate = new PauseReasonGate<"reply" | "audio">();
let audioEnabled = true;
// Start in the dedicated video_call state when the character provides one.
let characterVideoEnabled = true;
let currentAudio: HTMLAudioElement | null = null;
let finishCurrentAudio: (() => void) | null = null;
const audioQueue: string[] = [];
let audioQueuePlaying = false;
let backgroundAudio: HTMLAudioElement | null = null;
let currentCgPath = "";
let chatBusy = false;
let chatResponseDone = true;
let dependencyStatus: Record<string, unknown> = {};
let dialogTypingTimer: number | null = null;
let completeDialogTyping: (() => void) | null = null;
let createCharacterStateAssets: Record<string, string[]> = {};
let selectedCreateMbti = "INFP";
let lastGeneratedCharacterSetting = "";
let updatingGeneratedCharacterSetting = false;
const systemWelcomeGifPath = "assets/system/characters/system_sprite/animations/welcome.gif";
let dialogResizeSession: {
  pointerId: number;
  edges: ReadonlySet<DialogResizeEdge>;
  startX: number;
  startY: number;
  startWidth: number;
  startHeight: number;
} | null = null;
let suppressDialogClick = false;

const app = $("#app") as HTMLElement;
const stage = $("#stage") as HTMLElement;
const spriteImage = $("#sprite-image") as HTMLImageElement;
const spriteCanvas = $("#sprite-canvas") as HTMLCanvasElement;
const spriteVideo = $("#sprite-video") as HTMLVideoElement;
let spriteVideoReady: Promise<void> | null = null;
const spriteWrap = $("#sprite-wrap") as HTMLElement;
const dialogCaption = $("#dialog-caption") as HTMLElement;
const dialogPanel = $("#dialog-panel") as HTMLElement;
const dialogComponent = $("#dialog-component") as HTMLElement;
const dialogName = $("#dialog-name") as HTMLElement;
const dialogText = $("#dialog-text") as HTMLElement;
const composer = $("#composer") as HTMLElement;
const callTools = $("#call-tools") as HTMLElement;
const contextMenu = $("#context-menu") as HTMLElement;
const messageInput = $("#message-input") as HTMLTextAreaElement;
const busyBar = $("#busy-bar") as HTMLElement;
const busyText = $("#busy-text") as HTMLElement;
const characterMenu = $("#character-menu") as HTMLElement;
const settingsDialog = $("#settings-dialog") as HTMLDialogElement;
const historyDialog = $("#history-dialog") as HTMLDialogElement;
const lifeDialog = $("#life-dialog") as HTMLDialogElement;
const createCharacterDialog = $("#create-character-dialog") as HTMLDialogElement;

function switchRow(id: string, title: string, detail: string, checked: boolean): string {
  return `<div class="switch-row">
    <div class="switch-copy"><strong>${esc(title)}</strong>${detail ? `<span class="switch-detail">${esc(detail)}</span>` : ""}</div>
    <label class="toggle"><input id="${esc(id)}" type="checkbox" ${checked ? "checked" : ""}><span></span></label>
  </div>`;
}

function field(
  id: string,
  label: string,
  value: unknown,
  options?: { type?: string; wide?: boolean; min?: number; max?: number; step?: number; rows?: number; placeholder?: string; extraClass?: string; readOnly?: boolean; disabled?: boolean },
): string {
  const config = options || {};
  const className = `field${config.wide ? " field-wide" : ""}${config.extraClass ? ` ${config.extraClass}` : ""}`;
  const editState = `${config.readOnly ? " readonly" : ""}${config.disabled ? " disabled" : ""}`;
  if (config.type === "textarea") {
    return `<label class="${className}"><span>${esc(label)}</span><textarea id="${esc(id)}" rows="${config.rows || 4}"${config.placeholder ? ` placeholder="${esc(config.placeholder)}"` : ""}${editState}>${esc(value)}</textarea></label>`;
  }
  return `<label class="${className}"><span>${esc(label)}</span><input id="${esc(id)}" type="${esc(config.type || "text")}" value="${esc(value)}"${config.min !== undefined ? ` min="${config.min}"` : ""}${config.max !== undefined ? ` max="${config.max}"` : ""}${config.step !== undefined ? ` step="${config.step}"` : ""}${config.placeholder ? ` placeholder="${esc(config.placeholder)}"` : ""}${editState}></label>`;
}

function pathField(
  id: string,
  label: string,
  value: unknown,
  picker: "background" | "bgm" | "reference" | "directory",
  wide = true,
  placeholder = "",
): string {
  return `<label class="field${wide ? " field-wide" : ""}"><span>${esc(label)}</span><span class="path-control"><input id="${esc(id)}" type="text" value="${esc(value)}"${placeholder ? ` placeholder="${esc(placeholder)}"` : ""}><button class="icon-button" data-file-picker="${picker}" data-picker-target="${esc(id)}" type="button" title="选择"><i data-lucide="folder-open"></i></button></span></label>`;
}

function selectField(id: string, label: string, value: unknown, options: Array<[string, string]>, wide = false): string {
  return `<label class="field${wide ? " field-wide" : ""}"><span>${esc(label)}</span><select id="${esc(id)}">${options.map(([key, text]) =>
    `<option value="${esc(key)}" ${String(value) === key ? "selected" : ""}>${esc(text)}</option>`).join("")}</select></label>`;
}

function editableChoiceField(id: string, label: string, value: unknown, choices: string[], placeholder = ""): string {
  const listId = `${id}-choices`;
  return `<label class="field"><span>${esc(label)}</span><input id="${esc(id)}" type="text" value="${esc(value)}" list="${esc(listId)}"${placeholder ? ` placeholder="${esc(placeholder)}"` : ""}><datalist id="${esc(listId)}">${choices.map((choice) => `<option value="${esc(choice)}"></option>`).join("")}</datalist></label>`;
}

function pageHeader(title: string, subtitle: string): string {
  return `<h2 class="page-title">${esc(title)}</h2>${subtitle ? `<p class="page-subtitle">${esc(subtitle)}</p>` : ""}`;
}

const schemaLabels: Record<"tts" | "asr" | "t2i", Record<string, string>> = {
  tts: {
    voice: "音色",
    rate: "引擎语速",
    volume: "引擎音量",
    pitch: "音调",
    api_key: "API 密钥",
    group_id: "Group ID",
    model: "模型",
    model_id: "模型",
    voice_id: "音色 ID",
    reference_id: "参考音色 ID",
    response_format: "输出格式",
    output_format: "输出格式",
    audio_format: "音频格式",
    base_url: "基础地址",
    timeout: "超时时间（秒）",
    stability: "稳定性",
    similarity_boost: "相似度增强",
    sample_rate: "采样率",
    bitrate: "比特率",
    mp3_bitrate: "MP3 比特率",
    latency: "延迟模式",
  },
  asr: {
    model_path: "Vosk 模型目录",
    sample_rate: "采样率",
    chunk_size: "音频块大小",
    vad_filter: "语音活动检测",
    chunk_seconds: "分段时长（秒）",
    beam_size: "Beam 数量",
    silence_threshold: "静音阈值",
    chunk_frames: "音频块帧数",
    enable_realtime_transcription: "实时显示识别文字",
    realtime_processing_pause: "实时处理停顿（秒）",
  },
  t2i: {
    api_url: "API 地址",
    api_key: "API 密钥",
    api_style: "API 类型",
    api_format: "请求格式",
    default_model: "模型",
    aspect_ratio: "画面比例",
    image_size: "图像尺寸",
    size: "图像尺寸",
    quality: "图像质量",
    background: "背景模式",
    output_format: "输出格式",
    output_compression: "输出压缩率",
    moderation: "内容审核",
    stream_images: "流式返回图像",
    stream_partial_images: "流式预览数量",
    timeout_s: "超时时间（秒）",
  },
};

const adapterLabels: Record<"tts" | "asr" | "t2i", Record<string, string>> = {
  tts: {
    "edge-tts": "Edge TTS",
    "openai-tts": "OpenAI TTS",
    elevenlabs: "ElevenLabs",
    "minimax-tts": "MiniMax TTS",
    "fish-audio": "Fish Audio",
  },
  asr: {
    vosk: "Vosk",
    faster_whisper: "Faster-Whisper",
    realtime_stt: "Realtime STT",
  },
  t2i: {
    "image-api": "兼容图像 API",
    "xai-grok-imagine": "xAI Grok Imagine",
    "openai-gpt-image": "OpenAI GPT Image",
  },
};

const schemaChoiceLabels: Record<string, string> = {
  auto: "自动",
  low: "低",
  medium: "中",
  high: "高",
  transparent: "透明",
  opaque: "不透明",
  normal: "标准",
  openai: "OpenAI 格式",
  simple: "简单格式",
  fal: "fal 格式",
  openrouter: "OpenRouter 格式",
  mp3: "MP3",
  wav: "WAV",
  pcm: "PCM",
};

function adapterLabel(kind: "tts" | "asr" | "t2i", provider: string): string {
  return adapterLabels[kind][provider] || provider.replaceAll("_", "-");
}

function schemaFields(
  kind: "tts" | "asr" | "t2i",
  provider: string,
  values: Record<string, unknown>,
  idPrefix: string = kind,
): string {
  const schema = state.adapter_schemas[kind]?.[provider] || {};
  const content = Object.entries(schema).map(([key, raw]) => {
    const config = raw as Record<string, unknown>;
    const id = `extra-${idPrefix}-${key}`;
    const configuredValue = values[key];
    const useDefault = config.type !== "password" && String(configuredValue ?? "").trim() === ""
      && String(config.default ?? "").trim() !== "";
    const value = useDefault ? config.default : configuredValue ?? config.default ?? "";
    const label = schemaLabels[kind][key] || String(config.label || key);
    const choices = (config.options || config.choices || config.enum) as unknown[] | undefined;
    if (kind === "t2i" && provider === "image-api" && key === "api_url") return "";
    if (kind === "asr" && key === "model_path") {
      return pathField(id, label, value, "directory", false, "自动使用内置模型目录");
    }
    if (choices?.length) {
      const normalizedChoices = choices.map(String);
      if (config.editable) return editableChoiceField(id, label, value, normalizedChoices, String(config.placeholder || ""));
      return selectField(id, label, value, normalizedChoices.map((item) => [item, schemaChoiceLabels[item] || item]));
    }
    if (config.type === "bool") return switchRow(id, label, String(config.help || ""), Boolean(value));
    const type = config.type === "password" ? "password"
      : ["int", "float", "number"].includes(String(config.type)) ? "number" : "text";
    return field(id, label, value, {
      type,
      min: Number.isFinite(Number(config.min)) ? Number(config.min) : undefined,
      max: Number.isFinite(Number(config.max)) ? Number(config.max) : undefined,
      step: Number.isFinite(Number(config.step)) ? Number(config.step) : undefined,
      placeholder: String(config.placeholder || (config.type === "password" ? "未设置" : "")),
    });
  }).join("");
  return content
    ? `<div class="provider-schema field-grid">${content}</div>`
    : `<div class="provider-schema schema-empty">当前引擎无需额外参数。</div>`;
}

function activeCharacter(): BackendCharacter {
  return state.config.characters.find((item) => item.name === state.active_character_name)
    || state.config.characters[0];
}

function renderSettings(): void {
  const { api_config: apiConfig, system_config: system } = state.config;
  const character = activeCharacter();
  const ttsProviders = [["none", "不使用"], ...Object.keys(state.adapter_schemas.tts || {}).map((key) => [key, adapterLabel("tts", key)])] as Array<[string, string]>;
  const asrProviders = Object.keys(state.adapter_schemas.asr || {}).map((key) => [key, adapterLabel("asr", key)]) as Array<[string, string]>;
  const activeTtsProvider = String(apiConfig.tts_provider || "none");
  const activeAsrProvider = system.asr_provider.replaceAll("-", "_");
  const t2iProviders = Object.keys(state.adapter_schemas.t2i || {}).map((key) => [key, adapterLabel("t2i", key)]) as Array<[string, string]>;
  const imageApiUrl = String(apiConfig.t2i_extra_configs["image-api"]?.api_url || apiConfig.t2i_api_url || "");
  const selfieProvider = String(apiConfig.selfie_provider || apiConfig.t2i_provider || "image-api");

  $("[data-page='general']").innerHTML = pageHeader("通用", "窗口、显示、语言和桌面音频") + `
    <div class="form-section"><h3>界面</h3><div class="field-grid">
      ${selectField("general-language", "界面语言", system.ui_language, [["zh_CN", "简体中文"], ["en", "English"], ["ja", "日本語"], ["ko", "한국어"]])}
      ${field("general-font-size", "基础字号", system.base_font_size_px, { type: "number", min: 10, max: 60, step: 1 })}
      ${field("general-dialog-width", "对白宽度 %", system.dialog_box_width_pct, { type: "number", min: 0, max: 100, step: 1, placeholder: "0 = 使用主题默认" })}
      ${field("general-dialog-height", "对白高度 %", system.dialog_box_height_pct, { type: "number", min: 14, max: 70, step: 1 })}
    </div></div>
    <div class="form-section"><h3>桌面窗口</h3>
      ${switchRow("general-pin", "窗口置顶", "保持角色在其他窗口上方", state.window.always_on_top)}
      ${switchRow("general-dialog", "显示对白", "保留角色的对白区域", !system.dialog_box_collapsed)}
      ${switchRow("general-process", "显示过程状态", "显示思考、工具和生成进度", !system.process_hint_collapsed)}
      ${switchRow("general-input", "显示输入栏", "允许在桌面窗口直接发送消息", !system.input_bar_collapsed)}
    </div>
    <div class="form-section"><h3>背景与声音</h3><div class="field-grid">
      ${pathField("general-background", "背景图片路径", system.background_path, "background", true, "未设置（使用默认背景）")}
      ${pathField("general-bgm", "BGM 路径", system.bgm_path, "bgm", true, "未设置")}
      ${field("general-volume", "BGM 音量", system.music_volumn, { type: "number", min: 0, max: 100, step: 1 })}
      ${field("general-theme", "主题色", system.theme_color)}
      ${field("general-chat-theme-path", "聊天主题文件", system.chat_ui_theme_path, { wide: true, placeholder: "留空使用默认主题" })}
    </div></div>`;

  $("[data-page='agent']").innerHTML = pageHeader("Agent", "Hermes 与内置 OpenAI-compatible Agent") + `
    <div class="form-section"><h3>运行后端</h3><div class="field-grid">
      ${selectField("agent-backend", "Agent 后端", apiConfig.agent_backend, [["auto", "自动选择"], ["internal-agent", "Internal Agent"], ["hermes-agent", "Hermes Agent"]])}
    </div><div id="agent-internal-settings" class="field-grid provider-schema${apiConfig.agent_backend === "hermes-agent" ? " is-hidden" : ""}">
      ${field("agent-provider", "供应商", apiConfig.internal_agent_provider)}
      ${field("agent-model", "模型", apiConfig.internal_agent_model)}
      ${field("agent-base-url", "基础地址", apiConfig.internal_agent_base_url)}
      ${field("agent-api-key", "API 密钥", apiConfig.internal_agent_api_key, { type: "password", wide: true, placeholder: "未设置" })}
    </div><div class="inline-actions"><button id="agent-fetch-models" class="text-button${apiConfig.agent_backend === "hermes-agent" ? " is-hidden" : ""}" type="button"><i data-lucide="refresh-cw"></i><span>获取模型列表</span></button><button id="hermes-install" class="text-button${apiConfig.agent_backend === "internal-agent" ? " is-hidden" : ""}" type="button"><i data-lucide="package-plus"></i><span>安装 Hermes Agent</span></button><select id="agent-model-list" class="inline-select is-hidden"></select></div></div>
    <div class="form-section"><h3>上下文</h3>
      ${switchRow("agent-stream", "流式响应", "接收模型的流式输出", apiConfig.hermes_streaming)}
      ${switchRow("agent-memory", "角色记忆", "按角色分别保存长期记忆", apiConfig.hermes_use_internal_memory)}
      ${switchRow("agent-native-memory", "隔离其他应用记忆", "不读取本机其他应用的记忆数据", apiConfig.hermes_disable_native_memory)}
    </div>`;

  $("[data-page='tts']").innerHTML = pageHeader("TTS", "语音合成与播放") + `
    <div class="form-section"><h3>语音合成</h3><div class="field-grid">
      ${selectField("voice-tts-provider", "语音引擎", activeTtsProvider, ttsProviders)}
    </div><div id="tts-provider-settings" class="${activeTtsProvider === "none" ? "is-hidden" : ""}"><div class="field-grid provider-schema">
      ${selectField("voice-language", "语音语言", system.voice_language, [["zh", "中文"], ["ja", "日本語"], ["en", "English"], ["yue", "粤语"]])}
      ${field("voice-tts-speed", "全局语速", apiConfig.tts_speed, { type: "number", min: 0.5, max: 3, step: 0.1 })}
      ${field("voice-split-length", "分句最大长度", apiConfig.tts_max_sentence_length, { type: "number", min: 5, max: 100, step: 1 })}
    </div>${switchRow("voice-split", "分句合成", "长回复按句拆分语音", apiConfig.tts_split_enabled)}
    <div id="tts-schema">${schemaFields("tts", activeTtsProvider, apiConfig.tts_extra_configs[activeTtsProvider] || {})}</div></div></div>`;

  $("[data-page='asr']").innerHTML = pageHeader("ASR", "麦克风语音识别") + `
    <div class="form-section"><h3>语音识别</h3><div class="field-grid">
      ${selectField("voice-asr-provider", "识别后端", activeAsrProvider, asrProviders)}
      ${selectField("voice-asr-language", "识别语言", system.asr_language, [["", "跟随界面"], ["zh", "中文"], ["ja", "日本語"], ["en", "English"], ["yue", "粤语"]])}
    </div><div id="asr-whisper-fields" class="field-grid provider-schema${activeAsrProvider === "vosk" ? " is-hidden" : ""}">
      ${field("voice-whisper-model", "Whisper 模型", system.asr_whisper_model_size)}
      ${selectField("voice-whisper-device", "计算设备", system.asr_whisper_device, [["auto", "自动"], ["cpu", "CPU"], ["cuda", "CUDA"]])}
      ${field("voice-whisper-compute", "计算精度", system.asr_whisper_compute_type)}
    </div><div id="asr-schema">${schemaFields("asr", activeAsrProvider, apiConfig.asr_extra_configs[activeAsrProvider] || {})}</div>
      <div class="inline-actions"><button id="asr-install" class="text-button" type="button"><i data-lucide="package-plus"></i><span>安装当前识别依赖</span></button><button id="asr-prepare" class="text-button" type="button"><i data-lucide="download"></i><span>检查 / 预载模型</span></button><span id="asr-dependency-status" class="inline-status"></span></div></div>`;

  $("[data-page='image']").innerHTML = pageHeader("图像", "生图、自拍与实时立绘") + `
    <div class="form-section"><h3>生图引擎</h3><div class="field-grid">
      ${selectField("image-provider", "引擎", apiConfig.t2i_provider, t2iProviders)}
      ${selectField("image-selfie-provider", "自拍引擎", apiConfig.selfie_provider, [["", "沿用生图引擎"], ...t2iProviders])}
      ${field("image-api-url", "API 地址", imageApiUrl, { wide: true, extraClass: apiConfig.t2i_provider === "image-api" ? "" : "is-hidden" })}
    </div><div id="t2i-schema">${schemaFields("t2i", apiConfig.t2i_provider, apiConfig.t2i_extra_configs[apiConfig.t2i_provider] || {})}</div></div>
    <div class="form-section"><h3>自拍</h3><div class="field-grid">
      ${field("image-selfie-width", "图片宽度", Number(apiConfig.selfie_extra_configs.width) || 1024, { type: "number", min: 256, max: 4096, step: 64 })}
      ${field("image-selfie-height", "图片高度", Number(apiConfig.selfie_extra_configs.height) || 1024, { type: "number", min: 256, max: 4096, step: 64 })}
      <input id="image-selfie-extra" type="hidden" value="${esc(JSON.stringify(apiConfig.selfie_extra_configs))}">
    </div><div id="selfie-schema">${schemaFields("t2i", selfieProvider, apiConfig.t2i_extra_configs[selfieProvider] || {}, "selfie-t2i")}</div></div>
    <div class="form-section"><h3>桌面立绘</h3>
      ${switchRow("image-realtime", "实时生成立绘", "按情绪与场景调用生图服务", system.sprite_realtime_enabled)}
      <div id="image-realtime-settings" class="${system.sprite_realtime_enabled ? "" : "is-hidden"}"><div class="field-grid provider-schema">
        ${field("image-realtime-template", "实时立绘提示词模板", system.sprite_realtime_prompt_template, { type: "textarea", wide: true, rows: 4, placeholder: "自动使用内置提示词模板" })}
        ${pathField("image-cache-dir", "实时立绘缓存目录", system.sprite_realtime_cache_dir, "directory", true, "自动使用默认缓存目录")}
      </div><div class="inline-actions"><button id="video-install" class="text-button" type="button"><i data-lucide="package-plus"></i><span>安装视频立绘支持</span></button></div></div>
    </div>`;

  $("[data-page='proactive']").innerHTML = pageHeader("主动联系", "日常生活计划、联系节奏与送达策略") + `
    <div class="form-section"><h3>联系计划</h3>
      ${switchRow("proactive-enabled", "允许主动联系", "后台生成生活与联系计划", system.proactive_contact_enabled)}
      ${switchRow("proactive-photo", "允许附带自拍", "在合适的分享时刻生成状态照片", system.proactive_photo_enabled)}
      <div id="proactive-photo-settings" class="field-grid provider-schema${system.proactive_photo_enabled ? "" : " is-hidden"}">
        ${field("proactive-photo-limit", "每日自拍上限", system.proactive_photo_daily_limit, { type: "number", min: 0, max: 12, step: 1 })}
      </div>
    </div>
    <div class="form-section"><h3>外部送达</h3>
      ${switchRow("proactive-external", "外部平台送达", "允许主动消息从配置的平台发出", system.external_delivery_enabled)}
      <div id="proactive-external-settings" class="${system.external_delivery_enabled ? "" : "is-hidden"}">
      ${switchRow("proactive-confirm", "发送前确认", "需要确认时自动回到桌面显示", system.external_delivery_requires_confirmation)}
      ${switchRow("proactive-audio", "附带语音", "外部主动消息同时发送 TTS 音频", system.external_delivery_audio_enabled)}
      <div class="field-grid provider-schema">
        ${selectField("proactive-channel", "送达渠道", system.external_delivery_channel, deliveryOptions())}
        ${field("proactive-limit", "每日外发上限", system.external_delivery_daily_limit, { type: "number", min: 1, max: 12, step: 1 })}
        ${field("proactive-quiet", "免打扰时段", system.external_delivery_quiet_hours)}
        ${selectField("proactive-chat-channel", "普通聊天渠道", system.chat_delivery_channel, deliveryOptions())}
      </div>
      </div>
    </div>`;

  $("[data-page='platforms']").innerHTML = renderPlatformSettings();
  renderCharacterPages(character);
  $("[data-page='memory']").innerHTML = renderMemorySettings();
  $("[data-page='storage']").innerHTML = renderStorageSettings();
  document.querySelector<HTMLElement>("[data-page='companion']")!.innerHTML = pageHeader("同桌模式", "让 here 陪你工作，并逐渐理解你的工作节奏") + `
    <div class="form-section"><h3>同桌</h3>
      ${switchRow("screen-context-enabled", "开启同桌模式", "理解你的工作节奏，并在确实有帮助时主动提醒或提议", Boolean(system.screen_context_enabled))}
      <div id="screen-context-settings" class="field-grid provider-schema${system.screen_context_enabled ? "" : " is-hidden"}">
        ${field("screen-context-interval", "观察间隔（秒）", Number(system.screen_context_interval_seconds) || 300, { type: "number", min: 60, max: 3600, step: 60 })}
        ${field("screen-context-display-ids", "显示器 ID", Array.isArray(system.screen_context_display_ids) ? system.screen_context_display_ids.join(", ") : "", { wide: true, placeholder: "留空表示全部显示器" })}
      </div>
    </div>`;
  bindDynamicSettings();
  showSettingsPage(activeSettingsTab);
  refreshIcons();
  applyLocale(settingsDialog);
}

function deliveryOptions(): Array<[string, string]> {
  return Object.values(state.capabilities).map((item) => [item.channel, item.label]);
}

const capabilityReasonLabels: Record<string, string> = {
  ready: "可用",
  missing_token: "缺少访问令牌",
  missing_webhook: "缺少 Webhook",
  missing_credentials: "缺少登录凭据",
  missing_config: "尚未配置",
  not_configured: "尚未配置",
  not_logged_in: "尚未登录",
  unsupported: "当前环境不支持",
  disabled: "未启用",
};

function capabilityStatus(capability: DesktopState["capabilities"][string] | undefined): string {
  if (!capability) return "尚未配置";
  if (capability.available) return "可用";
  const reason = String(capability.reason || "").trim();
  return capabilityReasonLabels[reason] || reason.replaceAll("_", " ") || "尚未配置";
}

function renderPlatformSettings(): string {
  const configs = state.messaging || {};
  const platformMeta: Array<[string, string, Array<[string, string, string]>]> = [
    ["telegram", "Telegram", [["token", "Bot Token", "password"], ["target", "接收 chat_id", "text"]]],
    ["discord", "Discord", [["bot_token", "Bot Token", "password"], ["target", "接收用户 ID", "text"]]],
    ["wechat", "WeChat", [["account_id", "账号 ID", "text"], ["base_url", "OpenClaw 地址", "text"], ["user_id", "当前登录用户 ID", "text"], ["target", "目标用户通道 ID", "text"]]],
    ["feishu", "Feishu", [["app_id", "App ID", "text"], ["app_secret", "App Secret", "password"], ["target", "接收 ID", "text"], ["receive_id_type", "接收 ID 类型", "text"]]],
    ["whatsapp", "WhatsApp", [["api_token", "API Token", "password"], ["phone_number_id", "Phone Number ID", "text"], ["api_version", "API 版本", "text"], ["target", "目标号码", "text"]]],
  ];
  return pageHeader("消息平台", "Telegram、Discord、WeChat、Feishu 与 WhatsApp") + platformMeta.map(([key, title, fields]) => {
    const config = configs[key] || {};
    const capability = state.capabilities[key];
    return `<div class="form-section platform-section" data-platform="${key}"><h3>${esc(title)} · ${esc(capabilityStatus(capability))}</h3>
      ${switchRow(`platform-${key}-enabled`, "启用", title, Boolean(config.enabled))}
      <div class="platform-details${config.enabled ? "" : " is-hidden"}"><div class="field-grid provider-schema">${fields.map(([fieldKey, label, type]) =>
        field(`platform-${key}-${fieldKey}`, label, config[fieldKey] || "", { type, placeholder: "未配置" })).join("")}</div>
      ${key === "telegram" ? '<div class="inline-actions"><button id="telegram-discover" class="text-button" type="button"><i data-lucide="scan-search"></i><span>自动识别 chat_id</span></button></div>' : ""}
      ${key === "wechat" ? `${switchRow("platform-wechat-require_context_token", "要求 context_token", "避免个人微信主动发送失败", config.require_context_token !== false)}<div class="inline-actions"><button id="wechat-login" class="text-button" type="button"><i data-lucide="qr-code"></i><span>微信扫码登录</span></button><button id="wechat-refresh" class="text-button" type="button"><i data-lucide="refresh-cw"></i><span>刷新接收方</span></button></div><div id="wechat-login-box" class="wechat-login-box is-hidden"></div><div id="wechat-status" class="inline-status"></div>` : ""}
      </div>
    </div>`;
  }).join("");
}

function profileMap(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function profileText(value: unknown, fallback = ""): string {
  if (Array.isArray(value)) return value.map(String).filter(Boolean).join("、");
  return String(value ?? fallback).trim();
}

function renderCharacterProfileEditor(character: BackendCharacter): string {
  const profile = profileMap(character.character_profile);
  const identity = profileMap(profile.identity);
  const personality = profileMap(profile.personality);
  const speech = profileMap(profile.speech);
  const relationship = profileMap(profile.relationship);
  const preferences = profileMap(profile.preferences);
  const boundaries = profileMap(profile.boundaries);
  const mbti = profileText(personality.mbti, "INFP").toUpperCase();
  const locked = character.name === "here_system";
  const profileField = (
    id: string,
    label: string,
    value: unknown,
    options: Parameters<typeof field>[3] = {},
  ): string => field(id, label, value, { ...options, readOnly: locked });
  const mbtiTypes = [
    "INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP",
  ];
  return `<div class="form-section"><h3>角色档案</h3>
    <div class="profile-subsection"><h4>基础</h4><div class="field-grid">
      ${profileField("character-profile-age", "实际年龄", Number(identity.age) || 22, { type: "number", min: 18, max: 120, step: 1 })}
      ${profileField("character-profile-birthday", "生日", profileText(identity.birthday))}
      ${profileField("character-profile-gender", "性别/身份", profileText(identity.gender, "女性"))}
      ${profileField("character-profile-occupation", "职业", profileText(identity.occupation, "自学中的程序员"))}
      ${profileField("character-profile-life-status", "生活状态", profileText(identity.life_status, "独居"))}
      ${profileField("character-profile-relationship", "与你的关系", profileText(identity.relationship_to_user, "暧昧陪伴者"))}
      ${profileField("character-profile-first-person", "第一人称", profileText(identity.first_person, "我"))}
      ${profileField("character-profile-user-address", "称呼你", profileText(identity.user_address, "你"))}
    </div></div>
    <div class="profile-subsection"><h4>性格与 MBTI</h4>
      <input id="character-profile-mbti" type="hidden" value="${esc(mbti)}">
      <div class="mbti-grid character-mbti-grid" role="radiogroup" aria-label="MBTI 类型">${mbtiTypes.map((item) => `<button type="button" data-character-mbti="${item}" class="${item === mbti ? "is-active" : ""}"${locked ? " disabled" : ""}>${item}</button>`).join("")}</div>
      <div class="field-grid">
        ${profileField("character-profile-mbti-style", "表现方式", profileText(personality.mbti_style, "典型表现"))}
        ${profileField("character-profile-traits", "性格补充", profileText(personality.custom_traits), { placeholder: "用逗号分隔多个特质" })}
        ${profileField("character-profile-flaws", "缺点补充", profileText(personality.flaws), { placeholder: "用逗号分隔" })}
        ${profileField("character-profile-contrast", "反差点", profileText(personality.contrast))}
      </div>
    </div>
    <div class="profile-subsection"><h4>说话与关系</h4><div class="field-grid">
      ${profileField("character-profile-tone", "语气", profileText(speech.tone), { placeholder: "自然、亲近、轻柔" })}
      ${profileField("character-profile-reply-length", "回复长度", profileText(speech.reply_length, "适中"))}
      ${profileField("character-profile-catchphrases", "口头禅", profileText(speech.catchphrases), { placeholder: "用逗号分隔" })}
      ${profileField("character-profile-stage", "关系阶段", profileText(relationship.stage, "暧昧"))}
      ${profileField("character-profile-trust", "信任触发", profileText(relationship.trust_triggers), { placeholder: "用逗号分隔" })}
      ${profileField("character-profile-sadness", "失落触发", profileText(relationship.sadness_triggers), { placeholder: "用逗号分隔" })}
    </div></div>
    <div class="profile-subsection"><h4>喜好与边界</h4><div class="field-grid">
      ${profileField("character-profile-likes", "喜欢", profileText(preferences.likes), { placeholder: "用逗号分隔" })}
      ${profileField("character-profile-dislikes", "讨厌", profileText(preferences.dislikes), { placeholder: "用逗号分隔" })}
      ${profileField("character-profile-hobbies", "爱好", profileText(preferences.hobbies), { placeholder: "用逗号分隔" })}
      ${profileField("character-profile-boundary", "亲密边界", profileText(boundaries.intimacy_level, "轻度亲密"))}
      ${profileField("character-profile-boundary-notes", "边界补充", profileText(boundaries.notes), { type: "textarea", wide: true, rows: 3 })}
    </div></div>
    <div class="inline-actions">${locked ? "" : '<button id="character-regenerate-setting" class="text-button" type="button"><i data-lucide="refresh-cw"></i><span>根据档案重新生成设定文本</span></button>'}</div>
  </div>`;
}

function characterProfileFromSettings(existing: Record<string, unknown>): Record<string, unknown> {
  const profile = clone(profileMap(existing));
  profile.identity = {
    ...profileMap(profile.identity),
    age: Math.max(18, numeric("character-profile-age", 22)),
    birthday: value("character-profile-birthday"),
    gender: value("character-profile-gender"),
    occupation: value("character-profile-occupation"),
    life_status: value("character-profile-life-status"),
    relationship_to_user: value("character-profile-relationship"),
    first_person: value("character-profile-first-person"),
    user_address: value("character-profile-user-address"),
  };
  profile.personality = {
    ...profileMap(profile.personality),
    mbti: value("character-profile-mbti") || "INFP",
    mbti_style: value("character-profile-mbti-style"),
    custom_traits: csvValues(value("character-profile-traits")),
    flaws: csvValues(value("character-profile-flaws")),
    contrast: value("character-profile-contrast"),
  };
  profile.speech = {
    ...profileMap(profile.speech),
    tone: csvValues(value("character-profile-tone")),
    reply_length: value("character-profile-reply-length"),
    catchphrases: csvValues(value("character-profile-catchphrases")),
  };
  profile.relationship = {
    ...profileMap(profile.relationship),
    stage: value("character-profile-stage"),
    trust_triggers: csvValues(value("character-profile-trust")),
    sadness_triggers: csvValues(value("character-profile-sadness")),
  };
  profile.preferences = {
    ...profileMap(profile.preferences),
    likes: csvValues(value("character-profile-likes")),
    dislikes: csvValues(value("character-profile-dislikes")),
    hobbies: csvValues(value("character-profile-hobbies")),
  };
  profile.boundaries = {
    ...profileMap(profile.boundaries),
    adult: true,
    intimacy_level: value("character-profile-boundary"),
    notes: value("character-profile-boundary-notes"),
  };
  return profile;
}

function renderCharacterSettings(character: BackendCharacter): string {
  const locked = character.name === "here_system";
  return pageHeader("角色", "人设、视觉身份与语音表现") + `
    <div class="form-section"><h3>当前角色</h3><div class="field-grid">
      ${selectField("character-select", "角色", character.name, state.config.characters.map((item) => [item.name, item.name]))}
      ${field("character-name", "名称", character.name, { readOnly: locked })}
      ${field("character-color", "对话颜色", character.color, { type: "color" })}
      ${field("character-prefix", "资源前缀", character.sprite_prefix)}
      ${field("character-scale", "立绘缩放", character.sprite_scale, { type: "number", min: 0.15, max: 3, step: 0.05 })}
      ${field("character-speed", "语速倍率", character.speech_speed, { type: "number", min: 0.5, max: 2, step: 0.05 })}
      ${field("character-volume", "语音音量", character.speech_volume, { type: "number", min: 0, max: 2, step: 0.05 })}
      ${pathField("character-reference", "视觉参考图", character.visual_reference_image, "reference", true, "未设置")}
      ${field("character-visual", "视觉身份", character.visual_identity, { type: "textarea", wide: true, rows: 4, readOnly: locked })}
      ${field("character-setting", "角色设定", character.character_setting, { type: "textarea", wide: true, rows: 8, readOnly: locked })}
      <input id="character-profile" type="hidden" value="${esc(JSON.stringify(character.character_profile))}">
      <input id="character-pronunciation" type="hidden" value="${esc(JSON.stringify(character.pronunciation_map))}">
    </div><div class="inline-actions">
      <button id="character-new" class="text-button" type="button"><i data-lucide="user-plus"></i><span>新建</span></button>
      <button id="character-delete" class="danger-button" type="button"><i data-lucide="trash-2"></i><span>删除</span></button>
    </div></div>${renderCharacterProfileEditor(character)}`;
}

const coreSpriteStates = [
  { name: "neutral", label: "平静", group: "core_emotion" },
  { name: "happy", label: "开心", group: "core_emotion" },
  { name: "thinking", label: "思考", group: "core_emotion" },
  { name: "surprised", label: "惊讶", group: "core_emotion" },
  { name: "sad", label: "难过", group: "core_emotion" },
  { name: "angry", label: "生气", group: "core_emotion" },
] as const;

const welcomeSpriteState = { name: "welcome", label: "欢迎动画", group: "system_optional_emotion" } as const;

const spriteStateLabels: Record<string, string> = {
  video_call: "视频通话",
  ...Object.fromEntries(coreSpriteStates.map((item) => [item.name, item.label])),
  welcome: "欢迎动画",
  working: "执行中",
  reviewing: "检查中",
  moving_right: "向右移动",
  moving_left: "向左移动",
};

const fixedSpriteStates = [...coreSpriteStates, welcomeSpriteState] as const;

function spriteStateName(sprite: Record<string, unknown>, index: number): string {
  return String(sprite.state_name || sprite.source_state || `custom_${index + 1}`).trim();
}

function spriteStateLabel(stateName: string): string {
  return spriteStateLabels[stateName] || stateName || "未命名状态";
}

function renderSpriteEditor(sprite: Record<string, unknown>, index: number, fixed = false): string {
  const stateName = spriteStateName(sprite, index);
  const stateLabel = spriteStateLabel(stateName);
  const frameCount = Array.isArray(sprite.frames) && sprite.frames.length ? sprite.frames.length : Number(sprite.frame_count || 1);
  const sourcePath = String((Array.isArray(sprite.frames) && sprite.frames[0]) || sprite.path || sprite.spritesheet_path || "");
  const video = isVideoSprite({ path: sourcePath });
  const sourceName = sourcePath.split(/[\\/]/).pop() || "未命名素材";
  const fixedMeta = fixedSpriteStates.find((item) => item.name === stateName);
  const timingField = video ? `<input id="sprite-interval-${index}" type="hidden" value="120">`
    : field(`sprite-interval-${index}`, "帧间隔 ms", sprite.frame_interval_ms || 120, { type: "number", min: 20, max: 10000, step: 10 });
  const stateGroup = String(sprite.state_group || fixedMeta?.group || "custom");
  return `<article class="sprite-editor" data-sprite-editor="${index}">
    <div class="sprite-preview">
      ${video ? `<video class="is-hidden" data-sprite-preview="${index}" muted playsinline preload="auto" aria-label="${esc(stateLabel)}预览"></video>` : `<img class="is-hidden" data-sprite-preview="${index}" alt="${esc(stateLabel)}预览">`}
      <span class="sprite-preview-empty" data-sprite-preview-empty="${index}">正在加载预览</span>
      <span class="sprite-frame-badge">${esc(video ? "视频" : frameCount > 1 ? `${frameCount} 帧` : "静态")}</span>
    </div>
    <div class="sprite-editor-content">
      <div class="sprite-editor-heading"><div><strong>${esc(stateLabel)}</strong><small>${esc(stateName)}</small></div><span>${esc(sourceName)}</span></div>
      ${fixed
        ? `<input id="sprite-state-${index}" type="hidden" value="${esc(stateName)}"><input id="sprite-group-${index}" type="hidden" value="${esc(stateGroup)}"><div class="sprite-editor-fields fixed-state-fields">${timingField}</div>`
        : `<div class="sprite-editor-fields">${field(`sprite-state-${index}`, "状态名", stateName)}${selectField(`sprite-group-${index}`, "状态分组", stateGroup, [["system_optional_emotion", "系统情绪"], ["custom", "自定义"], ["mouse_event", "鼠标事件"]])}${field(`sprite-interval-${index}`, "帧间隔 ms", sprite.frame_interval_ms || 120, { type: "number", min: 20, max: 10000, step: 10 })}</div>`}
      <div class="inline-actions sprite-editor-actions">
        <button class="text-button" data-save-sprite="${index}" type="button"><i data-lucide="save"></i><span>保存设置</span></button>
        <button class="text-button" data-replace-sprite="${index}" type="button"><i data-lucide="replace"></i><span>替换素材</span></button>
        <button class="danger-button" data-delete-sprite="${index}" type="button"><i data-lucide="trash-2"></i><span>清空</span></button>
      </div>
    </div>
  </article>`;
}

function renderEmptySpriteSlot(name: string, label: string, group: string): string {
  return `<article class="sprite-editor sprite-editor-empty" data-empty-sprite-state="${esc(name)}">
    <div class="sprite-preview">
      <span class="sprite-preview-empty">未设置</span>
      <span class="sprite-frame-badge">空</span>
    </div>
    <div class="sprite-editor-content">
      <div class="sprite-editor-heading"><div><strong>${esc(label)}</strong><small>${esc(name)}</small></div><span>当前角色未配置</span></div>
      <p class="sprite-empty-copy">可以添加静态图片、图片序列、GIF 或视频。</p>
      <div class="inline-actions sprite-editor-actions">
        <button class="text-button" data-add-sprite-state="${esc(name)}" data-state-group="${esc(group)}" type="button"><i data-lucide="plus"></i><span>添加素材</span></button>
      </div>
    </div>
  </article>`;
}

function renderSpriteSettings(character: BackendCharacter): string {
  const fixedIndexes = new Set<number>();
  const renderFixedSlots = (states: readonly { name: string; label: string; group: string }[]) => states.map((fixedState) => {
    const index = character.sprites.findIndex((sprite, spriteIndex) => !fixedIndexes.has(spriteIndex) && spriteStateName(sprite, spriteIndex) === fixedState.name);
    if (index < 0) return renderEmptySpriteSlot(fixedState.name, fixedState.label, fixedState.group);
    fixedIndexes.add(index);
    return renderSpriteEditor(character.sprites[index], index, true);
  }).join("");
  const coreSlots = renderFixedSlots(coreSpriteStates);
  const welcomeSlot = renderFixedSlots([welcomeSpriteState]);
  const extraSprites = character.sprites
    .map((sprite, index) => ({ sprite, index }))
    .filter(({ sprite, index }) => !fixedIndexes.has(index) && spriteStateName(sprite, index) !== "video_call")
    .map(({ sprite, index }) => renderSpriteEditor(sprite, index))
    .join("");
  return pageHeader("状态立绘", "按角色管理情绪状态、静态图与动画资源") + `
    <div class="form-section"><h3>当前角色</h3><div class="field-grid">
      ${selectField("sprite-character-select", "角色", character.name, state.config.characters.map((item) => [item.name, item.name]))}
    </div></div>
    <div class="form-section"><h3>核心情绪</h3><div class="sprite-editor-list">${coreSlots}</div></div>
    <div class="form-section"><h3>欢迎动画</h3><div class="sprite-editor-list">${welcomeSlot}</div></div>
    ${extraSprites ? `<div class="form-section"><h3>其他状态</h3><div class="sprite-editor-list">${extraSprites}</div></div>` : ""}
    <div class="form-section"><h3>新增自定义状态</h3><div class="field-grid">
      <input id="character-state-name" type="hidden" value="custom">
      ${field("character-custom-state", "状态名", "", { placeholder: "例如：sleeping" })}
      ${selectField("character-state-group", "状态分组", "custom", [["system_optional_emotion", "系统情绪"], ["custom", "自定义"], ["mouse_event", "鼠标事件"]])}
      ${field("character-frame-interval", "帧间隔 ms", 120, { type: "number", min: 20, max: 10000, step: 10 })}
    </div><div class="inline-actions">
      <button id="character-import-state" class="text-button" type="button"><i data-lucide="film"></i><span>添加自定义素材</span></button>
      <button id="character-upload" class="text-button" type="button"><i data-lucide="images"></i><span>批量添加静态立绘</span></button>
    </div></div>
    <input id="character-emotions" type="hidden" value="${esc(character.emotion_tags)}">`;
}

function renderCharacterPages(character = activeCharacter()): void {
  $("[data-page='character']").innerHTML = renderCharacterSettings(character);
  $("[data-page='sprites']").innerHTML = renderSpriteSettings(character);
  const callIndex = character.sprites.findIndex((sprite) => sprite.state_name === "video_call");
  $("[data-page='video-call']").innerHTML = pageHeader("视频通话", "") + `
    <div class="form-section"><div class="field-grid">
      ${selectField("video-call-character-select", "角色", character.name, state.config.characters.map((item) => [item.name, item.name]))}
    </div></div>
    <div class="form-section"><h3>通话视频</h3>
      ${callIndex >= 0 ? renderSpriteEditor(character.sprites[callIndex], callIndex, true)
        : `<div class="inline-actions"><button class="text-button" data-add-sprite-state="video_call" data-state-group="custom" type="button"><i data-lucide="video"></i><span>添加视频</span></button></div>`}
    </div>`;
}

function spriteEditorValues(index: number): { stateName: string; stateGroup: string; frameIntervalMs: number } {
  const stateName = value(`sprite-state-${index}`);
  if (!stateName) throw new Error("状态名不能为空。");
  return {
    stateName,
    stateGroup: value(`sprite-group-${index}`) || "custom",
    frameIntervalMs: numeric(`sprite-interval-${index}`, 120),
  };
}

function commitSpriteDrafts(character = activeCharacter()): void {
  const editors = document.querySelectorAll<HTMLElement>("[data-sprite-editor]");
  if (!editors.length) return;
  const stateNames = new Set<string>();
  editors.forEach((editor) => {
    const index = Number(editor.dataset.spriteEditor);
    const sprite = character.sprites[index];
    if (!sprite) return;
    const metadata = spriteEditorValues(index);
    if (stateNames.has(metadata.stateName)) throw new Error(`状态名重复：${metadata.stateName}`);
    stateNames.add(metadata.stateName);
    sprite.state_name = metadata.stateName;
    sprite.state_group = metadata.stateGroup;
    sprite.frame_interval_ms = metadata.frameIntervalMs;
    sprite.fps = 0;
  });
}

async function hydrateSpritePreviews(): Promise<void> {
  const characterName = state.active_character_name;
  try {
    const resolved = await api.backendCall<{ sprites: ResolvedSprite[] }>("resolve_assets", { character_name: characterName });
    if (state.active_character_name !== characterName) return;
    for (const sprite of resolved.sprites || []) {
      const image = document.querySelector<HTMLImageElement | HTMLVideoElement>(`[data-sprite-preview='${sprite.index}']`);
      const empty = document.querySelector<HTMLElement>(`[data-sprite-preview-empty='${sprite.index}']`);
      if (!image || !empty) continue;
      const previewPath = sprite.frames?.[0] || sprite.path || sprite.spritesheet_path || "";
      if (!previewPath) { empty.textContent = "无可预览素材"; continue; }
      image.addEventListener(image instanceof HTMLVideoElement ? "loadeddata" : "load", () => {
        image.classList.remove("is-hidden");
        empty.classList.add("is-hidden");
      }, { once: true });
      image.addEventListener("error", () => { empty.textContent = "预览加载失败"; }, { once: true });
      image.src = await localUrl(previewPath);
    }
  } catch {
    document.querySelectorAll<HTMLElement>("[data-sprite-preview-empty]").forEach((empty) => { empty.textContent = "预览加载失败"; });
  }
}

async function saveSpriteEditor(index: number): Promise<void> {
  const status = $("#settings-status");
  try {
    const metadata = spriteEditorValues(index);
    await persistCharacterDraft();
    renderSettings();
    await applyState();
    $("#settings-status").textContent = `${spriteStateLabel(metadata.stateName)}设置已保存`;
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function replaceCharacterSprite(index: number): Promise<void> {
  const paths = await api.chooseFiles("character_assets");
  if (!paths.length) return;
  const status = $("#settings-status");
  try {
    const metadata = spriteEditorValues(index);
    await persistCharacterDraft();
    state = await api.backendCall<DesktopState>("import_character_state_assets", {
      character_name: state.active_character_name,
      sprite_index: index,
      state_name: metadata.stateName,
      state_group: metadata.stateGroup,
      frame_interval_ms: metadata.frameIntervalMs,
      paths,
    }, 10 * 60_000);
    renderSettings();
    await applyState();
    $("#settings-status").textContent = `${spriteStateLabel(metadata.stateName)}素材已替换`;
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : String(error);
  }
}

function renderMemorySettings(): string {
  return pageHeader("记忆", `与 ${state.active_character_name} 隔离保存的长期内容`) + `
    <div class="form-section"><h3>角色记忆</h3>
      ${field("memory-character", "MEMORY.md", state.memory.character.join("\n---\n"), { type: "textarea", wide: true, rows: 10, placeholder: "暂无角色记忆" })}
    </div>
    <div class="form-section"><h3>你的档案</h3>
      ${field("memory-user", "长期印象", state.memory.user.join("\n---\n"), { type: "textarea", wide: true, rows: 8, placeholder: "暂时还没有记录" })}
    </div>`;
}

function renderStorageSettings(): string {
  return pageHeader("存储", "角色资产、长期记忆与旧版数据导入") + `
    <div class="form-section"><h3>位置</h3><div class="field-grid">
      ${pathField("storage-memory", "角色记忆目录", state.storage?.character_memory_dir || "", "directory", true, "使用默认记忆目录")}
      ${pathField("storage-assets", "角色资产目录", state.storage?.character_assets_dir || "", "directory", true, "使用默认角色资产目录")}
      ${field("storage-root", "Electron 数据目录", state.paths.root || "", { wide: true })}
    </div>
      ${switchRow("storage-copy-memory", "保存时复制现有角色记忆到新目录", "", true)}
      ${switchRow("storage-copy-assets", "保存时复制现有角色动画素材到新目录，并更新角色配置里的素材路径", "", true)}
    </div>
    <div class="form-section"><h3>旧版 here</h3><div class="inline-actions">
      <button id="import-legacy" class="text-button" type="button"><i data-lucide="import"></i><span>导入旧版数据</span></button>
    </div></div>`;
}

function setSettingsSectionVisible(selector: string, visible: boolean): void {
  document.querySelector<HTMLElement>(selector)?.classList.toggle("is-hidden", !visible);
}

function bindDynamicSettings(): void {
  const ttsSelect = document.querySelector<HTMLSelectElement>("#voice-tts-provider");
  ttsSelect?.addEventListener("change", () => {
    setSettingsSectionVisible("#tts-provider-settings", ttsSelect.value !== "none");
    $("#tts-schema").innerHTML = schemaFields("tts", ttsSelect.value, state.config.api_config.tts_extra_configs[ttsSelect.value] || {});
    refreshIcons();
    applyLocale($("#tts-provider-settings"));
  });
  const asrSelect = document.querySelector<HTMLSelectElement>("#voice-asr-provider");
  asrSelect?.addEventListener("change", () => {
    $("#asr-schema").innerHTML = schemaFields("asr", asrSelect.value, state.config.api_config.asr_extra_configs[asrSelect.value] || {});
    $("#asr-whisper-fields").classList.toggle("is-hidden", asrSelect.value === "vosk");
    refreshIcons();
    applyLocale($("#asr-schema"));
  });
  const t2iSelect = document.querySelector<HTMLSelectElement>("#image-provider");
  t2iSelect?.addEventListener("change", () => {
    $("#t2i-schema").innerHTML = schemaFields("t2i", t2iSelect.value, state.config.api_config.t2i_extra_configs[t2iSelect.value] || {});
    const selfieSelect = document.querySelector<HTMLSelectElement>("#image-selfie-provider");
    if (selfieSelect?.value === "") {
      $("#selfie-schema").innerHTML = schemaFields(
        "t2i",
        t2iSelect.value,
        state.config.api_config.t2i_extra_configs[t2iSelect.value] || {},
        "selfie-t2i",
      );
    }
    const apiField = document.querySelector<HTMLElement>("#image-api-url")?.closest(".field");
    apiField?.classList.toggle("is-hidden", t2iSelect.value !== "image-api");
    refreshIcons();
    applyLocale($("#t2i-schema"));
  });
  const selfieSelect = document.querySelector<HTMLSelectElement>("#image-selfie-provider");
  selfieSelect?.addEventListener("change", () => {
    const provider = selfieSelect.value || document.querySelector<HTMLSelectElement>("#image-provider")?.value || "image-api";
    $("#selfie-schema").innerHTML = schemaFields(
      "t2i",
      provider,
      state.config.api_config.t2i_extra_configs[provider] || {},
      "selfie-t2i",
    );
    refreshIcons();
    applyLocale($("#selfie-schema"));
  });
  document.querySelector<HTMLSelectElement>("#agent-backend")?.addEventListener("change", (event) => {
    const backend = (event.currentTarget as HTMLSelectElement).value;
    setSettingsSectionVisible("#agent-internal-settings", backend !== "hermes-agent");
    setSettingsSectionVisible("#agent-fetch-models", backend !== "hermes-agent");
    setSettingsSectionVisible("#hermes-install", backend !== "internal-agent");
  });
  document.querySelector<HTMLInputElement>("#image-realtime")?.addEventListener("change", (event) => {
    setSettingsSectionVisible("#image-realtime-settings", (event.currentTarget as HTMLInputElement).checked);
  });
  document.querySelector<HTMLInputElement>("#proactive-photo")?.addEventListener("change", (event) => {
    setSettingsSectionVisible("#proactive-photo-settings", (event.currentTarget as HTMLInputElement).checked);
  });
  document.querySelector<HTMLInputElement>("#screen-context-enabled")?.addEventListener("change", (event) => {
    setSettingsSectionVisible("#screen-context-settings", (event.currentTarget as HTMLInputElement).checked);
  });
  document.querySelector<HTMLInputElement>("#proactive-external")?.addEventListener("change", (event) => {
    setSettingsSectionVisible("#proactive-external-settings", (event.currentTarget as HTMLInputElement).checked);
  });
  ["telegram", "discord", "wechat", "feishu", "whatsapp"].forEach((platform) => {
    document.querySelector<HTMLInputElement>(`#platform-${platform}-enabled`)?.addEventListener("change", (event) => {
      setSettingsSectionVisible(`[data-platform='${platform}'] .platform-details`, (event.currentTarget as HTMLInputElement).checked);
    });
  });
  document.querySelector<HTMLSelectElement>("#character-state-name")?.addEventListener("change", (event) => {
    const customStateField = document.querySelector<HTMLElement>("#character-custom-state")?.closest<HTMLElement>(".field");
    customStateField?.classList.toggle("is-hidden", (event.currentTarget as HTMLSelectElement).value !== "custom");
  });
  bindCharacterSettings();
  document.querySelectorAll<HTMLElement>(".settings-page:not([data-page='character']):not([data-page='sprites']) [data-file-picker]").forEach((button) => button.addEventListener("click", choosePathForField));
  document.querySelector("#import-legacy")?.addEventListener("click", importLegacy);
  document.querySelector("#wechat-login")?.addEventListener("click", startWechatLogin);
  document.querySelector("#wechat-refresh")?.addEventListener("click", refreshWechatStatus);
  document.querySelector("#telegram-discover")?.addEventListener("click", discoverTelegramChat);
  document.querySelector("#agent-fetch-models")?.addEventListener("click", fetchAgentModels);
  document.querySelector("#hermes-install")?.addEventListener("click", () => installFeature("hermes"));
  document.querySelector("#asr-install")?.addEventListener("click", () => installFeature(value("voice-asr-provider")));
  document.querySelector("#asr-prepare")?.addEventListener("click", prepareAsr);
  document.querySelector("#video-install")?.addEventListener("click", () => installFeature("video"));
  void refreshDependencyStatus();
  if (activeSettingsTab === "platforms") void refreshWechatStatus();
}

function bindCharacterSettings(): void {
  document.querySelectorAll<HTMLSelectElement>("#character-select, #sprite-character-select, #video-call-character-select").forEach((select) => select.addEventListener("change", (event) => {
    const selectedName = (event.target as HTMLSelectElement).value;
    try {
      commitCharacterDraft();
      state.active_character_name = selectedName;
      state.config.system_config.active_character_name = selectedName;
      renderCharacterPages();
      bindCharacterSettings();
      refreshIcons();
      applyLocale(settingsDialog);
    } catch (error) {
      select.value = state.active_character_name;
      $("#settings-status").textContent = error instanceof Error ? error.message : String(error);
    }
  }));
  document.querySelector("#character-new")?.addEventListener("click", openCreateCharacter);
  document.querySelector("#character-delete")?.addEventListener("click", deleteCharacter);
  document.querySelector("#character-upload")?.addEventListener("click", uploadCharacterSprites);
  document.querySelector("#character-import-state")?.addEventListener("click", importCharacterStateAssets);
  document.querySelectorAll<HTMLElement>("[data-character-mbti]").forEach((button) => button.addEventListener("click", () => {
    const mbti = String(button.dataset.characterMbti || "INFP");
    const input = document.querySelector<HTMLInputElement>("#character-profile-mbti");
    if (input) input.value = mbti;
    document.querySelectorAll<HTMLElement>("[data-character-mbti]").forEach((item) => item.classList.toggle("is-active", item === button));
  }));
  document.querySelector("#character-regenerate-setting")?.addEventListener("click", () => {
    const character = activeCharacter();
    const setting = document.querySelector<HTMLTextAreaElement>("#character-setting");
    if (setting) setting.value = buildCharacterSettingText(character.name, characterProfileFromSettings(character.character_profile));
  });
  document.querySelectorAll<HTMLElement>("[data-page='character'] [data-file-picker], [data-page='sprites'] [data-file-picker]").forEach((button) => button.addEventListener("click", choosePathForField));
  document.querySelectorAll<HTMLElement>("[data-save-sprite]").forEach((button) => button.addEventListener("click", () => {
    void saveSpriteEditor(Number(button.dataset.saveSprite));
  }));
  document.querySelectorAll<HTMLElement>("[data-replace-sprite]").forEach((button) => button.addEventListener("click", () => {
    void replaceCharacterSprite(Number(button.dataset.replaceSprite));
  }));
  document.querySelectorAll<HTMLElement>("[data-add-sprite-state]").forEach((button) => button.addEventListener("click", () => {
    void importCharacterStateAssetsFor(
      String(button.dataset.addSpriteState || ""),
      String(button.dataset.stateGroup || "core_emotion"),
      120,
    );
  }));
  document.querySelectorAll<HTMLElement>("[data-delete-sprite]").forEach((button) => button.addEventListener("click", deleteCharacterSprite));
  void hydrateSpritePreviews();
}

async function choosePathForField(event: Event): Promise<void> {
  const button = event.currentTarget as HTMLElement;
  const kind = button.dataset.filePicker as Parameters<HereDesktopApi["chooseFiles"]>[0];
  const target = button.dataset.pickerTarget;
  if (!kind || !target) return;
  const paths = await api.chooseFiles(kind);
  const input = document.querySelector<HTMLInputElement>(`#${CSS.escape(target)}`);
  if (input && paths[0]) input.value = paths[0];
}

async function fetchAgentModels(): Promise<void> {
  const status = $("#settings-status");
  status.textContent = "正在获取模型…";
  try {
    const response = await api.backendCall<{ models: string[] }>("list_models", {
      base_url: value("agent-base-url"),
      api_key: value("agent-api-key"),
    }, 60_000);
    const select = $("#agent-model-list") as HTMLSelectElement;
    select.innerHTML = response.models.map((model) => `<option value="${esc(model)}">${esc(model)}</option>`).join("");
    select.classList.toggle("is-hidden", response.models.length === 0);
    select.onchange = () => { (document.querySelector("#agent-model") as HTMLInputElement).value = select.value; };
    status.textContent = response.models.length ? `获取到 ${response.models.length} 个模型` : "没有返回模型";
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function refreshDependencyStatus(): Promise<void> {
  try {
    dependencyStatus = await api.backendCall<Record<string, unknown>>("dependency_status", {
      model_path: value("extra-asr-model_path"),
    });
    const provider = value("voice-asr-provider");
    const asr = (dependencyStatus.asr as Record<string, { missing?: string[]; ready?: boolean }> | undefined)?.[provider];
    const label = document.querySelector<HTMLElement>("#asr-dependency-status");
    if (label) label.textContent = asr?.ready ? "已准备" : asr?.missing?.length ? `缺少：${asr.missing.join("、")}` : "需要检查模型";
  } catch {
    dependencyStatus = {};
  }
}

async function installFeature(feature: string): Promise<void> {
  const status = $("#settings-status");
  status.textContent = `正在安装 ${feature}，请稍候…`;
  try {
    dependencyStatus = await api.backendCall<Record<string, unknown>>("install_dependencies", { feature }, 30 * 60_000);
    status.textContent = `${feature} 依赖已安装`;
    await refreshDependencyStatus();
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function prepareAsr(): Promise<void> {
  const status = $("#settings-status");
  status.textContent = "正在检查 ASR 模型…";
  try {
    const result = await api.backendCall<Record<string, unknown>>("prepare_asr", {
      provider: value("voice-asr-provider"),
      model: value("voice-whisper-model"),
      device: value("voice-whisper-device"),
      compute_type: value("voice-whisper-compute"),
      model_path: value("extra-asr-model_path"),
    }, 30 * 60_000);
    status.textContent = `${result.provider || "ASR"} 已准备`;
    await refreshDependencyStatus();
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function discoverTelegramChat(): Promise<void> {
  const status = $("#settings-status");
  status.textContent = "请现在给 Telegram bot 发送一条私聊消息…";
  try {
    const result = await api.backendCall<Record<string, unknown>>("telegram_discover", {
      token: value("platform-telegram-token"),
    }, 60_000);
    if (result.chat_id) {
      (document.querySelector("#platform-telegram-target") as HTMLInputElement).value = String(result.chat_id);
      status.textContent = `已识别：${result.description || result.chat_id}`;
    } else status.textContent = `未识别到私聊：${result.reason || "unknown"}`;
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function refreshWechatStatus(): Promise<void> {
  const box = document.querySelector<HTMLElement>("#wechat-status");
  if (!box) return;
  try {
    const result = await api.backendCall<{ accounts: Array<{ account_id: string; base_url: string; user_id: string; recipients: string[] }> }>("wechat_status");
    if (!result.accounts.length) { box.textContent = "当前没有已登录的微信账号"; return; }
    const account = result.accounts[0];
    const assign = (id: string, text: string) => {
      const input = document.querySelector<HTMLInputElement>(`#${id}`);
      if (input && !input.value) input.value = text;
    };
    assign("platform-wechat-account_id", account.account_id);
    assign("platform-wechat-base_url", account.base_url);
    assign("platform-wechat-user_id", account.user_id);
    if (account.recipients.length === 1) assign("platform-wechat-target", account.recipients[0]);
    box.textContent = `登录账号：${account.account_id}；已缓存接收方：${account.recipients.join("、") || "暂无"}`;
  } catch (error) {
    box.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function importCharacterStateAssets(): Promise<void> {
  const selected = value("character-state-name");
  const stateName = selected === "custom" ? value("character-custom-state") : selected;
  if (!stateName) {
    $("#settings-status").textContent = "请输入自定义状态名。";
    return;
  }
  await importCharacterStateAssetsFor(
    stateName,
    value("character-state-group") || "custom",
    numeric("character-frame-interval", 120),
  );
}

async function importCharacterStateAssetsFor(stateName: string, stateGroup: string, frameIntervalMs: number): Promise<void> {
  const paths = await api.chooseFiles("character_assets");
  if (!paths.length) return;
  const status = $("#settings-status");
  try {
    await persistCharacterDraft();
    state = await api.backendCall<DesktopState>("import_character_state_assets", {
      character_name: state.active_character_name,
      state_name: stateName,
      state_group: stateGroup,
      frame_interval_ms: frameIntervalMs,
      paths,
    }, 10 * 60_000);
    status.textContent = `${spriteStateLabel(stateName)}素材已添加`;
    renderSettings();
    await applyState();
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function deleteCharacterSprite(event: Event): Promise<void> {
  const index = Number((event.currentTarget as HTMLElement).dataset.deleteSprite);
  const sprite = activeCharacter().sprites[index];
  const stateLabel = sprite ? spriteStateLabel(spriteStateName(sprite, index)) : "该状态";
  if (!Number.isInteger(index) || !window.confirm(`清空“${stateLabel}”的素材？`)) return;
  try {
    state = await api.backendCall<DesktopState>("delete_character_sprite", {
      character_name: activeCharacter().name,
      index,
    }, 60_000);
    renderSettings();
    await applyState();
  } catch (error) {
    $("#settings-status").textContent = error instanceof Error ? error.message : String(error);
  }
}

function value(id: string): string {
  return (document.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(`#${id}`)?.value || "").trim();
}
function checked(id: string): boolean {
  return Boolean(document.querySelector<HTMLInputElement>(`#${id}`)?.checked);
}
function numeric(id: string, fallback: number): number {
  const parsed = Number(value(id));
  return Number.isFinite(parsed) ? parsed : fallback;
}
function parseJson<T>(id: string, fallback: T): T {
  const raw = value(id);
  if (!raw) return fallback;
  try { return JSON.parse(raw) as T; }
  catch { throw new Error(`${document.querySelector(`label:has(#${id}) span`)?.textContent || id} 不是有效 JSON。`); }
}

function collectSchema(
  kind: "tts" | "asr" | "t2i",
  provider: string,
  existing: Record<string, unknown>,
  idPrefix: string = kind,
): Record<string, unknown> {
  const output = { ...existing };
  const schema = state.adapter_schemas[kind]?.[provider] || {};
  for (const [key, config] of Object.entries(schema)) {
    const element = document.querySelector<HTMLInputElement | HTMLSelectElement>(`#extra-${idPrefix}-${CSS.escape(key)}`);
    if (!element) continue;
    const type = String((config as Record<string, unknown>).type || "str");
    output[key] = element instanceof HTMLInputElement && element.type === "checkbox"
      ? element.checked
      : ["int", "float", "number"].includes(type) ? Number(element.value) : element.value;
  }
  return output;
}

async function saveSettings(): Promise<void> {
  const status = $("#settings-status") as HTMLElement;
  status.textContent = "正在保存…";
  try {
    commitSpriteDrafts();
    const apiConfig = clone(state.config.api_config);
    const system = clone(state.config.system_config);
    const characters = clone(state.config.characters);
    const originalCharacterName = activeCharacter().name;
    apiConfig.agent_backend = value("agent-backend");
    apiConfig.internal_agent_provider = value("agent-provider");
    apiConfig.internal_agent_model = value("agent-model");
    apiConfig.internal_agent_base_url = value("agent-base-url");
    apiConfig.internal_agent_api_key = value("agent-api-key");
    apiConfig.hermes_streaming = checked("agent-stream");
    apiConfig.hermes_use_internal_memory = checked("agent-memory");
    apiConfig.hermes_disable_native_memory = checked("agent-native-memory");
    apiConfig.tts_provider = value("voice-tts-provider");
    apiConfig.tts_speed = numeric("voice-tts-speed", apiConfig.tts_speed);
    apiConfig.tts_split_enabled = checked("voice-split");
    apiConfig.tts_max_sentence_length = numeric("voice-split-length", apiConfig.tts_max_sentence_length);
    apiConfig.t2i_provider = value("image-provider");
    if (apiConfig.t2i_provider === "image-api" && value("image-api-url")) {
      apiConfig.t2i_api_url = value("image-api-url");
    }
    const selfieProviderSelection = value("image-selfie-provider");
    const selfieProvider = selfieProviderSelection || apiConfig.t2i_provider || "image-api";
    apiConfig.selfie_provider = selfieProviderSelection;
    apiConfig.selfie_extra_configs = parseJson("image-selfie-extra", {});
    apiConfig.selfie_extra_configs.width = numeric("image-selfie-width", Number(apiConfig.selfie_extra_configs.width) || 1024);
    apiConfig.selfie_extra_configs.height = numeric("image-selfie-height", Number(apiConfig.selfie_extra_configs.height) || 1024);
    apiConfig.tts_extra_configs[apiConfig.tts_provider] = collectSchema("tts", apiConfig.tts_provider, apiConfig.tts_extra_configs[apiConfig.tts_provider] || {});
    system.asr_provider = value("voice-asr-provider").replaceAll("_", "-");
    apiConfig.asr_extra_configs[value("voice-asr-provider")] = collectSchema("asr", value("voice-asr-provider"), apiConfig.asr_extra_configs[value("voice-asr-provider")] || {});
    apiConfig.t2i_extra_configs[apiConfig.t2i_provider] = collectSchema("t2i", apiConfig.t2i_provider, apiConfig.t2i_extra_configs[apiConfig.t2i_provider] || {});
    apiConfig.t2i_extra_configs[selfieProvider] = collectSchema(
      "t2i",
      selfieProvider,
      apiConfig.t2i_extra_configs[selfieProvider] || {},
      "selfie-t2i",
    );
    if (apiConfig.t2i_provider === "image-api") {
      apiConfig.t2i_extra_configs["image-api"] = {
        ...apiConfig.t2i_extra_configs["image-api"],
        api_url: apiConfig.t2i_api_url,
      };
    }

    system.ui_language = value("general-language");
    system.base_font_size_px = numeric("general-font-size", system.base_font_size_px);
    system.dialog_box_width_pct = numeric("general-dialog-width", system.dialog_box_width_pct);
    system.dialog_box_height_pct = numeric("general-dialog-height", system.dialog_box_height_pct);
    system.dialog_box_collapsed = !checked("general-dialog");
    system.process_hint_collapsed = !checked("general-process");
    system.input_bar_collapsed = !checked("general-input");
    system.background_path = value("general-background");
    system.bgm_path = value("general-bgm");
    system.music_volumn = numeric("general-volume", system.music_volumn);
    system.theme_color = value("general-theme");
    system.chat_ui_theme_path = value("general-chat-theme-path");
    system.voice_language = value("voice-language");
    system.asr_language = value("voice-asr-language");
    system.asr_whisper_model_size = value("voice-whisper-model");
    system.asr_whisper_device = value("voice-whisper-device");
    system.asr_whisper_compute_type = value("voice-whisper-compute");
    system.sprite_realtime_enabled = checked("image-realtime");
    system.sprite_realtime_prompt_template = value("image-realtime-template");
    system.sprite_realtime_cache_dir = value("image-cache-dir");
    system.proactive_contact_enabled = checked("proactive-enabled");
    system.screen_context_enabled = checked("screen-context-enabled");
    system.screen_context_interval_seconds = numeric("screen-context-interval", Number(system.screen_context_interval_seconds) || 300);
    system.screen_context_display_ids = csvValues(value("screen-context-display-ids"));
    system.proactive_photo_enabled = checked("proactive-photo");
    system.proactive_photo_daily_limit = numeric("proactive-photo-limit", system.proactive_photo_daily_limit);
    system.external_delivery_enabled = checked("proactive-external");
    system.external_delivery_requires_confirmation = checked("proactive-confirm");
    system.external_delivery_audio_enabled = checked("proactive-audio");
    system.external_delivery_channel = value("proactive-channel");
    system.external_delivery_daily_limit = numeric("proactive-limit", system.external_delivery_daily_limit);
    system.external_delivery_quiet_hours = value("proactive-quiet");
    system.chat_delivery_channel = value("proactive-chat-channel");
    system.active_character_name = state.active_character_name;

    const index = characters.findIndex((item) => item.name === activeCharacter().name);
    if (index >= 0 && document.querySelector("#character-name")) {
      characters[index] = {
        ...characters[index],
        name: value("character-name"),
        color: value("character-color"),
        sprite_prefix: value("character-prefix"),
        sprite_scale: numeric("character-scale", characters[index].sprite_scale),
        speech_speed: numeric("character-speed", characters[index].speech_speed),
        speech_volume: numeric("character-volume", characters[index].speech_volume),
        visual_reference_image: value("character-reference"),
        visual_identity: value("character-visual"),
        character_setting: value("character-setting"),
        emotion_tags: value("character-emotions"),
        character_profile: document.querySelector("#character-profile-age")
          ? characterProfileFromSettings(characters[index].character_profile)
          : parseJson("character-profile", characters[index].character_profile),
        pronunciation_map: parseJson("character-pronunciation", characters[index].pronunciation_map),
      };
      if (state.active_character_name !== characters[index].name) system.active_character_name = characters[index].name;
    }

    const messaging: Record<string, Record<string, unknown>> = clone(state.messaging || {});
    for (const platform of ["telegram", "discord", "wechat", "feishu", "whatsapp"]) {
      const current = messaging[platform] || {};
      current.enabled = checked(`platform-${platform}-enabled`);
      document.querySelectorAll<HTMLInputElement>(`[id^='platform-${platform}-']:not([type='checkbox'])`).forEach((input) => {
        current[input.id.slice(`platform-${platform}-`.length)] = input.value;
      });
      if (platform === "wechat") current.require_context_token = checked("platform-wechat-require_context_token");
      messaging[platform] = current;
    }

    const pinChanged = checked("general-pin") !== state.window.always_on_top;
    const savedCharacterName = characters[index]?.name || originalCharacterName;
    state = await api.saveConfig({
      api_config: apiConfig,
      system_config: system,
      characters,
      character_rename: { old_name: originalCharacterName, new_name: savedCharacterName },
    });
    await api.backendCall("save_messaging", messaging, 60_000);
    const memoryEntries = value("memory-character").split(/\n---\n/).map((item) => item.trim()).filter(Boolean);
    const userEntries = value("memory-user").split(/\n---\n/).map((item) => item.trim()).filter(Boolean);
    await api.backendCall("update_memory", { character_name: state.active_character_name, kind: "character", entries: memoryEntries });
    state.memory = await api.backendCall("update_memory", { character_name: state.active_character_name, kind: "user", entries: userEntries });
    await api.backendCall("save_storage", {
      character_memory_dir: value("storage-memory"),
      character_assets_dir: value("storage-assets"),
      copy_memory: checked("storage-copy-memory"),
      copy_assets: checked("storage-copy-assets"),
    }, 60_000);
    if (pinChanged) state.window.always_on_top = await api.windowAction("toggle-pin");
    status.textContent = "已保存";
    await applyState();
    setTimeout(() => settingsDialog.close(), 280);
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : String(error);
  }
}

const mbtiDescriptions: Record<string, string> = {
  INTJ: "战略型、独立、目标感强，习惯先观察再行动。",
  INTP: "分析型、好奇、重逻辑，喜欢拆解问题。",
  ENTJ: "领导型、果断、有推进力，喜欢掌控节奏。",
  ENTP: "创意型、机敏、爱辩论，喜欢新点子。",
  INFJ: "洞察型、温和、有理想，擅长理解他人情绪。",
  INFP: "理想主义、敏感、共情强，重视真实感受。",
  ENFJ: "照顾型、热情、有感染力，擅长鼓励别人。",
  ENFP: "灵感型、活泼、情绪丰富，喜欢自由表达。",
  ISTJ: "稳重、守信、重秩序，做事可靠。",
  ISFJ: "守护型、细心、体贴，习惯默默照顾人。",
  ESTJ: "务实、直接、执行力强，重视效率。",
  ESFJ: "亲和、外向、会照顾气氛，重视关系。",
  ISTP: "冷静、动手能力强，喜欢直接解决问题。",
  ISFP: "柔和、审美敏感、重感受，表达克制。",
  ESTP: "行动派、爽快、会制造现场感。",
  ESFP: "开朗、热情、爱分享，情绪感染力强。",
};

function csvValues(text: string): string[] {
  return text.split(/[,，、\n]+/).map((item) => item.trim()).filter(Boolean);
}

function createCharacterProfile(): Record<string, unknown> {
  return {
    identity: {
      age: Math.max(18, Number(value("create-profile-age")) || 22),
      birthday: value("create-profile-birthday").trim(),
      gender: value("create-profile-gender").trim(),
      occupation: value("create-profile-occupation").trim(),
      life_status: value("create-profile-life-status").trim(),
      relationship_to_user: value("create-profile-relationship").trim(),
      first_person: value("create-profile-first-person").trim(),
      user_address: value("create-profile-user-address").trim(),
    },
    personality: {
      mbti: selectedCreateMbti,
      mbti_style: value("create-profile-mbti-style").trim(),
      custom_traits: csvValues(value("create-profile-traits")),
      flaws: csvValues(value("create-profile-flaws")),
      contrast: value("create-profile-contrast").trim(),
    },
    speech: {
      tone: csvValues(value("create-profile-tone")),
      reply_length: value("create-profile-reply-length").trim(),
      catchphrases: csvValues(value("create-profile-catchphrases")),
    },
    relationship: {
      stage: value("create-profile-stage").trim(),
      trust_triggers: csvValues(value("create-profile-trust")),
      sadness_triggers: csvValues(value("create-profile-sadness")),
    },
    preferences: {
      likes: csvValues(value("create-profile-likes")),
      dislikes: csvValues(value("create-profile-dislikes")),
      hobbies: csvValues(value("create-profile-hobbies")),
    },
    boundaries: {
      adult: true,
      intimacy_level: value("create-profile-boundary").trim(),
      notes: value("create-profile-boundary-notes").trim(),
    },
  };
}

function listText(value: unknown): string {
  return Array.isArray(value) ? value.map(String).filter(Boolean).join("、") : String(value || "").trim();
}

function buildCharacterSettingText(name: string, profile: Record<string, unknown>): string {
  const normalized = profileMap(profile);
  const identity = profileMap(normalized.identity);
  const personality = profileMap(normalized.personality);
  const speech = profileMap(normalized.speech);
  const relationship = profileMap(normalized.relationship);
  const preferences = profileMap(normalized.preferences);
  const boundaries = profileMap(normalized.boundaries);
  const selectedMbti = profileText(personality.mbti, "INFP").toUpperCase();
  const lines = [
    `${name}是${identity.age || 22}岁的${identity.gender || "女性"}，职业/身份是${identity.occupation || "自学中的程序员"}，居住/运行环境是${identity.life_status || "独居"}。`,
    `她与用户的关系是${identity.relationship_to_user || "朋友"}，第一人称使用“${identity.first_person || "我"}”，称呼用户为“${identity.user_address || "你"}”。`,
  ];
  if (identity.birthday) lines.push(`她的生日是${identity.birthday}。`);
  lines.push("");
  lines.push(`她的 MBTI 设定为 ${selectedMbti}，表现方式是${personality.mbti_style || "典型表现"}。${mbtiDescriptions[selectedMbti] || ""}`);
  const traits = listText(personality.custom_traits);
  const flaws = listText(personality.flaws);
  if (traits) lines.push(`性格补充：${traits}。`);
  if (flaws) lines.push(`她的缺点/脆弱点是：${flaws}。`);
  if (personality.contrast) lines.push(`她的反差点是：${personality.contrast}。`);
  lines.push("");
  lines.push(`她说话风格${listText(speech.tone) || "自然、亲近"}，回复长度偏${speech.reply_length || "适中"}。`);
  const catchphrases = speech.catchphrases as string[];
  if (catchphrases.length) lines.push(`她偶尔会使用这些口头禅：${catchphrases.map((item) => `“${item}”`).join("、")}。`);
  lines.push(`关系阶段：${relationship.stage || "朋友"}。`);
  if (listText(relationship.trust_triggers)) lines.push(`让她更信任用户的触发点：${listText(relationship.trust_triggers)}。`);
  if (listText(relationship.sadness_triggers)) lines.push(`容易让她失落的触发点：${listText(relationship.sadness_triggers)}。`);
  if (listText(preferences.likes)) lines.push(`她喜欢：${listText(preferences.likes)}。`);
  if (listText(preferences.dislikes)) lines.push(`她讨厌：${listText(preferences.dislikes)}。`);
  if (listText(preferences.hobbies)) lines.push(`她的爱好是：${listText(preferences.hobbies)}。`);
  lines.push("");
  lines.push(`亲密边界：${boundaries.intimacy_level || "普通陪伴"}。角色必须是成年人。`);
  if (boundaries.notes) lines.push(String(boundaries.notes));
  return lines.join("\n").trim();
}

function generatedCharacterSetting(): string {
  const name = value("create-character-name").trim() || "这个角色";
  return buildCharacterSettingText(name, createCharacterProfile());
}

function syncCreateProfilePreview(force = false): void {
  $("#create-mbti-description").textContent = mbtiDescriptions[selectedCreateMbti] || "";
  const setting = $("#create-character-setting") as HTMLTextAreaElement;
  const generated = generatedCharacterSetting();
  if (force || !setting.value.trim() || setting.value.trim() === lastGeneratedCharacterSetting.trim()) {
    updatingGeneratedCharacterSetting = true;
    setting.value = generated;
    updatingGeneratedCharacterSetting = false;
    lastGeneratedCharacterSetting = generated;
  }
}

function updateCreateStateControls(stateName: string): void {
  const paths = createCharacterStateAssets[stateName] || [];
  const pathInput = document.querySelector<HTMLInputElement>(`[data-create-state-path='${CSS.escape(stateName)}']`);
  if (pathInput) pathInput.value = paths.map((path) => path.split(/[\\/]/).pop()).filter(Boolean).join(", ");
  const openButton = document.querySelector<HTMLButtonElement>(`[data-open-create-state='${CSS.escape(stateName)}']`);
  if (openButton) openButton.disabled = paths.length === 0;
}

async function chooseCreateStateAsset(stateName: string, kind: "character_image" | "character_animation"): Promise<void> {
  const paths = await api.chooseFiles(kind);
  if (!paths.length) return;
  createCharacterStateAssets[stateName] = paths;
  updateCreateStateControls(stateName);
}

async function openCreateStateAsset(stateName: string): Promise<void> {
  const paths = createCharacterStateAssets[stateName] || [];
  if (!paths.length) return;
  const target = paths.length > 1 ? paths[0].replace(/[\\/][^\\/]+$/, "") : paths[0];
  await api.openPath(target);
}

function clearCreateStateAsset(stateName: string): void {
  delete createCharacterStateAssets[stateName];
  updateCreateStateControls(stateName);
}

function showCreateProfilePage(page: string): void {
  $$<HTMLElement>("[data-create-profile-tab]").forEach((button) => button.classList.toggle("is-active", button.dataset.createProfileTab === page));
  $$<HTMLElement>("[data-create-profile-page]").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.createProfilePage === page));
}

function openCreateCharacter(): void {
  createCharacterStateAssets = {};
  ($("#create-character-form") as HTMLFormElement).reset();
  selectedCreateMbti = "INFP";
  lastGeneratedCharacterSetting = "";
  $$<HTMLElement>("[data-create-mbti]").forEach((button) => button.classList.toggle("is-active", button.dataset.createMbti === selectedCreateMbti));
  showCreateProfilePage("basic");
  $$<HTMLInputElement>("[data-create-state-path]").forEach((input) => { input.value = ""; });
  $$<HTMLButtonElement>("[data-open-create-state]").forEach((button) => { button.disabled = true; });
  $("#create-character-status").textContent = "";
  syncCreateProfilePreview(true);
  createCharacterDialog.showModal();
  ($("#create-character-name") as HTMLInputElement).focus();
}

async function createCharacter(): Promise<void> {
  const status = $("#create-character-status");
  const button = $("#confirm-create-character") as HTMLButtonElement;
  const name = value("create-character-name").trim();
  const setting = value("create-character-setting").trim();
  const states = Object.entries(createCharacterStateAssets).filter(([, paths]) => paths.length).map(([stateName, paths]) => ({
    state_name: stateName,
    state_group: "core_emotion",
    frame_interval_ms: Number((document.querySelector(`[data-create-state-interval='${stateName}']`) as HTMLInputElement)?.value || 120),
    paths,
  }));
  if (!name) { status.textContent = "角色名不能为空"; return; }
  if (!setting) { status.textContent = "请填写角色人设"; return; }
  if (!states.length) { status.textContent = "至少需要导入一个立绘图片或动画"; return; }
  try {
    button.disabled = true;
    state = await api.backendCall<DesktopState>("create_character", {
      name,
      setting,
      visual_identity: value("create-character-visual").trim(),
      character_profile: createCharacterProfile(),
      states,
    }, 120_000);
    createCharacterDialog.close();
    renderSettings();
    await applyState();
    $("#settings-status").textContent = `已创建 ${state.active_character_name}`;
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    button.disabled = false;
  }
}

function commitCharacterDraft(): void {
  const character = activeCharacter();
  if (!document.querySelector("#character-name")) return;
  commitSpriteDrafts(character);
  const oldName = character.name;
  character.name = value("character-name") || character.name;
  character.color = value("character-color") || character.color;
  character.sprite_prefix = value("character-prefix") || character.sprite_prefix;
  character.sprite_scale = numeric("character-scale", character.sprite_scale);
  character.speech_speed = numeric("character-speed", character.speech_speed);
  character.speech_volume = numeric("character-volume", character.speech_volume);
  character.visual_reference_image = value("character-reference");
  character.character_setting = value("character-setting");
  character.visual_identity = value("character-visual");
  character.emotion_tags = value("character-emotions");
  character.character_profile = document.querySelector("#character-profile-age")
    ? characterProfileFromSettings(character.character_profile)
    : parseJson("character-profile", character.character_profile);
  character.pronunciation_map = parseJson("character-pronunciation", character.pronunciation_map);
  if (state.active_character_name === oldName) {
    state.active_character_name = character.name;
    state.config.system_config.active_character_name = character.name;
  }
}

async function persistCharacterDraft(): Promise<void> {
  const oldName = activeCharacter().name;
  commitCharacterDraft();
  const newName = state.active_character_name;
  state = await api.saveConfig({
    characters: clone(state.config.characters),
    system_config: clone(state.config.system_config),
    character_rename: { old_name: oldName, new_name: newName },
  });
}

async function deleteCharacter(): Promise<void> {
  const character = activeCharacter();
  if (character.name === "here_system") {
    $("#settings-status").textContent = "内置系统角色不能删除。";
    return;
  }
  if (state.config.characters.length <= 1) return;
  if (!window.confirm(`删除角色“${character.name}”及其立绘、语音和模型文件？`)) return;
  const deleteMemory = window.confirm("同时删除这个角色的长期记忆？选择“取消”会保留记忆。");
  try {
    state = await api.backendCall<DesktopState>("delete_character", {
      name: character.name,
      delete_memory: deleteMemory,
    }, 120_000);
    renderSettings();
    await applyState();
  } catch (error) {
    $("#settings-status").textContent = error instanceof Error ? error.message : String(error);
  }
}

async function uploadCharacterSprites(): Promise<void> {
  const selected = await api.chooseImages();
  if (!selected.length) return;
  try {
    await persistCharacterDraft();
    const result = await api.backendCall<DesktopState>("upload_character_sprites", {
      character_name: state.active_character_name,
      attachments: selected,
      emotion_tags: value("character-emotions"),
    }, 120_000);
    state = result;
    renderSettings();
  } catch (error) {
    $("#settings-status").textContent = error instanceof Error ? error.message : String(error);
  }
}

async function importLegacy(): Promise<void> {
  const status = $("#settings-status");
  try {
    const report = await api.importLegacy();
    if (!report) return;
    state = await api.getState();
    status.textContent = `已导入 ${report.charactersImported} 个角色`;
    renderSettings();
    await applyState();
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function importCodexPet(path = ""): Promise<void> {
  setBusy("正在导入 Codex Pet…", true);
  try {
    const response = (path
      ? await api.backendCall<{ state?: DesktopState }>("import_codex_pet", { path }, 120_000)
      : await api.importCodexPet()) as { state?: DesktopState } | null;
    if (!response) {
      setBusy("", false);
      return;
    }
    state = response.state || await api.getState();
    renderSettings();
    await applyState();
    setBusy(`已导入 ${state.active_character_name}`, true);
    window.setTimeout(() => setBusy("", false), 3_200);
  } catch (error) {
    setBusy(error instanceof Error ? error.message : String(error), true);
    window.setTimeout(() => setBusy("", false), 4_200);
  }
}

async function startWechatLogin(): Promise<void> {
  const box = document.querySelector<HTMLElement>("#wechat-login-box");
  if (!box) return;
  box.classList.remove("is-hidden");
  box.textContent = "正在生成二维码…";
  try {
    const login = await api.backendCall<Record<string, unknown>>("wechat_login_start", {
      base_url: value("platform-wechat-base_url"),
    }, 60_000);
    box.innerHTML = `<img src="${esc(login.qr_data_url)}" alt="微信登录二维码"><span>${esc(login.message || "请使用微信扫码")}</span>`;
    const startedAt = Date.now();
    let baseUrl = value("platform-wechat-base_url") || "https://ilinkai.weixin.qq.com";
    while (Date.now() - startedAt < 2 * 60_000 && settingsDialog.open) {
      const polled = await api.backendCall<Record<string, unknown>>("wechat_login_poll", {
        qrcode: login.qrcode,
        base_url: baseUrl,
      }, 20_000);
      if (polled.redirect_base_url) baseUrl = String(polled.redirect_base_url);
      if (polled.status === "confirmed") {
        box.innerHTML = '<i data-lucide="circle-check"></i><span>微信登录成功</span>';
        refreshIcons();
        state = await api.getState();
        await refreshWechatStatus();
        return;
      }
      if (polled.status === "failed" || polled.status === "expired") throw new Error(String(polled.message || "微信登录失败"));
      await new Promise((resolve) => setTimeout(resolve, 1_000));
    }
    box.querySelector("span")!.textContent = "二维码已过期";
  } catch (error) {
    box.textContent = error instanceof Error ? error.message : String(error);
  }
}

function showSettingsPage(tab: string): void {
  activeSettingsTab = tab;
  $$(".tab-button").forEach((button) => button.classList.toggle("is-active", (button as HTMLElement).dataset.tab === tab));
  $$(".settings-page").forEach((page) => page.classList.toggle("is-active", (page as HTMLElement).dataset.page === tab));
}

function openSettings(tab = "general"): void {
  activeSettingsTab = tab;
  renderSettings();
  if (!settingsDialog.open) settingsDialog.showModal();
}

async function applyState(): Promise<void> {
  const system = state.config.system_config;
  const chatTheme = state.chat_ui_theme || {
    dialog_offset_y: 0,
    dialog_width_pct: 80,
    dialog_padding: 40,
    options_gap: 10,
  };
  await setLocale(system.ui_language);
  const externalChat = system.chat_delivery_channel !== "desktop_chat";
  document.documentElement.style.setProperty("--font-scale", String(Math.max(0.75, Math.min(1.4, system.base_font_size_px / 40))));
  const savedDialogWidth = Number(system.dialog_box_width_pct || 0);
  const dialogWidth = Math.max(30, Math.min(100, savedDialogWidth > 0 ? savedDialogWidth : Number(chatTheme.dialog_width_pct || 80)));
  document.documentElement.style.setProperty("--dialog-width", `${dialogWidth}%`);
  document.documentElement.style.setProperty("--dialog-offset-y", `${Number(chatTheme.dialog_offset_y || 0)}px`);
  document.documentElement.style.setProperty("--options-padding", `${Math.max(0, Number(chatTheme.dialog_padding ?? 40))}px`);
  document.documentElement.style.setProperty("--options-gap", `${Math.max(0, Number(chatTheme.options_gap ?? 10))}px`);
  const theme = normalizeThemeColor(String(system.theme_color || ""));
  if (theme) {
    document.documentElement.style.setProperty("--accent", theme);
    document.documentElement.style.setProperty(
      "--dialog-theme",
      qtDialogBackground(String(system.theme_color || "")) || theme,
    );
  }
  $("#title-character").textContent = state.active_character_name;
  $("#call-character").textContent = state.active_character_name;
  $("#backend-name").textContent = state.selected_backend;
  dialogName.textContent = state.active_character_name;
  dialogName.style.color = activeCharacter().color;
  stage.classList.toggle("is-system-character", state.active_character_name === "here_system");
  const callLayout = stage.classList.contains("call-mode");
  const dialogHidden = externalChat || (!callLayout && system.dialog_box_collapsed);
  dialogPanel.classList.toggle("is-hidden", dialogHidden);
  dialogCaption.classList.toggle("is-hidden", dialogHidden);
  $("#dialog-component").classList.toggle("is-collapsed", dialogHidden);
  $("#restore-dialog").classList.toggle("is-hidden", callLayout || !system.dialog_box_collapsed || externalChat);
  composer.classList.toggle("is-hidden", externalChat || (!callLayout && system.input_bar_collapsed));
  $("#options-panel").classList.toggle("is-hidden", externalChat || !$("#options-panel").children.length);
  await Promise.all([renderSprite(currentEmotion), renderBackgroundAndBgm()]);
  applyDialogLayout();
  renderCharacterMenu();
  applyLocale(document.body);
}

function setDialogVisible(visible: boolean): void {
  dialogPanel.classList.toggle("is-hidden", !visible);
  dialogCaption.classList.toggle("is-hidden", !visible);
  $("#dialog-component").classList.toggle("is-collapsed", !visible);
  applyDialogLayout();
}

function applyDialogLayout(): void {
  if (!state) return;
  const chatTheme = state.chat_ui_theme || { dialog_width_pct: 80, dialog_offset_y: 0 };
  const stageRect = stage.getBoundingClientRect();
  const savedDialogWidth = Number(state.config.system_config.dialog_box_width_pct || 0);
  const configuredDialogWidth = Math.max(
    30,
    Math.min(100, savedDialogWidth > 0 ? savedDialogWidth : Number(chatTheme.dialog_width_pct || 80)),
  );
  const callLayout = stage.classList.contains("call-mode");
  document.documentElement.style.setProperty(
    "--dialog-width",
    callLayout
      ? `${configuredDialogWidth}%`
      : `${qtOverlayWidthPx(stageRect.width, configuredDialogWidth)}px`,
  );
  if (callLayout) {
    // The call footer is painted inside the stage. Keep it out of the
    // dialogue's sizing area so a short window cannot push the bubble under
    // the controls.
    const callControls = document.querySelector<HTMLElement>(".call-controls");
    const callControlsHeight = callControls?.getBoundingClientRect().height
      || Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--call-controls-height"))
      || 50;
    const availableHeight = Math.max(1, stageRect.height - callControlsHeight);
    const minHeight = Math.min(58, availableHeight);
    const maxHeight = Math.max(minHeight, Math.min(260, availableHeight * 0.55));
    const configuredHeight = Number(state.config.system_config.dialog_box_height_pct || 0);
    const contentHeight = Math.max(minHeight, dialogText.scrollHeight + 30);
    // 45% is the legacy seeded value (81% width / 45% height). In the
    // call-style surface it produced a mostly empty bubble for short replies;
    // preserve non-default values for explicit settings and drag-resize, but
    // let the seeded value follow the actual text height.
    const usesLegacyDefaultDialogHeight = configuredDialogWidth === 81 && configuredHeight === 45;
    const requestedHeight = configuredHeight > 0 && !usesLegacyDefaultDialogHeight
      ? availableHeight * Math.max(14, Math.min(70, configuredHeight)) / 100
      : contentHeight;
    const dialogHeight = Math.round(Math.max(minHeight, Math.min(maxHeight, requestedHeight)));
    dialogComponent.style.height = `${dialogHeight}px`;
    dialogComponent.style.maxHeight = `${maxHeight}px`;
    dialogPanel.style.height = "100%";
    dialogPanel.style.maxHeight = "none";
    dialogCaption.style.height = "100%";
    dialogPanel.style.top = "";
    dialogPanel.style.bottom = "";
    dialogCaption.style.top = "";
    composer.style.top = "";
    composer.style.bottom = "";
    return;
  }
  const composerVisible = !composer.classList.contains("is-hidden");
  const dialogVisible = !dialogPanel.classList.contains("is-hidden");
  const composerHeight = composerVisible ? composer.getBoundingClientRect().height : 0;
  const canvasReady = !spriteCanvas.classList.contains("is-hidden")
    && spriteCanvas.width > 0
    && spriteCanvas.height > 0;
  const imageReady = !spriteImage.classList.contains("is-hidden")
    && spriteImage.complete
    && spriteImage.naturalWidth > 0
    && spriteImage.naturalHeight > 0;
  const videoReady = !spriteVideo.classList.contains("is-hidden") && spriteVideo.videoWidth > 0;
  const spriteElement = !spriteWrap.classList.contains("is-hidden")
    ? (videoReady ? spriteVideo : canvasReady ? spriteCanvas : imageReady ? spriteImage : null)
    : null;
  const spriteRect = spriteElement?.getBoundingClientRect();
  const spriteTop = spriteRect ? Math.max(0, spriteRect.top - stageRect.top) : 0;
  const spriteBottom = spriteRect ? Math.min(stageRect.height, spriteRect.bottom - stageRect.top) : 0;
  const spriteHeight = dialogVisible && spriteRect ? Math.max(0, spriteBottom - spriteTop) : 0;
  const panelStyle = getComputedStyle(dialogPanel);
  const panelChromeHeight = Number.parseFloat(panelStyle.paddingTop)
    + Number.parseFloat(panelStyle.paddingBottom)
    + Number.parseFloat(panelStyle.borderTopWidth)
    + Number.parseFloat(panelStyle.borderBottomWidth);
  const contentHeight = dialogText.scrollHeight + panelChromeHeight;
  const layout = qtDialogLayout(
    stageRect.height,
    composerHeight,
    10,
    spriteTop,
    spriteHeight,
    contentHeight,
    Number(state.config.system_config.dialog_box_height_pct || 0),
  );

  const dialogOffsetY = Number(chatTheme.dialog_offset_y || 0);
  const maxDialogTop = Math.max(0, Math.min(stageRect.height - layout.dialogHeight, layout.composerTop - 6 - layout.dialogHeight));
  const boundedDialogTop = Math.max(
    0,
    Math.min(maxDialogTop, layout.dialogTop + dialogOffsetY),
  );
  dialogPanel.style.top = `${boundedDialogTop}px`;
  dialogPanel.style.bottom = "auto";
  dialogPanel.style.height = `${layout.dialogHeight}px`;
  const captionHeight = dialogCaption.getBoundingClientRect().height || 26;
  const captionTop = Math.max(0, boundedDialogTop - captionHeight - 3);
  dialogCaption.style.top = `${captionTop}px`;
  if (composerVisible) {
    composer.style.top = `${layout.composerTop}px`;
    composer.style.bottom = "auto";
  }
}

function dialogResizeEdges(event: PointerEvent): Set<DialogResizeEdge> {
  const rect = dialogPanel.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return new Set();
  const margin = Math.min(10, Math.max(6, Math.min(rect.width, rect.height) / 4));
  const edges = new Set<DialogResizeEdge>();
  if (event.clientX - rect.left <= margin) edges.add("left");
  if (rect.right - event.clientX <= margin) edges.add("right");
  if (event.clientY - rect.top <= margin) edges.add("top");
  if (rect.bottom - event.clientY <= margin) edges.add("bottom");
  return edges;
}

function dialogResizeCursor(edges: ReadonlySet<DialogResizeEdge>): string {
  const horizontal = edges.has("left") || edges.has("right");
  const vertical = edges.has("top") || edges.has("bottom");
  if (horizontal && vertical) {
    return (edges.has("left") === edges.has("top")) ? "nwse-resize" : "nesw-resize";
  }
  if (horizontal) return "ew-resize";
  if (vertical) return "ns-resize";
  return "default";
}

function updateDialogResizeCursor(event: PointerEvent): void {
  if (dialogResizeSession) return;
  dialogPanel.style.cursor = dialogResizeCursor(dialogResizeEdges(event));
}

function beginDialogResize(event: PointerEvent): void {
  if (event.button !== 0 || dialogPanel.classList.contains("is-hidden")) return;
  const edges = dialogResizeEdges(event);
  if (!edges.size) return;
  const rect = dialogPanel.getBoundingClientRect();
  dialogResizeSession = {
    pointerId: event.pointerId,
    edges,
    startX: event.clientX,
    startY: event.clientY,
    startWidth: rect.width,
    startHeight: rect.height,
  };
  suppressDialogClick = true;
  dialogPanel.setPointerCapture(event.pointerId);
  event.preventDefault();
  event.stopPropagation();
}

function applyDialogResize(event: PointerEvent): void {
  const session = dialogResizeSession;
  if (!session || event.pointerId !== session.pointerId) return;
  const stageRect = stage.getBoundingClientRect();
  const availableWidth = Math.max(1, stageRect.width);
  const availableHeight = Math.max(1, stageRect.height);
  const bounds = {
    minWidth: Math.min(260, availableWidth),
    maxWidth: availableWidth,
    minHeight: Math.min(58, availableHeight),
    maxHeight: Math.max(Math.min(58, availableHeight), Math.min(260, availableHeight * 0.7)),
  };
  const size = qtDialogResizeSize(
    session.startWidth,
    session.startHeight,
    event.clientX - session.startX,
    event.clientY - session.startY,
    session.edges,
    bounds,
  );
  const system = state.config.system_config;
  system.dialog_box_width_pct = Math.round(size.width / availableWidth * 100);
  system.dialog_box_height_pct = Math.round(size.height / availableHeight * 100);
  applyDialogLayout();
  event.preventDefault();
}

function endDialogResize(event: PointerEvent): void {
  const session = dialogResizeSession;
  if (!session || event.pointerId !== session.pointerId) return;
  dialogResizeSession = null;
  if (dialogPanel.hasPointerCapture(event.pointerId)) dialogPanel.releasePointerCapture(event.pointerId);
  event.preventDefault();
  void persistDisplayState({
    dialog_box_width_pct: state.config.system_config.dialog_box_width_pct,
    dialog_box_height_pct: state.config.system_config.dialog_box_height_pct,
  });
}

async function localUrl(path: string): Promise<string> {
  if (!path) return "";
  return await api.localFileUrl(path);
}

async function renderBackgroundAndBgm(): Promise<void> {
  const image = $("#background-image") as HTMLImageElement;
  const { background_path: backgroundPath, bgm_path: bgmPath, music_volumn: volume } = state.config.system_config;
  if (backgroundPath) {
    try { image.src = await localUrl(backgroundPath); image.classList.remove("is-hidden"); }
    catch { image.classList.add("is-hidden"); }
  } else image.classList.add("is-hidden");
  if (backgroundAudio) { backgroundAudio.pause(); backgroundAudio = null; }
  if (bgmPath) {
    try {
      backgroundAudio = new Audio(await localUrl(bgmPath));
      backgroundAudio.loop = true;
      backgroundAudio.volume = Math.max(0, Math.min(1, volume / 100));
      void backgroundAudio.play().catch(() => undefined);
    } catch { backgroundAudio = null; }
  }
}

function updateSpriteMediaMode(source: CanvasImageSource, sourceWidth: number, sourceHeight: number): void {
  try {
    const probe = document.createElement("canvas");
    probe.width = 32;
    probe.height = 32;
    const context = probe.getContext("2d", { willReadFrequently: true });
    if (!context) return;
    context.drawImage(source, 0, 0, sourceWidth, sourceHeight, 0, 0, probe.width, probe.height);
    const pixels = context.getImageData(0, 0, probe.width, probe.height).data;
    let transparentPixels = 0;
    for (let index = 3; index < pixels.length; index += 4) {
      if (pixels[index] < 245) transparentPixels += 1;
    }
    spriteWrap.classList.toggle("is-cutout", transparentPixels > probe.width * probe.height * 0.02);
  } catch {
    spriteWrap.classList.remove("is-cutout");
  }
}

async function renderSprite(emotion = "neutral", assetId?: string | number | null): Promise<void> {
  const token = ++spriteLoadToken;
  spriteVideo.pause();
  if (spriteTimer !== null) window.clearInterval(spriteTimer);
  spriteTimer = null;
  const hasVideoCall = activeCharacter().sprites.some((sprite) => sprite.state_name === "video_call");
  const callControl = $("[data-call-toggle='video']") as HTMLButtonElement;
  callControl.disabled = !hasVideoCall;
  updateCallControl(callControl, !hasVideoCall || !characterVideoEnabled);
  if (!hasVideoCall) callControl.title = "未设置通话视频";
  if (state.config.system_config.sprite_realtime_enabled && !hasVideoCall) {
    try {
      const generated = await api.backendCall<{ path: string; scale?: number }>("generate_realtime_sprite", {
        character_name: state.active_character_name,
        emotion,
        scene: "normal",
      }, 10 * 60_000);
      if (token !== spriteLoadToken) return;
      if (generated.path) {
        await renderSingleSprite(generated.path, Number(generated.scale || 1), token);
        return;
      }
    } catch (error) {
      console.error("Realtime sprite generation failed; using static sprite", error);
    }
  }
  const resolved = await api.backendCall<{ name: string; scale: number; sprites: ResolvedSprite[] }>("resolve_assets", { character_name: state.active_character_name });
  if (token !== spriteLoadToken || !resolved.sprites.length) return;
  const sprite = selectDisplaySprite(resolved.sprites, characterVideoEnabled, emotion, assetId);
  if (!sprite) { spriteVideo.classList.add("is-hidden"); return; }
  const scale = Math.max(0.15, Math.min(3, Number(resolved.scale || 1)));
  spriteImage.style.transform = "none";
  spriteCanvas.style.transform = "none";
  if (isVideoSprite(sprite)) {
    const videoUrl = spriteVideo.dataset.assetPath === sprite.path && spriteVideoReady
      ? spriteVideo.src : await localUrl(sprite.path);
    if (token !== spriteLoadToken) return;
    spriteVideo.dataset.assetPath = sprite.path;
    await renderSpriteVideo(videoUrl, token, scale);
    return;
  }
  spriteVideo.classList.add("is-hidden");
  if (sprite.spritesheet_path && sprite.frame_width && sprite.frame_height) {
    await renderSpritesheet(sprite, token, scale);
    return;
  }
  spriteCanvas.classList.add("is-hidden");
  spriteImage.classList.remove("is-hidden");
  const paths = sprite.frames?.length ? sprite.frames : [sprite.path];
  const urls = await Promise.all(paths.filter(Boolean).map(localUrl));
  if (token !== spriteLoadToken || !urls.length) return;
  let index = 0;
  spriteImage.src = urls[0];
  await spriteImage.decode().catch(() => undefined);
  if (token !== spriteLoadToken) return;
  updateSpriteMediaMode(spriteImage, spriteImage.naturalWidth, spriteImage.naturalHeight);
  const wrap = $("#sprite-wrap") as HTMLElement;
  const ratio = Math.min(
    scale,
    wrap.clientWidth / Math.max(1, spriteImage.naturalWidth),
    wrap.clientHeight / Math.max(1, spriteImage.naturalHeight),
  );
  spriteImage.style.width = `${Math.round(spriteImage.naturalWidth * ratio)}px`;
  spriteImage.style.height = `${Math.round(spriteImage.naturalHeight * ratio)}px`;
  applyDialogLayout();
  if (urls.length > 1 && characterVideoEnabled) {
    const interval = sprite.fps ? Math.round(1000 / sprite.fps) : Number(sprite.frame_interval_ms || 120);
    spriteTimer = window.setInterval(() => {
      index = (index + 1) % urls.length;
      spriteImage.src = urls[index];
    }, Math.max(36, interval));
  }
}

function updateSpriteVideoPlayback(): void {
  if (!characterVideoEnabled) {
    spriteVideo.pause();
    return;
  }
  void spriteVideo.play().catch((error) => {
    if (error instanceof DOMException && error.name === "AbortError") return;
    characterVideoEnabled = false;
    updateCallControl($("[data-call-toggle='video']") as HTMLButtonElement, true);
    console.error("Unable to play character video", error);
    void renderSprite("neutral");
  });
}

async function renderSpriteVideo(url: string, token: number, scale: number): Promise<void> {
  if (spriteVideo.src !== new URL(url, document.baseURI).href) spriteVideoReady = null;
  spriteVideoReady ??= new Promise<void>((resolve, reject) => {
    const finish = (error?: Error): void => {
      window.clearTimeout(timeout);
      spriteVideo.removeEventListener("loadeddata", loaded);
      spriteVideo.removeEventListener("error", failed);
      if (error) reject(error);
      else resolve();
    };
    const loaded = (): void => finish();
    const failed = (): void => finish(new Error("Unable to load character video"));
    const timeout = window.setTimeout(failed, 15_000);
    spriteVideo.addEventListener("loadeddata", loaded, { once: true });
    spriteVideo.addEventListener("error", failed, { once: true });
    spriteVideo.muted = true;
    spriteVideo.src = url;
    spriteVideo.load();
  }).catch((error) => {
    spriteVideoReady = null;
    throw error;
  });
  try {
    await spriteVideoReady;
  } catch (error) {
    if (token !== spriteLoadToken) return;
    console.error("Unable to load character video; returning to neutral", error);
    characterVideoEnabled = false;
    updateCallControl($("[data-call-toggle='video']") as HTMLButtonElement, true);
    await renderSprite("neutral");
    return;
  }
  if (token !== spriteLoadToken) return;
  const ratio = Math.min(scale, spriteWrap.clientWidth / spriteVideo.videoWidth,
    spriteWrap.clientHeight / spriteVideo.videoHeight);
  spriteVideo.style.width = `${Math.round(spriteVideo.videoWidth * ratio)}px`;
  spriteVideo.style.height = `${Math.round(spriteVideo.videoHeight * ratio)}px`;
  spriteWrap.classList.remove("is-cutout");
  spriteImage.classList.add("is-hidden");
  spriteCanvas.classList.add("is-hidden");
  spriteVideo.classList.remove("is-hidden");
  updateSpriteVideoPlayback();
  applyDialogLayout();
}

async function renderSingleSprite(path: string, scale: number, token: number): Promise<void> {
  spriteVideo.pause();
  spriteVideo.classList.add("is-hidden");
  spriteCanvas.classList.add("is-hidden");
  spriteImage.classList.remove("is-hidden");
  spriteImage.src = await localUrl(path);
  await spriteImage.decode().catch(() => undefined);
  if (token !== spriteLoadToken) return;
  updateSpriteMediaMode(spriteImage, spriteImage.naturalWidth, spriteImage.naturalHeight);
  const wrap = $("#sprite-wrap") as HTMLElement;
  const ratio = Math.min(
    Math.max(0.15, Math.min(3, scale)),
    wrap.clientWidth / Math.max(1, spriteImage.naturalWidth),
    wrap.clientHeight / Math.max(1, spriteImage.naturalHeight),
  );
  spriteImage.style.width = `${Math.round(spriteImage.naturalWidth * ratio)}px`;
  spriteImage.style.height = `${Math.round(spriteImage.naturalHeight * ratio)}px`;
  applyDialogLayout();
}

async function playSystemWelcomeAnimation(): Promise<void> {
  if (state.active_character_name !== "here_system") return;
  if (spriteTimer !== null) window.clearInterval(spriteTimer);
  spriteTimer = null;
  const resolved = await api.backendCall<{ scale: number; sprites: ResolvedSprite[] }>("resolve_assets", {
    character_name: "here_system",
  });
  const welcomeSprite = resolved.sprites.find((item) => item.state_name === "welcome");
  if (!welcomeSprite?.path) return;
  const gifPath = welcomeSprite.path.replace(/\/animations\/welcome\/frame_001\.png$/i, "/animations/welcome.gif");
  const token = ++spriteLoadToken;
  currentEmotion = "welcome";
  await renderSingleSprite(gifPath || systemWelcomeGifPath, Number(resolved.scale || activeCharacter().sprite_scale || 0.3), token);
  if (token !== spriteLoadToken) return;
  window.setTimeout(() => {
    if (token !== spriteLoadToken || state.active_character_name !== "here_system") return;
    currentEmotion = "neutral";
    void renderSprite("neutral");
  }, 5_200);
}

async function renderSpritesheet(sprite: ResolvedSprite, token: number, scale: number): Promise<void> {
  const source = new Image();
  source.crossOrigin = "anonymous";
  source.src = await localUrl(sprite.spritesheet_path || "");
  await source.decode();
  if (token !== spriteLoadToken) return;
  const width = Number(sprite.frame_width || source.width);
  const height = Number(sprite.frame_height || source.height);
  const columns = Math.max(1, Math.floor(source.width / width));
  const count = Math.max(1, Number(sprite.frame_count || columns));
  spriteCanvas.width = width;
  spriteCanvas.height = height;
  const wrap = $("#sprite-wrap") as HTMLElement;
  const ratio = Math.min(scale, wrap.clientWidth / width, wrap.clientHeight / height);
  spriteCanvas.style.width = `${Math.round(width * ratio)}px`;
  spriteCanvas.style.height = `${Math.round(height * ratio)}px`;
  spriteCanvas.classList.remove("is-hidden");
  spriteImage.classList.add("is-hidden");
  applyDialogLayout();
  const context = spriteCanvas.getContext("2d");
  let frameIndex = 0;
  const draw = () => {
    if (!context) return;
    const absolute = Number(sprite.frame_col || 0) + frameIndex;
    const x = (absolute % columns) * width;
    const y = (Number(sprite.frame_row || 0) + Math.floor(absolute / columns)) * height;
    context.clearRect(0, 0, width, height);
    context.drawImage(source, x, y, width, height, 0, 0, width, height);
  };
  draw();
  updateSpriteMediaMode(spriteCanvas, width, height);
  const interval = sprite.fps ? Math.round(1000 / sprite.fps) : Number(sprite.frame_interval_ms || 120);
  if (characterVideoEnabled) {
    spriteTimer = window.setInterval(() => { frameIndex = (frameIndex + 1) % count; draw(); }, Math.max(36, interval));
  }
}

function renderCharacterMenu(): void {
  $("#character-list").innerHTML = state.config.characters.map((character) => `
    <button class="character-option ${character.name === state.active_character_name ? "is-active" : ""}" data-character="${esc(character.name)}" type="button">
      <span class="character-color" style="background:${esc(character.color)}"></span>
      <span>${esc(character.name)}</span>
      ${character.name === state.active_character_name ? '<i data-lucide="check"></i>' : ""}
    </button>`).join("");
  refreshIcons();
}

async function refreshCodexPetCandidates(): Promise<void> {
  const container = document.querySelector<HTMLElement>("#codex-pet-candidates");
  if (!container) return;
  try {
    const candidates = await api.backendCall<string[]>("codex_pet_candidates");
    if (!candidates.length) {
      container.classList.add("is-hidden");
      container.innerHTML = "";
      return;
    }
    container.innerHTML = `<div class="popover-heading">已发现的 Codex Pet</div>${candidates.slice(0, 12).map((path) => {
      const label = String(path).split(/[\\/]/).filter(Boolean).pop() || path;
      return `<button class="popover-action codex-pet-candidate" data-codex-pet-path="${esc(path)}" type="button"><i data-lucide="bot"></i><span>${esc(label)}</span></button>`;
    }).join("")}`;
    container.classList.remove("is-hidden");
    refreshIcons();
  } catch {
    container.classList.add("is-hidden");
  }
}

async function selectCharacter(name: string): Promise<void> {
  characterMenu.classList.add("is-hidden");
  state = await api.setActiveCharacter(name);
  currentEmotion = "neutral";
  dialogName.textContent = name;
  dialogText.textContent = `我在。想聊什么？`;
  await applyState();
  await playSystemWelcomeAnimation();
}

function setBusy(text: string, visible: boolean): void {
  if (state?.config.system_config.process_hint_collapsed || state?.config.system_config.chat_delivery_channel !== "desktop_chat") visible = false;
  busyText.textContent = text;
  const callLayout = stage.classList.contains("call-mode");
  busyBar.classList.toggle("is-hidden", !visible || callLayout);
  dialogPanel.classList.toggle("is-busy", visible && callLayout);
  if (visible && callLayout) {
    dialogPanel.scrollTop = 0;
    dialogPanel.dataset.busyText = text;
    dialogPanel.setAttribute("aria-busy", "true");
  } else {
    delete dialogPanel.dataset.busyText;
    dialogPanel.removeAttribute("aria-busy");
  }
}

function markdownHtml(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { breaks: true }) as string, { USE_PROFILES: { html: true } });
}

function renderDialogText(text: string, animate = true): void {
  if (dialogTypingTimer !== null) window.clearInterval(dialogTypingTimer);
  dialogTypingTimer = null;
  completeDialogTyping = null;
  dialogPanel.scrollTop = 0;
  const finish = () => {
    if (dialogTypingTimer !== null) window.clearInterval(dialogTypingTimer);
    dialogTypingTimer = null;
    dialogText.classList.remove("is-typing");
    dialogText.innerHTML = markdownHtml(text);
    completeDialogTyping = null;
    applyDialogLayout();
  };
  if (!animate || !text || text.length > 1200) { finish(); return; }
  let index = 0;
  dialogText.classList.add("is-typing");
  dialogText.textContent = "";
  completeDialogTyping = finish;
  dialogTypingTimer = window.setInterval(() => {
    index = Math.min(text.length, index + Math.max(1, Math.ceil(text.length / 180)));
    dialogText.textContent = text.slice(0, index);
    applyDialogLayout();
    if (index >= text.length) finish();
  }, 18);
}

async function attachmentsFromFiles(files: File[]): Promise<Attachment[]> {
  const supported = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
  const available = Math.max(0, 4 - attachments.length);
  const selected = files.filter((file) => supported.has(file.type)).slice(0, available);
  return await Promise.all(selected.map(async (file) => {
    if (file.size > 12 * 1024 * 1024) throw new Error(`${file.name} 超过 12 MB。`);
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.addEventListener("load", () => resolve(String(reader.result || "")), { once: true });
      reader.addEventListener("error", () => reject(reader.error || new Error("无法读取图片")), { once: true });
      reader.readAsDataURL(file);
    });
    return { name: file.name || `image-${Date.now()}.png`, mimeType: file.type, dataUrl };
  }));
}

function resizeMessageInput(): void {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(128, messageInput.scrollHeight)}px`;
  applyDialogLayout();
}

async function pauseAsr(reason: "reply" | "audio"): Promise<void> {
  if (!asrRunning) return;
  if (asrPauseGate.pause(reason)) {
    await api.backendCall("pause_asr").catch(() => undefined);
  }
}

async function resumeAsr(reason: "reply" | "audio"): Promise<void> {
  if (!asrRunning) {
    asrPauseGate.resume(reason);
    return;
  }
  if (asrPauseGate.resume(reason)) {
    await api.backendCall("resume_asr").catch(() => undefined);
  }
}

async function pauseAsrForReply(): Promise<void> {
  await pauseAsr("reply");
}

async function resumeAsrAfterReply(): Promise<void> {
  if (!asrPauseGate.has("reply")) return;
  messageInput.value = "";
  asrOriginalText = "";
  resizeMessageInput();
  await resumeAsr("reply");
}

function maybeResumeAsrAfterReply(): void {
  if (chatResponseDone && !audioQueuePlaying && audioQueue.length === 0) {
    void resumeAsrAfterReply();
  }
}

function setAsrUiRunning(running: boolean): void {
  setAsrUiStarting(false);
  asrRunning = running;
  if (!running) {
    asrPauseGate.clear();
    asrOriginalText = "";
  }
  $("#mic-button").classList.toggle("is-active", running);
  updateCallControl($("[data-call-toggle='microphone']") as HTMLButtonElement, !running);
}

function setAsrUiStarting(starting: boolean): void {
  asrStarting = starting;
  const button = $("#mic-button") as HTMLButtonElement;
  button.classList.toggle("is-loading", starting);
  button.setAttribute("aria-busy", String(starting));
  button.title = starting ? "正在启动语音输入" : "语音输入";
  if (starting) setBusy("正在启动语音识别…", true);
  else if (!chatBusy) setBusy("", false);
}

function applyAsrTranscript(rawText: string, final: boolean): void {
  if (!asrRunning || asrPauseGate.paused) return;
  const text = String(rawText || "");
  if (!final && text.startsWith("麦克风输入为空")) {
    setBusy(text, true);
    window.setTimeout(() => {
      if (!chatBusy) setBusy("", false);
    }, 4_200);
    return;
  }
  if (!final) {
    messageInput.value = `${asrOriginalText}${text}`;
    resizeMessageInput();
    return;
  }

  const language = String(
    state.config.system_config.asr_language
      || state.config.system_config.ui_language
      || "zh",
  ).trim().toLowerCase();
  const normalized = language.startsWith("en")
    ? text.trim()
    : text.replace(/\s+/g, "").trim();
  if (!normalized) return;
  const separator = language.startsWith("en") ? " " : "，";
  const built = `${asrOriginalText}${asrOriginalText ? separator : ""}${normalized}`;
  const current = messageInput.value.trim();
  if (current && (current === built.trim() || current.endsWith(normalized))) {
    asrOriginalText = messageInput.value;
  } else {
    messageInput.value = built;
    asrOriginalText = messageInput.value;
  }
  resizeMessageInput();
  void sendMessage();
}

function renderAttachments(): void {
  const strip = $("#attachment-strip") as HTMLElement;
  strip.classList.toggle("is-hidden", attachments.length === 0);
  strip.innerHTML = attachments.map((item, index) => `<div class="attachment-chip"><i data-lucide="image"></i><span>${esc(item.name)}</span><button type="button" data-remove-attachment="${index}">×</button></div>`).join("");
  refreshIcons();
}

async function sendMessage(): Promise<void> {
  if (chatBusy) {
    await api.stopMessage();
    setChatBusy(false);
    setBusy("", false);
    chatResponseDone = true;
    maybeResumeAsrAfterReply();
    return;
  }
  const text = messageInput.value.trim();
  if (!text && !attachments.length) return;
  await pauseAsrForReply();
  chatResponseDone = false;
  const requestId = crypto.randomUUID();
  const outgoing = attachments;
  attachments = [];
  renderAttachments();
  messageInput.value = "";
  resizeMessageInput();
  state.history.push({
    id: crypto.randomUUID(), role: "user", character_name: "你", text: text || "[图片]",
    created_at: new Date().toISOString(), request_id: requestId, attachmentNames: outgoing.map((item) => item.name),
  } as BackendHistoryItem & { attachmentNames: string[] });
  dialogName.textContent = state.active_character_name;
  setDialogVisible(true);
  setBusy("正在等待回复", true);
  setChatBusy(true);
  try {
    await api.sendMessage({ requestId, text, characterName: state.active_character_name, attachments: outgoing });
  } catch (error) {
    setChatBusy(false);
    chatResponseDone = true;
    maybeResumeAsrAfterReply();
    throw error;
  }
}

function setChatBusy(busy: boolean): void {
  chatBusy = busy;
  const button = $("#send-button") as HTMLButtonElement;
  button.title = busy ? "停止生成" : "发送";
  button.innerHTML = `<i data-lucide="${busy ? "square" : "arrow-up"}"></i>`;
  refreshIcons();
}

function handleBackendEvent(message: BackendEvent): void {
  const payload = message.payload as Record<string, unknown>;
  if (message.event === "status") {
    setBusy(String(payload.text || "正在处理"), Boolean(payload.busy));
  } else if (message.event === "chat_start") {
    chatResponseDone = false;
    setChatBusy(true);
    setBusy("正在思考", true);
  } else if (message.event === "dialog") {
    const item = payload as unknown as BackendHistoryItem;
    state.history.push(item);
    dialogName.textContent = item.character_name || state.active_character_name;
    renderDialogText(item.text || "");
    currentEmotion = item.emotion || "neutral";
    setDialogVisible(true);
    void renderSprite(currentEmotion, item.asset_id);
    const effect = String(payload.effect || "").toUpperCase();
    if (effect === "LEAVE") spriteWrap.classList.add("is-hidden");
    else if (effect === "ENTER") spriteWrap.classList.remove("is-hidden");
    applyDialogLayout();
    window.setTimeout(() => { currentEmotion = "neutral"; void renderSprite("neutral"); }, 3_000);
  } else if (message.event === "chat_done") {
    setChatBusy(false);
    setBusy("", false);
    chatResponseDone = true;
    maybeResumeAsrAfterReply();
  } else if (message.event === "chat_error" || message.event === "fatal") {
    setChatBusy(false);
    dialogText.textContent = String(payload.message || "处理失败");
    setBusy("", false);
    chatResponseDone = true;
    maybeResumeAsrAfterReply();
  } else if (message.event === "audio") {
    if (audioEnabled && payload.path) {
      audioQueue.push(String(payload.path));
      void drainAudioQueue();
    }
  } else if (message.event === "options") {
    const options = Array.isArray(payload.options) ? payload.options.map(String) : [];
    const panel = $("#options-panel");
    panel.innerHTML = options.map((option) => `<button class="option-button" type="button" data-option="${esc(option)}">${esc(option)}</button>`).join("");
    panel.classList.toggle("is-hidden", options.length === 0);
    setDialogVisible(false);
  } else if (message.event === "numeric") {
    const panel = $("#numeric-panel");
    panel.textContent = String(payload.text || "");
    panel.classList.toggle("is-hidden", !payload.text);
  } else if (message.event === "background") {
    if (payload.path) void setRuntimeBackground(String(payload.path));
  } else if (message.event === "bgm") {
    void setRuntimeBgm(String(payload.path || ""));
  } else if (message.event === "cg") {
    if (payload.path) {
      if (Boolean(payload.background_only)) {
        $("#cg-layer").classList.add("is-hidden");
        void setRuntimeBackground(String(payload.path));
      } else {
        void showCg(String(payload.path));
      }
    }
  } else if (message.event === "transcript") {
    applyAsrTranscript(String(payload.text || ""), Boolean(payload.final));
  } else if (message.event === "asr_state") {
    setAsrUiRunning(Boolean(payload.running));
  } else if (message.event === "character") {
    state.active_character_name = String(payload.name || state.active_character_name);
    void applyState().then(playSystemWelcomeAnimation);
  } else if (message.event === "history_reverted") {
    const history = Array.isArray(payload.history) ? payload.history as unknown as BackendHistoryItem[] : [];
    state.history = history;
    const display = payload.display as BackendHistoryItem | undefined;
    dialogName.textContent = display?.character_name || state.active_character_name;
    renderDialogText(display?.text || "我在。想聊什么？", false);
    currentEmotion = display?.emotion || "neutral";
    renderHistory();
    void renderSprite(currentEmotion, display?.asset_id);
  }
}

async function playAudio(path: string): Promise<void> {
  const audio = new Audio(await localUrl(path));
  currentAudio = audio;
  const character = activeCharacter();
  audio.volume = Math.max(0, Math.min(1, Number(character.speech_volume || 1)));
  await waitForAudioEnd(audio, (finish) => {
    const registered = () => {
      if (finishCurrentAudio === registered) finishCurrentAudio = null;
      finish();
    };
    finishCurrentAudio = registered;
  });
  if (currentAudio === audio) currentAudio = null;
}

async function drainAudioQueue(): Promise<void> {
  if (audioQueuePlaying || !audioEnabled || audioQueue.length === 0) return;
  audioQueuePlaying = true;
  await pauseAsr("audio");
  try {
    while (audioEnabled && audioQueue.length) await playAudio(audioQueue.shift()!);
  } finally {
    audioQueuePlaying = false;
    await resumeAsr("audio");
    maybeResumeAsrAfterReply();
  }
}

async function setRuntimeBackground(path: string): Promise<void> {
  const image = $("#background-image") as HTMLImageElement;
  image.src = await localUrl(path);
  image.classList.remove("is-hidden");
}

async function setRuntimeBgm(path: string): Promise<void> {
  backgroundAudio?.pause();
  backgroundAudio = null;
  if (!path) return;
  backgroundAudio = new Audio(await localUrl(path));
  backgroundAudio.loop = true;
  backgroundAudio.volume = Math.max(0, Math.min(1, state.config.system_config.music_volumn / 100));
  await backgroundAudio.play().catch(() => undefined);
}

async function showCg(path: string): Promise<void> {
  const layer = $("#cg-layer");
  currentCgPath = path;
  ($("#cg-image") as HTMLImageElement).src = await localUrl(path);
  layer.classList.remove("is-hidden");
}

function renderHistory(): void {
  const list = $("#history-list");
  if (!state.history.length) {
    list.innerHTML = '<div class="empty-state">暂无对话</div>';
    return;
  }
  list.innerHTML = state.history.slice().reverse().map((item) => {
    const date = new Date(item.created_at);
    return `<article class="history-item"><div class="history-meta"><strong>${esc(item.character_name)}</strong><span>${esc(date.toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }))}</span>${item.role === "user" ? `<button class="history-revert" data-revert-history="${esc(item.id)}" type="button">回到这里</button>` : ""}</div><p>${esc(item.text)}</p></article>`;
  }).join("");
}

async function revertHistory(messageId: string): Promise<void> {
  if (!window.confirm("回滚到这条消息之前？之后的对话会从当前记录中移除。")) return;
  try {
    const result = await api.backendCall<{ history: BackendHistoryItem[]; display?: BackendHistoryItem }>("revert_history", { user_message_id: messageId });
    state.history = result.history;
    renderHistory();
  } catch (error) {
    dialogText.textContent = error instanceof Error ? error.message : String(error);
  }
}

function renderLife(): void {
  const source = currentLifeTab === "life" ? state.life_plan : state.contact_plan;
  const items = currentLifeTab === "life"
    ? (source?.blocks as Array<Record<string, unknown>> || [])
    : (source?.contacts as Array<Record<string, unknown>> || []);
  const content = $("#life-content");
  if (!items.length) { content.innerHTML = '<div class="empty-state">暂无计划</div>'; return; }
  content.innerHTML = items.map((item) => {
    const time = currentLifeTab === "life" ? `${item.start || ""} - ${item.end || ""}` : `${item.window_start || ""} - ${item.window_end || ""}`;
    const title = currentLifeTab === "life" ? item.activity : item.intent;
    const detail = currentLifeTab === "life"
      ? [item.location, item.mood, item.availability].filter(Boolean).join(" · ")
      : [item.type, item.status, item.delivery_channel].filter(Boolean).join(" · ");
    return `<article class="timeline-item"><span class="timeline-time">${esc(time)}</span><h3>${esc(title)}</h3><p>${esc(detail)}</p></article>`;
  }).join("");
}

async function toggleAsr(): Promise<void> {
  if (asrStarting) return;
  try {
    if (asrRunning) {
      const result = await api.backendCall<{ status: string }>("stop_asr");
      setAsrUiRunning(result.status === "Running");
    } else {
      asrOriginalText = messageInput.value;
      asrPauseGate.clear();
      setAsrUiStarting(true);
      const result = await api.backendCall<{ status: string }>("start_asr", {}, 180_000);
      setAsrUiRunning(result.status === "Running");
    }
  } catch (error) {
    setAsrUiStarting(false);
    setBusy(error instanceof Error ? error.message : String(error), true);
    setTimeout(() => setBusy("", false), 4200);
  }
}

async function persistDisplayState(patch: Record<string, unknown>): Promise<void> {
  const system = clone(state.config.system_config);
  Object.assign(system, patch);
  state = await api.saveConfig({ system_config: system });
  await applyState();
}

function showContextMenu(event: MouseEvent): void {
  const target = event.target as Element;
  const actionMarkup = target.closest("#dialog-panel, #dialog-caption")
    ? `<button class="popover-action" data-context-action="dialog" type="button"><i data-lucide="message-circle"></i><span>${state.config.system_config.dialog_box_collapsed ? "显示对白" : "收起对白"}</span></button>
       <button class="popover-action" data-context-action="process" type="button"><i data-lucide="loader-circle"></i><span>${state.config.system_config.process_hint_collapsed ? "显示过程状态" : "收起过程状态"}</span></button>`
    : target.closest("#mic-button")
      ? `<button class="popover-action" data-context-action="asr" type="button"><i data-lucide="mic"></i><span>打开 ASR 设置</span></button>`
      : target.closest("#composer")
        ? `<button class="popover-action" data-context-action="input" type="button"><i data-lucide="text-cursor-input"></i><span>${state.config.system_config.input_bar_collapsed ? "显示输入栏" : "收起输入栏"}</span></button>`
        : `<button class="popover-action" data-context-action="settings" type="button"><i data-lucide="settings-2"></i><span>打开设置</span></button>`;
  contextMenu.innerHTML = actionMarkup;
  const stageRect = stage.getBoundingClientRect();
  contextMenu.style.left = `${Math.max(8, Math.min(stageRect.width - 258, event.clientX - stageRect.left))}px`;
  contextMenu.style.top = `${Math.max(8, Math.min(stageRect.height - 64, event.clientY - stageRect.top))}px`;
  contextMenu.classList.remove("is-hidden");
  refreshIcons();
}

function wireEvents(): void {
  api.onBackendEvent(handleBackendEvent);
  const setChromeVisible = (visible: boolean): void => {
    stage.classList.toggle("chrome-visible", visible);
    if (!visible) {
      characterMenu.classList.add("is-hidden");
      callTools.classList.add("is-hidden");
      contextMenu.classList.add("is-hidden");
    }
  };
  app.addEventListener("contextmenu", (event) => {
    const target = event.target as Element;
    // Native dialog controls retain the browser's copy/paste context menu.
    if (target.closest("dialog")) return;
    event.preventDefault();
    showContextMenu(event);
  });
  stage.addEventListener("pointerdown", (event) => {
    contextMenu.classList.add("is-hidden");
    if (event.button !== 0 || !stage.classList.contains("chrome-visible")) return;
    if ((event.target as Element).closest(".titlebar, #character-menu")) return;
    setChromeVisible(false);
  });
  $("#settings-button").addEventListener("click", () => {
    setChromeVisible(false);
    openSettings();
  });
  $("#call-back").addEventListener("click", () => api.windowAction("minimize"));
  $("#call-participants").addEventListener("click", () => {
    callTools.classList.add("is-hidden");
    characterMenu.classList.toggle("is-hidden");
  });
  $("#call-more").addEventListener("click", () => {
    characterMenu.classList.add("is-hidden");
    callTools.classList.toggle("is-hidden");
  });
  callTools.addEventListener("click", (event) => {
    const action = (event.target as Element).closest<HTMLElement>("[data-call-action]")?.dataset.callAction;
    if (!action) return;
    callTools.classList.add("is-hidden");
    if (action === "history") { renderHistory(); historyDialog.showModal(); }
    if (action === "life") { renderLife(); lifeDialog.showModal(); }
    if (action === "settings") openSettings();
  });
  $$("[data-call-toggle]").forEach((button) => button.addEventListener("click", () => {
    const control = button as HTMLButtonElement;
    const kind = control.dataset.callToggle;
    if (kind === "camera") {
      spriteWrap.classList.toggle("is-mirrored");
      control.setAttribute("aria-pressed", String(spriteWrap.classList.contains("is-mirrored")));
      return;
    }
    if (kind === "microphone") {
      void toggleAsr().then(() => updateCallControl(control, !asrRunning));
      return;
    }
    const isOff = !control.classList.contains("is-off");
    if (kind === "video") {
      characterVideoEnabled = !isOff;
      void renderSprite("neutral");
    }
    if (kind === "speaker") {
      audioEnabled = !isOff;
      $("#speaker-button").classList.toggle("is-active", audioEnabled);
      if (isOff) {
        audioQueue.length = 0;
        currentAudio?.pause();
        finishCurrentAudio?.();
      } else {
        void drainAudioQueue();
      }
    }
    updateCallControl(control, isOff);
  }));
  $("#call-end").addEventListener("click", () => {
    void (async () => {
      if (audioEnabled) {
        audioEnabled = false;
        $("#speaker-button").classList.remove("is-active");
        audioQueue.length = 0;
        currentAudio?.pause();
        finishCurrentAudio?.();
        updateCallControl($("[data-call-toggle='speaker']") as HTMLButtonElement, true);
      }
      await api.windowAction("close");
    })();
  });
  $("#pin-button").addEventListener("click", async () => {
    state.window.always_on_top = await api.windowAction("toggle-pin");
    $("#pin-button").classList.toggle("is-active", state.window.always_on_top);
  });
  $("#minimize-button").addEventListener("click", () => api.windowAction("minimize"));
  $("#close-button").addEventListener("click", () => api.windowAction("close"));
  $("#character-button").addEventListener("click", () => {
    characterMenu.classList.toggle("is-hidden");
    if (!characterMenu.classList.contains("is-hidden")) void refreshCodexPetCandidates();
  });
  characterMenu.addEventListener("click", (event) => {
    const target = (event.target as Element).closest<HTMLElement>("[data-character], [data-action], [data-codex-pet-path]");
    if (!target) return;
    if (target.dataset.character) void selectCharacter(target.dataset.character);
    if (target.dataset.action === "new-character") { characterMenu.classList.add("is-hidden"); openCreateCharacter(); }
    if (target.dataset.action === "import-codex") { characterMenu.classList.add("is-hidden"); void importCodexPet(); }
    if (target.dataset.action === "memory") { characterMenu.classList.add("is-hidden"); openSettings("memory"); }
    if (target.dataset.codexPetPath) { characterMenu.classList.add("is-hidden"); void importCodexPet(target.dataset.codexPetPath); }
  });
  document.addEventListener("click", (event) => {
    if (!(event.target as Element).closest("#context-menu")) contextMenu.classList.add("is-hidden");
    if (!(event.target as Element).closest("#character-menu, #character-button, #call-participants")) characterMenu.classList.add("is-hidden");
    if (!(event.target as Element).closest("#call-tools, #call-more")) callTools.classList.add("is-hidden");
  });
  contextMenu.addEventListener("click", (event) => {
    const action = (event.target as Element).closest<HTMLElement>("[data-context-action]")?.dataset.contextAction;
    if (!action) return;
    contextMenu.classList.add("is-hidden");
    if (action === "settings") openSettings();
    else if (action === "asr") openSettings("asr");
    else if (action === "dialog") void persistDisplayState({ dialog_box_collapsed: !state.config.system_config.dialog_box_collapsed });
    else if (action === "process") void persistDisplayState({ process_hint_collapsed: !state.config.system_config.process_hint_collapsed });
    else if (action === "input") void persistDisplayState({ input_bar_collapsed: !state.config.system_config.input_bar_collapsed });
  });
  $("#send-button").addEventListener("click", sendMessage);
  messageInput.addEventListener("input", resizeMessageInput);
  messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(); }
  });
  messageInput.addEventListener("paste", (event) => {
    const files = Array.from(event.clipboardData?.files || []);
    if (!files.some((file) => file.type.startsWith("image/"))) return;
    event.preventDefault();
    void attachmentsFromFiles(files).then((items) => {
      attachments.push(...items);
      renderAttachments();
    }).catch((error) => setBusy(error instanceof Error ? error.message : String(error), true));
  });
  for (const eventName of ["dragenter", "dragover"]) {
    messageInput.addEventListener(eventName, (event) => {
      const dragEvent = event as DragEvent;
      if (Array.from(dragEvent.dataTransfer?.items || []).some((item) => item.kind === "file" && item.type.startsWith("image/"))) {
        dragEvent.preventDefault();
        dragEvent.dataTransfer!.dropEffect = "copy";
      }
    });
  }
  messageInput.addEventListener("drop", (event) => {
    const files = Array.from(event.dataTransfer?.files || []);
    if (!files.some((file) => file.type.startsWith("image/"))) return;
    event.preventDefault();
    void attachmentsFromFiles(files).then((items) => {
      attachments.push(...items);
      renderAttachments();
    }).catch((error) => setBusy(error instanceof Error ? error.message : String(error), true));
  });
  $("#attach-button").addEventListener("click", async () => {
    attachments.push(...await api.chooseImages());
    attachments = attachments.slice(0, 4);
    renderAttachments();
  });
  $("#attachment-strip").addEventListener("click", (event) => {
    const button = (event.target as Element).closest<HTMLElement>("[data-remove-attachment]");
    if (!button) return;
    attachments.splice(Number(button.dataset.removeAttachment), 1);
    renderAttachments();
  });
  $("#options-panel").addEventListener("click", (event) => {
    const option = (event.target as Element).closest<HTMLElement>("[data-option]")?.dataset.option;
    if (!option) return;
    $("#options-panel").classList.add("is-hidden");
    setDialogVisible(true);
    messageInput.value = option;
    void sendMessage();
  });
  $("#close-cg").addEventListener("click", () => $("#cg-layer").classList.add("is-hidden"));
  $("#save-cg").addEventListener("click", async () => {
    if (currentCgPath) await api.saveAsset(currentCgPath);
  });
  $("#mic-button").addEventListener("click", toggleAsr);
  dialogPanel.addEventListener("click", () => {
    if (suppressDialogClick) {
      suppressDialogClick = false;
      return;
    }
    // Qt's dialog label click only skips typing/audio. Collapsing is an
    // explicit action (the chevron or context menu), so a normal click must
    // leave the conversation visible.
    completeDialogTyping?.();
    currentAudio?.pause();
    finishCurrentAudio?.();
  });
  dialogPanel.addEventListener("pointerdown", beginDialogResize);
  dialogPanel.addEventListener("pointermove", (event) => {
    if (dialogResizeSession) applyDialogResize(event);
    else updateDialogResizeCursor(event);
  });
  dialogPanel.addEventListener("pointerup", endDialogResize);
  dialogPanel.addEventListener("pointercancel", endDialogResize);
  dialogPanel.addEventListener("pointerleave", () => {
    if (!dialogResizeSession) dialogPanel.style.cursor = "default";
  });
  $("#speaker-button").addEventListener("click", () => {
    audioEnabled = !audioEnabled;
    $("#speaker-button").classList.toggle("is-active", audioEnabled);
    if (!audioEnabled) {
      audioQueue.length = 0;
      currentAudio?.pause();
      finishCurrentAudio?.();
    } else {
      void drainAudioQueue();
    }
  });
  $("#collapse-dialog").addEventListener("click", () => {
    setDialogVisible(false);
    $("#restore-dialog").classList.remove("is-hidden");
  });
  $("#restore-dialog").addEventListener("click", () => {
    setDialogVisible(true);
    $("#restore-dialog").classList.add("is-hidden");
  });
  $("#history-button").addEventListener("click", () => { renderHistory(); historyDialog.showModal(); });
  $("#history-list").addEventListener("click", (event) => {
    const id = (event.target as Element).closest<HTMLElement>("[data-revert-history]")?.dataset.revertHistory;
    if (id) void revertHistory(id);
  });
  $("#life-button").addEventListener("click", () => { renderLife(); lifeDialog.showModal(); });
  $("#settings-tabs").addEventListener("click", (event) => {
    const tab = (event.target as Element).closest<HTMLElement>("[data-tab]")?.dataset.tab;
    if (tab) showSettingsPage(tab);
  });
  $("#save-settings").addEventListener("click", saveSettings);
  $("#create-character-form").addEventListener("click", async (event) => {
    const profileTab = (event.target as Element).closest<HTMLElement>("[data-create-profile-tab]")?.dataset.createProfileTab;
    if (profileTab) {
      showCreateProfilePage(profileTab);
      return;
    }
    const mbti = (event.target as Element).closest<HTMLElement>("[data-create-mbti]")?.dataset.createMbti;
    if (mbti) {
      selectedCreateMbti = mbti;
      $$<HTMLElement>("[data-create-mbti]").forEach((button) => button.classList.toggle("is-active", button.dataset.createMbti === mbti));
      syncCreateProfilePreview();
      return;
    }
    const openState = (event.target as Element).closest<HTMLElement>("[data-open-create-state]")?.dataset.openCreateState;
    if (openState) { await openCreateStateAsset(openState); return; }
    const imageState = (event.target as Element).closest<HTMLElement>("[data-choose-create-image]")?.dataset.chooseCreateImage;
    if (imageState) { await chooseCreateStateAsset(imageState, "character_image"); return; }
    const animationState = (event.target as Element).closest<HTMLElement>("[data-choose-create-animation]")?.dataset.chooseCreateAnimation;
    if (animationState) { await chooseCreateStateAsset(animationState, "character_animation"); return; }
    const clearState = (event.target as Element).closest<HTMLElement>("[data-clear-create-state]")?.dataset.clearCreateState;
    if (clearState) { clearCreateStateAsset(clearState); return; }
  });
  $("#create-character-form").addEventListener("input", (event) => {
    if ((event.target as Element).id === "create-character-setting") {
      if (!updatingGeneratedCharacterSetting) lastGeneratedCharacterSetting = "";
      return;
    }
    if ((event.target as Element).matches("[data-create-state-path], [data-create-state-interval], #create-character-visual")) return;
    syncCreateProfilePreview();
  });
  $("#regenerate-character-setting").addEventListener("click", () => syncCreateProfilePreview(true));
  $("#create-character-form").addEventListener("submit", (event) => { event.preventDefault(); void createCharacter(); });
  $$(".dialog-close").forEach((button) => button.addEventListener("click", () => (button.closest("dialog") as HTMLDialogElement)?.close()));
  $("#copy-history").addEventListener("click", () => api.copyHistory());
  $("#clear-history").addEventListener("click", async () => { await api.clearHistory(); state.history = []; renderHistory(); });
  $$("[data-life-tab]").forEach((button) => button.addEventListener("click", () => {
    currentLifeTab = (button as HTMLElement).dataset.lifeTab as "life" | "contact";
    $$("[data-life-tab]").forEach((item) => item.classList.toggle("is-active", item === button));
    renderLife();
  }));
  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    characterMenu.classList.add("is-hidden");
    callTools.classList.add("is-hidden");
    setChromeVisible(false);
  });
  window.addEventListener("resize", applyDialogLayout);
}

async function boot(): Promise<void> {
  refreshIcons();
  wireEvents();
  observeLocale(document.body);
  try {
    state = await api.getState();
    await applyState();
    const last = [...state.history].reverse().find((item) => item.role === "assistant" && item.character_name === state.active_character_name);
    renderDialogText(last?.text || "我在。想聊什么？", false);
    dialogName.textContent = last?.character_name || state.active_character_name;
    currentEmotion = last?.emotion || "neutral";
    app.classList.remove("is-loading");
    void playSystemWelcomeAnimation();
  } catch (error) {
    dialogText.textContent = error instanceof Error ? error.message : String(error);
    $("#backend-name").textContent = "offline";
    app.classList.remove("is-loading");
  }
}

void boot();
