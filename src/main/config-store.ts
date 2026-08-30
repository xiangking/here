import { app, safeStorage } from "electron";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { createDefaultConfig } from "../shared/defaults";
import type { AppConfig, ChatMessage } from "../shared/types";

interface StoredConfig extends Omit<AppConfig, "api"> {
  api: Omit<AppConfig["api"], "apiKey"> & {
    apiKeyEncrypted?: string;
    apiKeyPlaintext?: string;
  };
}

function clamp(value: unknown, minimum: number, maximum: number, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.min(maximum, Math.max(minimum, parsed)) : fallback;
}

export function mergeConfig(candidate: Partial<AppConfig> | null | undefined): AppConfig {
  const defaults = createDefaultConfig();
  const api = candidate?.api || defaults.api;
  const system = candidate?.system || defaults.system;
  const proactive = candidate?.proactive || defaults.proactive;
  const candidateCharacters = Array.isArray(candidate?.characters)
    ? candidate.characters.filter((item) => item && item.id && item.name && item.sprite?.paths?.length)
    : [];
  const characters = candidateCharacters.length ? candidateCharacters : defaults.characters;
  const activeCharacterId = characters.some((item) => item.id === system.activeCharacterId)
    ? system.activeCharacterId
    : characters[0].id;

  return {
    version: 1,
    api: {
      ...defaults.api,
      ...api,
      baseUrl: String(api.baseUrl || defaults.api.baseUrl).trim(),
      model: String(api.model || defaults.api.model).trim(),
      apiKey: String(api.apiKey || ""),
      temperature: clamp(api.temperature, 0, 2, defaults.api.temperature),
    },
    system: {
      ...defaults.system,
      ...system,
      activeCharacterId,
      fontScale: clamp(system.fontScale, 0.75, 1.4, 1),
      volume: clamp(system.volume, 0, 1, 0.75),
    },
    proactive: {
      ...defaults.proactive,
      ...proactive,
      intervalHours: clamp(proactive.intervalHours, 1, 72, 6),
      dailyLimit: Math.round(clamp(proactive.dailyLimit, 1, 12, 1)),
      quietHours: /^\d{2}:\d{2}-\d{2}:\d{2}$/.test(String(proactive.quietHours || ""))
        ? String(proactive.quietHours)
        : defaults.proactive.quietHours,
    },
    characters,
  };
}

export class ConfigStore {
  readonly root: string;
  readonly characterAssetsRoot: string;
  private readonly configPath: string;
  private readonly historyPath: string;
  private configCache: AppConfig | null = null;

  constructor(root = app.getPath("userData")) {
    this.root = root;
    this.characterAssetsRoot = join(root, "characters");
    this.configPath = join(root, "config.json");
    this.historyPath = join(root, "history.json");
  }

  async initialize(): Promise<void> {
    await mkdir(this.characterAssetsRoot, { recursive: true });
    await this.loadConfig();
  }

  async loadConfig(): Promise<AppConfig> {
    if (this.configCache) return structuredClone(this.configCache);
    let stored: StoredConfig | null = null;
    try {
      stored = JSON.parse(await readFile(this.configPath, "utf8")) as StoredConfig;
    } catch {
      stored = null;
    }

    const candidate = stored as unknown as Partial<AppConfig> | null;
    const config = mergeConfig(candidate);
    if (stored?.api?.apiKeyEncrypted && safeStorage.isEncryptionAvailable()) {
      try {
        config.api.apiKey = safeStorage.decryptString(
          Buffer.from(stored.api.apiKeyEncrypted, "base64"),
        );
      } catch {
        config.api.apiKey = "";
      }
    } else if (stored?.api?.apiKeyPlaintext) {
      config.api.apiKey = stored.api.apiKeyPlaintext;
    }
    this.configCache = config;
    if (!stored) await this.saveConfig(config);
    return structuredClone(config);
  }

  async saveConfig(candidate: AppConfig): Promise<AppConfig> {
    const config = mergeConfig(candidate);
    const { apiKey, ...safeApi } = config.api;
    const stored: StoredConfig = {
      ...config,
      api: safeStorage.isEncryptionAvailable() && apiKey
        ? {
            ...safeApi,
            apiKeyEncrypted: safeStorage.encryptString(apiKey).toString("base64"),
          }
        : { ...safeApi, apiKeyPlaintext: apiKey },
    };
    await this.atomicWrite(this.configPath, JSON.stringify(stored, null, 2));
    this.configCache = config;
    return structuredClone(config);
  }

  async loadHistory(): Promise<ChatMessage[]> {
    try {
      const history = JSON.parse(await readFile(this.historyPath, "utf8"));
      return Array.isArray(history) ? history.slice(-500) : [];
    } catch {
      return [];
    }
  }

  async saveHistory(history: ChatMessage[]): Promise<void> {
    await this.atomicWrite(this.historyPath, JSON.stringify(history.slice(-500), null, 2));
  }

  async appendHistory(message: ChatMessage): Promise<ChatMessage[]> {
    const history = await this.loadHistory();
    history.push(message);
    await this.saveHistory(history);
    return history;
  }

  async clearHistory(): Promise<void> {
    await this.saveHistory([]);
  }

  private async atomicWrite(path: string, contents: string): Promise<void> {
    await mkdir(dirname(path), { recursive: true });
    const temporaryPath = `${path}.tmp`;
    await writeFile(temporaryPath, contents, { encoding: "utf8", mode: 0o600 });
    await rename(temporaryPath, path);
  }
}
