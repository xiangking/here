import type { BackendCharacter, DesktopState } from "../shared/backend-types";
import { isVideoSprite } from "./sprite-media";
import {
  editableChoiceField,
  esc,
  field,
  pageHeader,
  pathField,
  selectField,
  switchRow,
} from "./dom";

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

export function adapterLabel(kind: "tts" | "asr" | "t2i", provider: string): string {
  return adapterLabels[kind][provider] || provider.replaceAll("_", "-");
}

export function schemaFields(
  state: DesktopState,
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

export function deliveryOptions(state: DesktopState): Array<[string, string]> {
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

export function renderPlatformSettings(state: DesktopState): string {
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

export function profileMap(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function profileText(value: unknown, fallback = ""): string {
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

export function renderCharacterSettings(state: DesktopState, character: BackendCharacter): string {
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

export function spriteStateName(sprite: Record<string, unknown>, index: number): string {
  return String(sprite.state_name || sprite.source_state || `custom_${index + 1}`).trim();
}

export function spriteStateLabel(stateName: string): string {
  return spriteStateLabels[stateName] || stateName || "未命名状态";
}

export function renderSpriteEditor(sprite: Record<string, unknown>, index: number, fixed = false): string {
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

export function renderSpriteSettings(state: DesktopState, character: BackendCharacter): string {
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

export function renderMemorySettings(state: DesktopState): string {
  return pageHeader("记忆", `与 ${state.active_character_name} 隔离保存的长期内容`) + `
    <div class="form-section"><h3>角色记忆</h3>
      ${field("memory-character", "MEMORY.md", state.memory.character.join("\n---\n"), { type: "textarea", wide: true, rows: 10, placeholder: "暂无角色记忆" })}
    </div>
    <div class="form-section"><h3>你的档案</h3>
      ${field("memory-user", "长期印象", state.memory.user.join("\n---\n"), { type: "textarea", wide: true, rows: 8, placeholder: "暂时还没有记录" })}
    </div>`;
}

export function renderStorageSettings(state: DesktopState): string {
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
