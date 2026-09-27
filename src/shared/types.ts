import type { BackendEvent, DesktopState } from "./backend-types";

export interface Attachment {
  name: string;
  mimeType: string;
  dataUrl: string;
}

export interface LegacyImportReport {
  sourcePath: string;
  charactersImported: number;
  settingsImported: boolean;
  warnings: string[];
}

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
