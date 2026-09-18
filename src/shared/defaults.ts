import type { AppConfig, Character, Emotion } from "./types";

const systemEmotions: Record<Emotion, string> = {
  neutral: "assets/characters/system/system_sprite_neutral.png",
  happy: "assets/characters/system/system_sprite_happy.png",
  thinking: "assets/characters/system/system_sprite_thinking.png",
  surprised: "assets/characters/system/system_sprite_surprised.png",
  sad: "assets/characters/system/system_sprite_sad.png",
  angry: "assets/characters/system/system_sprite_angry.png",
};

export const defaultCharacters: Character[] = [
  {
    id: "here",
    name: "here",
    color: "#f4a7b9",
    profile:
      "你是住在用户桌面上的 AI 伴侣 here。自然、温柔、有自己的生活节奏；记住上下文，但不要声称拥有未提供的事实。回答简洁、真诚，默认使用用户的语言。",
    visualIdentity: "自然、亲切的年轻女性桌面伴侣，白色衬衫，写实风格。",
    scale: 0.92,
    sprite: { kind: "static", paths: ["assets/characters/here/here_neutral.png"], frameIntervalMs: 120 },
  },
  {
    id: "here-system",
    name: "here_system",
    color: "#84c2d5",
    profile:
      "你是 here 的系统设置助手。清楚、温和、简洁地帮助用户理解设置和排查问题，不伪装成普通聊天角色。",
    visualIdentity: "可靠、干净、亲切的桌面设置助手。",
    scale: 0.72,
    sprite: { kind: "static", paths: [systemEmotions.neutral], frameIntervalMs: 120 },
    emotionSprites: systemEmotions,
  },
];

export const createDefaultConfig = (): AppConfig => ({
  version: 1,
  api: {
    provider: "openai-compatible",
    model: process.env.HERE_API_MODEL || "gpt-4o-mini",
    baseUrl: process.env.HERE_API_BASE_URL || "https://api.openai.com/v1",
    apiKey: "",
    temperature: 0.8,
    stream: true,
  },
  system: {
    activeCharacterId: "here",
    language: "zh-CN",
    alwaysOnTop: true,
    closeToTray: true,
    launchAtLogin: false,
    fontScale: 1,
    volume: 0.75,
    speakReplies: false,
    showDialog: true,
    showProcessHint: true,
    showInput: true,
  },
  proactive: {
    enabled: false,
    intervalHours: 6,
    quietHours: "23:00-09:00",
    dailyLimit: 1,
  },
  characters: defaultCharacters.map((character) => structuredClone(character)),
});
