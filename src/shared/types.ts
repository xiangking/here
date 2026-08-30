export type Emotion = "neutral" | "happy" | "thinking" | "surprised" | "sad" | "angry";

export interface SpriteSource {
  kind: "frames" | "static" | "custom";
  paths: string[];
  frameIntervalMs: number;
}

export interface Character {
  id: string;
  name: string;
  color: string;
  profile: string;
  visualIdentity: string;
  scale: number;
  sprite: SpriteSource;
  emotionSprites?: Partial<Record<Emotion, string>>;
}

export interface ApiSettings {
  provider: "openai-compatible";
  model: string;
  baseUrl: string;
  apiKey: string;
  temperature: number;
  stream: boolean;
}

export interface SystemSettings {
  activeCharacterId: string;
  language: "zh-CN" | "en" | "ja";
  alwaysOnTop: boolean;
  closeToTray: boolean;
  launchAtLogin: boolean;
  fontScale: number;
  volume: number;
  speakReplies: boolean;
  showDialog: boolean;
  showProcessHint: boolean;
  showInput: boolean;
}

export interface ProactiveSettings {
  enabled: boolean;
  intervalHours: number;
  quietHours: string;
  dailyLimit: number;
}

export interface AppConfig {
  version: 1;
  api: ApiSettings;
  system: SystemSettings;
  proactive: ProactiveSettings;
  characters: Character[];
}

export interface Attachment {
  name: string;
  mimeType: string;
  dataUrl: string;
}

export interface ChatMessage {
  id: string;
  characterId: string;
  role: "user" | "assistant";
  text: string;
  emotion?: Emotion;
  attachmentNames?: string[];
  createdAt: string;
}

export interface ChatRequest {
  requestId: string;
  text: string;
  characterId: string;
  attachments: Attachment[];
}

export type ChatEvent =
  | { requestId: string; type: "start" }
  | { requestId: string; type: "delta"; delta: string }
  | { requestId: string; type: "done"; text: string; emotion: Emotion }
  | { requestId: string; type: "error"; message: string };

export interface AppState {
  config: AppConfig;
  history: ChatMessage[];
  platform: NodeJS.Platform;
  appVersion: string;
}

export interface LegacyImportReport {
  sourcePath: string;
  charactersImported: number;
  settingsImported: boolean;
  warnings: string[];
}

import type { BackendEvent, DesktopState } from "./backend-types";

export interface HereDesktopApi {
  getState: () => Promise<DesktopState>;
  backendCall: <T>(method: string, params?: Record<string, unknown>, timeoutMs?: number) => Promise<T>;
  saveConfig: (config: Record<string, unknown>) => Promise<DesktopState>;
  setActiveCharacter: (name: string) => Promise<DesktopState>;
  sendMessage: (request: {
    requestId: string;
    text: string;
    characterName: string;
    attachments: Attachment[];
  }) => Promise<void>;
  stopMessage: () => Promise<void>;
  chooseImages: () => Promise<Attachment[]>;
  captureScreenshots: () => Promise<Attachment[]>;
  chooseFiles: (kind: "background" | "bgm" | "reference" | "character_assets" | "character_image" | "character_animation" | "audio" | "directory") => Promise<string[]>;
  openPath: (path: string) => Promise<string>;
  saveAsset: (sourcePath: string) => Promise<string>;
  clearHistory: () => Promise<[]>;
  copyHistory: () => Promise<void>;
  importLegacy: () => Promise<LegacyImportReport | null>;
  importCodexPet: () => Promise<unknown | null>;
  localFileUrl: (path: string) => Promise<string>;
  windowAction: (action: "minimize" | "hide" | "close" | "toggle-pin") => Promise<boolean>;
  setIgnoreMouseEvents: (ignore: boolean, forward?: boolean) => void;
  onBackendEvent: (listener: (event: BackendEvent) => void) => () => void;
}
