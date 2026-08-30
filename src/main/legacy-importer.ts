import { copyFile, mkdir, readFile, stat } from "node:fs/promises";
import { basename, dirname, extname, join, relative, resolve, sep } from "node:path";
import YAML from "yaml";
import type { BrowserWindow } from "electron";
import { dialog } from "electron";
import type { AppConfig, Character, LegacyImportReport } from "../shared/types";
import { ConfigStore } from "./config-store";

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff-]+/g, "-").replace(/^-|-$/g, "") || "character";
}

async function exists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function readYaml(path: string): Promise<unknown> {
  return YAML.parse(await readFile(path, "utf8"));
}

async function locateRoots(selection: string): Promise<{ dataRoot: string; repoRoot: string } | null> {
  const candidates = [
    { dataRoot: join(selection, ".local", "here"), repoRoot: selection },
    { dataRoot: selection, repoRoot: resolve(selection, "..", "..") },
    { dataRoot: dirname(selection), repoRoot: resolve(selection, "..", "..", "..") },
  ];
  for (const candidate of candidates) {
    if (await exists(join(candidate.dataRoot, "config", "system_config.yaml"))) return candidate;
  }
  return null;
}

function sample<T>(items: T[], maximum: number): T[] {
  if (items.length <= maximum) return items;
  return Array.from({ length: maximum }, (_, index) => items[Math.floor(index * items.length / maximum)]);
}

async function resolveLegacyAsset(raw: string, dataRoot: string, repoRoot: string): Promise<string | null> {
  const value = String(raw || "").trim();
  if (!value) return null;
  const candidates = [value, resolve(repoRoot, value), resolve(dataRoot, value)];
  for (const candidate of candidates) {
    if (await exists(candidate)) return resolve(candidate);
  }
  return null;
}

async function importCharacter(
  item: Record<string, unknown>,
  dataRoot: string,
  repoRoot: string,
  store: ConfigStore,
  index: number,
  warnings: string[],
): Promise<Character | null> {
  const name = String(item.name || `character-${index + 1}`).trim();
  const sprites = Array.isArray(item.sprites) ? item.sprites as Array<Record<string, unknown>> : [];
  if (!sprites.length) {
    warnings.push(`${name} 没有可导入的立绘。`);
    return null;
  }
  const preferred = sprites.find((entry) => String(entry.state_name || "") === "neutral") || sprites[0];
  const rawFrames = Array.isArray(preferred.frames) && preferred.frames.length
    ? preferred.frames.map(String)
    : [String(preferred.path || "")];
  const sourcePaths = (await Promise.all(sample(rawFrames, 24).map(
    (path) => resolveLegacyAsset(path, dataRoot, repoRoot),
  ))).filter((path): path is string => Boolean(path));
  if (!sourcePaths.length) {
    warnings.push(`${name} 的立绘路径无法解析。`);
    return null;
  }

  const id = `legacy-${slug(name)}-${index + 1}`;
  const targetDirectory = join(store.characterAssetsRoot, id);
  await mkdir(targetDirectory, { recursive: true });
  const importedPaths: string[] = [];
  for (const [frameIndex, sourcePath] of sourcePaths.entries()) {
    const extension = extname(sourcePath).toLowerCase() || ".png";
    const targetName = `frame_${String(frameIndex + 1).padStart(3, "0")}${extension}`;
    await copyFile(sourcePath, join(targetDirectory, targetName));
    importedPaths.push(`here-user:///characters/${id}/${targetName}`);
  }
  const profile = item.character_setting
    ? String(item.character_setting)
    : JSON.stringify(item.character_profile || {}, null, 2);
  return {
    id,
    name,
    color: String(item.color || "#f4a7b9"),
    profile: profile || `你是 ${name}，以自然、真诚的方式陪伴用户。`,
    visualIdentity: String(item.visual_identity || ""),
    scale: Number(item.sprite_scale || 1),
    sprite: {
      kind: importedPaths.length > 1 ? "frames" : "custom",
      paths: importedPaths,
      frameIntervalMs: Number(preferred.frame_interval_ms || 100),
    },
  };
}

export async function importLegacyHere(
  parent: BrowserWindow,
  store: ConfigStore,
): Promise<LegacyImportReport | null> {
  const result = await dialog.showOpenDialog(parent, {
    title: "选择旧版 here 仓库或数据目录",
    properties: ["openDirectory"],
    message: "只读取旧目录，并将兼容数据复制到 Electron 应用目录。",
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const roots = await locateRoots(result.filePaths[0]);
  if (!roots) throw new Error("没有找到旧版 config/system_config.yaml。请选择 here 仓库或 .local/here 目录。");

  const warnings: string[] = [];
  const [systemRaw, apiRaw, charactersRaw] = await Promise.all([
    readYaml(join(roots.dataRoot, "config", "system_config.yaml")),
    readYaml(join(roots.dataRoot, "config", "api.yaml")),
    readYaml(join(roots.dataRoot, "config", "characters.yaml")),
  ]);
  const system = (systemRaw || {}) as Record<string, unknown>;
  const api = (apiRaw || {}) as Record<string, unknown>;
  const legacyCharacters = Array.isArray(charactersRaw)
    ? charactersRaw as Array<Record<string, unknown>>
    : [];
  const imported = (await Promise.all(legacyCharacters.map((item, index) =>
    importCharacter(item, roots.dataRoot, roots.repoRoot, store, index, warnings),
  ))).filter((item): item is Character => Boolean(item));

  const current = await store.loadConfig();
  const mergedCharacters = [...current.characters];
  for (const character of imported) {
    if (!mergedCharacters.some((item) => item.name === character.name)) mergedCharacters.push(character);
  }
  const activeByName = mergedCharacters.find((item) => item.name === String(system.active_character_name || ""));
  const next: AppConfig = {
    ...current,
    api: {
      ...current.api,
      model: String(api.internal_agent_model || current.api.model),
      baseUrl: String(api.internal_agent_base_url || current.api.baseUrl),
      apiKey: String(api.internal_agent_api_key || current.api.apiKey),
      stream: api.hermes_streaming !== false,
    },
    system: {
      ...current.system,
      activeCharacterId: activeByName?.id || current.system.activeCharacterId,
      language: String(system.ui_language || "").startsWith("en")
        ? "en"
        : String(system.ui_language || "").startsWith("ja") ? "ja" : "zh-CN",
      fontScale: Math.min(1.4, Math.max(0.75, Number(system.base_font_size_px || 40) / 40)),
      volume: Math.min(1, Math.max(0, Number(system.music_volumn || 30) / 100)),
      showDialog: system.dialog_box_collapsed !== true,
      showProcessHint: system.process_hint_collapsed !== true,
      showInput: system.input_bar_collapsed !== true,
    },
    proactive: {
      ...current.proactive,
      enabled: system.proactive_contact_enabled === true,
      dailyLimit: Number(system.external_delivery_daily_limit || current.proactive.dailyLimit),
      quietHours: String(system.external_delivery_quiet_hours || current.proactive.quietHours),
    },
    characters: mergedCharacters,
  };
  await store.saveConfig(next);
  if (await exists(join(roots.dataRoot, "memory", "state.db"))) {
    warnings.push("旧版 SQLite 会话和 Hermes 记忆未自动合并；它们仍完整保留在原目录。");
  }
  return {
    sourcePath: roots.dataRoot,
    charactersImported: imported.length,
    settingsImported: true,
    warnings,
  };
}
