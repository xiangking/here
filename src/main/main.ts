import {
  app,
  BrowserWindow,
  clipboard,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
  net,
  Notification,
  protocol,
  screen,
  shell,
  systemPreferences,
  Tray,
  desktopCapturer,
} from "electron";
import { copyFile, readFile, stat } from "node:fs/promises";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, extname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";
import type { Attachment, LegacyImportReport } from "../shared/types";
import type { BackendEvent, BackendState, DesktopState } from "../shared/backend-types";
import { PythonSidecar } from "./python-sidecar";

protocol.registerSchemesAsPrivileged([
  {
    scheme: "here-local",
    privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true },
  },
]);

const sidecar = new PythonSidecar();
const MAX_LOCAL_FILE_TOKENS = 512;
const localFiles = new Map<string, string>();
let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let isQuitting = false;
let backendState: BackendState | null = null;
let windowPreferences = { always_on_top: true, close_to_tray: true };
let persistWindowTimer: NodeJS.Timeout | null = null;
let screenContextTimer: NodeJS.Timeout | null = null;
let screenContextBusy = false;

interface PersistedWindowState {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  always_on_top?: boolean;
}

function rememberLocalFile(token: string, path: string): void {
  localFiles.set(token, path);
  while (localFiles.size > MAX_LOCAL_FILE_TOKENS) {
    const oldest = localFiles.keys().next().value;
    if (oldest === undefined) break;
    localFiles.delete(oldest);
  }
}

function resolveLocalFile(token: string): string | undefined {
  const path = localFiles.get(token);
  if (!path) return undefined;
  localFiles.delete(token);
  localFiles.set(token, path);
  return path;
}

function rendererEntry(): string {
  return join(__dirname, "..", "..", "dist", "renderer", "index.html");
}

function iconPath(): string {
  return join(sidecar.backendRoot, "assets", "system", "picture", "Icon.png");
}

function desktopState(state: BackendState): DesktopState {
  return {
    ...state,
    platform: process.platform,
    app_version: app.getVersion(),
    window: { ...windowPreferences },
  };
}

function windowStatePath(): string {
  return join(app.getPath("userData"), "window-state.json");
}

function loadWindowState(): PersistedWindowState {
  try {
    const value = JSON.parse(readFileSync(windowStatePath(), "utf8")) as PersistedWindowState;
    if (typeof value.always_on_top === "boolean") windowPreferences.always_on_top = value.always_on_top;
    return value;
  } catch {
    return {};
  }
}

function visibleWindowBounds(saved: PersistedWindowState): Electron.Rectangle | undefined {
  if (![saved.x, saved.y, saved.width, saved.height].every((value) => Number.isFinite(value))) return undefined;
  const candidate = {
    x: Number(saved.x),
    y: Number(saved.y),
    width: Math.max(340, Number(saved.width)),
    height: Math.max(560, Number(saved.height)),
  };
  const visible = screen.getAllDisplays().some(({ workArea }) => (
    candidate.x < workArea.x + workArea.width - 80
    && candidate.x + candidate.width > workArea.x + 80
    && candidate.y < workArea.y + workArea.height - 80
    && candidate.y + candidate.height > workArea.y + 80
  ));
  return visible ? candidate : undefined;
}

function persistWindowState(): void {
  if (!mainWindow || mainWindow.isDestroyed() || mainWindow.isMinimized()) return;
  const bounds = mainWindow.getBounds();
  const value: PersistedWindowState = { ...bounds, always_on_top: mainWindow.isAlwaysOnTop() };
  mkdirSync(dirname(windowStatePath()), { recursive: true });
  writeFileSync(windowStatePath(), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function scheduleWindowStatePersist(): void {
  if (persistWindowTimer) clearTimeout(persistWindowTimer);
  persistWindowTimer = setTimeout(persistWindowState, 250);
}

function createWindow(): BrowserWindow {
  const savedBounds = visibleWindowBounds(loadWindowState());
  const window = new BrowserWindow({
    width: savedBounds?.width || 351,
    height: savedBounds?.height || 470,
    x: savedBounds?.x,
    y: savedBounds?.y,
    minWidth: 320,
    minHeight: 450,
    transparent: true,
    backgroundColor: "#00000000",
    frame: false,
    show: false,
    resizable: true,
    alwaysOnTop: windowPreferences.always_on_top,
    hasShadow: false,
    title: "here",
    icon: iconPath(),
    webPreferences: {
      preload: join(__dirname, "..", "preload", "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      backgroundThrottling: false,
    },
  });
  window.setMenuBarVisibility(false);
  if (process.platform === "darwin") window.setWindowButtonVisibility(false);
  window.on("close", (event) => {
    if (!isQuitting && windowPreferences.close_to_tray) {
      event.preventDefault();
      window.hide();
    }
  });
  window.on("closed", () => {
    mainWindow = null;
  });
  window.on("move", scheduleWindowStatePersist);
  window.on("resize", scheduleWindowStatePersist);
  window.once("ready-to-show", () => window.show());
  if (process.env.VITE_DEV_SERVER_URL) {
    void window.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    void window.loadFile(rendererEntry());
  }
  return window;
}

function showWindow(): void {
  if (!mainWindow) mainWindow = createWindow();
  mainWindow.show();
  mainWindow.focus();
}

function installTray(): void {
  if (tray) return;
  const icon = nativeImage.createFromPath(iconPath()).resize({ width: 18, height: 18 });
  tray = new Tray(icon);
  tray.setToolTip("here");
  refreshTrayMenu();
  tray.on("click", () => {
    if (mainWindow?.isVisible()) mainWindow.hide();
    else showWindow();
  });
}

function refreshTrayMenu(): void {
  if (!tray) return;
  const locale = String(backendState?.config.system_config.ui_language || "zh_CN");
  const labels: Record<string, [string, string, string]> = {
    zh_CN: ["显示 here", "隐藏到后台", "退出"],
    en: ["Show here", "Hide in background", "Quit"],
    ja: ["here を表示", "バックグラウンドに隠す", "終了"],
    ko: ["here 표시", "백그라운드로 숨기기", "종료"],
  };
  const [show, hide, quit] = labels[locale] || labels.zh_CN;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: show, click: showWindow },
    { label: hide, click: () => mainWindow?.hide() },
    { type: "separator" },
    {
      label: quit,
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]));
}

function publish(event: BackendEvent): void {
  if (event.event === "ready") {
    backendState = event.payload as BackendState;
    scheduleScreenContext();
  }
  if (event.event === "dialog") {
    const payload = event.payload as { text?: string; character_name?: string };
    if (!mainWindow?.isVisible() && Notification.isSupported()) {
      new Notification({
        title: payload.character_name || "here",
        body: payload.text || "",
        icon: iconPath(),
      }).show();
    }
  }
  mainWindow?.webContents.send("backend:event", event);
}

async function chooseImages(): Promise<Attachment[]> {
  if (!mainWindow) return [];
  const choice = await dialog.showOpenDialog(mainWindow, {
    title: "选择图片",
    properties: ["openFile", "multiSelections"],
    filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "gif"] }],
  });
  if (choice.canceled) return [];
  const attachments: Attachment[] = [];
  for (const path of choice.filePaths.slice(0, 4)) {
    const info = await stat(path);
    if (info.size > 12 * 1024 * 1024) throw new Error(`${basename(path)} 超过 12 MB。`);
    const extension = extname(path).toLowerCase();
    const mimeType = extension === ".png" ? "image/png"
      : extension === ".webp" ? "image/webp"
        : extension === ".gif" ? "image/gif" : "image/jpeg";
    attachments.push({
      name: basename(path),
      mimeType,
      dataUrl: `data:${mimeType};base64,${(await readFile(path)).toString("base64")}`,
    });
  }
  return attachments;
}

const MICROPHONE_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone";

function isMicrophonePermissionError(error: unknown): boolean {
  const text = error instanceof Error ? error.message : String(error || "");
  return /麦克风权限|microphone permission|microphone access|microphone.*denied|not authorized/i.test(text);
}

async function offerMicrophonePermission(): Promise<void> {
  if (process.platform !== "darwin" || !mainWindow || mainWindow.isDestroyed()) return;
  const response = await dialog.showMessageBox(mainWindow, {
    type: "warning",
    title: "需要麦克风权限",
    message: "here 需要访问麦克风才能使用语音输入。",
    detail: "请在系统设置的“隐私与安全性 > 麦克风”中允许 here，然后返回应用重试。",
    buttons: ["打开系统设置", "取消"],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  if (response.response === 0) {
    await shell.openExternal(MICROPHONE_SETTINGS_URL).catch(() => undefined);
  }
}

/** Capture selected displays as bounded PNG attachments. The renderer never gets raw Electron sources. */
function screenCapturePermissionHint(): string {
  if (process.platform === "darwin") {
    return "请在系统设置的“隐私与安全性 > 屏幕录制”中允许 here。";
  }
  if (process.platform === "win32") {
    return "请检查 Windows 的屏幕捕获权限，并允许 here 访问屏幕内容。";
  }
  return "请检查系统的屏幕捕获权限。";
}

async function captureScreenshots(displayIds: string[] = []): Promise<Attachment[]> {
  const displays = screen.getAllDisplays();
  if (!displays.length) throw new Error("未检测到显示器。");
  const selected = displayIds.length
    ? displays.filter((display) => displayIds.includes(String(display.id)))
    : displays;
  if (!selected.length) throw new Error("同桌模式选择的显示器不可用。");
  const max = selected.reduce((size, display) => ({
    // Keep the native capture bounded; high-DPI displays are resized before leaving main.
    width: Math.max(size.width, Math.min(1920, Math.ceil(display.bounds.width * display.scaleFactor))),
    height: Math.max(size.height, Math.min(1080, Math.ceil(display.bounds.height * display.scaleFactor))),
  }), { width: 1, height: 1 });
  let sources: Electron.DesktopCapturerSource[];
  try {
    sources = await desktopCapturer.getSources({
      types: ["screen"],
      thumbnailSize: max,
      fetchWindowIcons: false,
    });
  } catch (error) {
    throw new Error(`无法访问屏幕内容。${screenCapturePermissionHint()}${error instanceof Error ? ` ${error.message}` : ""}`);
  }
  const byDisplay = new Map(selected.map((display) => [String(display.id), display]));
  const attachments = sources
    .filter((source) => {
      const sourceDisplayId = source.display_id || source.id.split(":")[1] || "";
      // Some Linux/Windows Electron builds leave display_id empty. In the default
      // all-display mode, retain those sources rather than silently returning none.
      return sourceDisplayId ? byDisplay.has(sourceDisplayId) : displayIds.length === 0;
    })
    .map((source) => {
      const image = source.thumbnail;
      if (image.isEmpty()) return null;
      const size = image.getSize();
      const width = Math.min(1280, size.width);
      const resized = width < size.width
        ? image.resize({ width, height: Math.round(size.height * width / size.width), quality: "best" })
        : image;
      const png = resized.toPNG();
      return {
        name: `screen-${source.display_id || source.id}.png`,
        mimeType: "image/png",
        dataUrl: `data:image/png;base64,${png.toString("base64")}`,
      } satisfies Attachment;
    })
    .filter((attachment): attachment is Attachment => attachment !== null && attachment.dataUrl.length > 0);
  if (!attachments.length) {
    throw new Error(`无法读取屏幕内容。${screenCapturePermissionHint()}`);
  }
  return attachments;
}

function stopScreenContext(): void {
  if (screenContextTimer) clearTimeout(screenContextTimer);
  screenContextTimer = null;
}

function scheduleScreenContext(): void {
  stopScreenContext();
  const system = backendState?.config.system_config;
  if (!system?.screen_context_enabled) return;
  const intervalMs = Math.max(60, Number(system.screen_context_interval_seconds) || 300) * 1000;
  screenContextTimer = setTimeout(() => void runScreenContextCapture(intervalMs), intervalMs);
}

async function runScreenContextCapture(intervalMs: number): Promise<void> {
  if (screenContextBusy) {
    screenContextTimer = setTimeout(() => void runScreenContextCapture(intervalMs), intervalMs);
    return;
  }
  const system = backendState?.config.system_config;
  if (!system?.screen_context_enabled) return;
  screenContextBusy = true;
  try {
    const attachments = await captureScreenshots(Array.isArray(system.screen_context_display_ids)
      ? system.screen_context_display_ids.map(String) : []);
    await sidecar.request("observe_screen", {
      character_name: backendState?.active_character_name,
      attachments,
    }, 10 * 60_000);
    mainWindow?.webContents.send("backend:event", {
      event: "screen_context",
      payload: { state: "observed", captured_at: new Date().toISOString() },
    });
  } catch (error) {
    mainWindow?.webContents.send("backend:event", {
      event: "screen_context",
      payload: { state: "error", message: error instanceof Error ? error.message : String(error) },
    });
  } finally {
    screenContextBusy = false;
    scheduleScreenContext();
  }
}

async function chooseFiles(kind: string): Promise<string[]> {
  if (!mainWindow) return [];
  const choices: Record<string, { title: string; properties: Array<"openFile" | "openDirectory" | "multiSelections">; filters?: Electron.FileFilter[] }> = {
    background: { title: "选择背景图片", properties: ["openFile"], filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "gif"] }] },
    bgm: { title: "选择背景音乐", properties: ["openFile"], filters: [{ name: "Audio", extensions: ["mp3", "ogg", "wav", "m4a", "aac", "flac"] }] },
    reference: { title: "选择视觉参考图", properties: ["openFile"], filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] }] },
    character_assets: { title: "选择立绘、逐帧图片或视频", properties: ["openFile", "multiSelections"], filters: [{ name: "Character assets", extensions: ["png", "jpg", "jpeg", "webp", "gif", "bmp", "mp4", "mov", "m4v", "avi", "mkv", "webm"] }] },
    character_image: { title: "选择立绘图片", properties: ["openFile"], filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "bmp"] }] },
    character_animation: { title: "选择动画帧或视频", properties: ["openFile", "multiSelections"], filters: [{ name: "Animation frames or video", extensions: ["png", "jpg", "jpeg", "webp", "bmp", "mp4", "mov", "webm", "m4v", "avi"] }] },
    audio: { title: "选择音频", properties: ["openFile"], filters: [{ name: "Audio", extensions: ["wav", "mp3", "ogg", "m4a", "flac"] }] },
    directory: { title: "选择目录", properties: ["openDirectory"] },
  };
  const options = choices[kind];
  if (!options) throw new Error(`Unsupported file picker: ${kind}`);
  const choice = await dialog.showOpenDialog(mainWindow, options);
  return choice.canceled ? [] : choice.filePaths;
}

async function saveAsset(sourcePath: string): Promise<string> {
  if (!mainWindow || !(await stat(sourcePath)).isFile()) return "";
  const choice = await dialog.showSaveDialog(mainWindow, {
    title: "保存文件",
    defaultPath: basename(sourcePath),
  });
  if (choice.canceled || !choice.filePath) return "";
  await copyFile(sourcePath, choice.filePath);
  return choice.filePath;
}

function registerIpc(): void {
  ipcMain.handle("state:get", async () => desktopState(await sidecar.request<BackendState>("get_state")));
  ipcMain.handle("backend:call", async (_event, method: string, params = {}, timeoutMs = 30_000) => {
    const allowed = new Set([
      "get_state", "save_config", "set_active_character", "chat", "stop_chat", "clear_history",
      "update_memory", "generate_image", "generate_realtime_sprite", "start_asr", "stop_asr", "save_messaging", "save_storage",
      "pause_asr", "resume_asr", "resolve_assets", "import_legacy", "upload_character_sprites",
      "codex_pet_candidates", "import_codex_pet", "wechat_login_start", "wechat_login_poll",
      "wechat_status", "telegram_discover", "list_models", "dependency_status", "install_dependencies",
      "prepare_asr", "revert_history", "import_character_state_assets", "delete_character_sprite",
      "delete_character",
      "create_character",
    ]);
    if (!allowed.has(method)) throw new Error(`Backend method not allowed: ${method}`);
    const requestParams: Record<string, unknown> = params && typeof params === "object" && !Array.isArray(params)
      ? { ...(params as Record<string, unknown>) }
      : {};
    // Only the host process may assert that macOS permission was granted.
    // Do not trust a similarly named value from the renderer.
    delete requestParams.__here_macos_microphone_authorized;
    if (method === "start_asr" && process.platform === "darwin") {
      const granted = await systemPreferences.askForMediaAccess("microphone");
      if (!granted) {
        await offerMicrophonePermission();
        throw new Error("麦克风权限未开启。请在系统设置中允许 here，然后返回应用重试。");
      }
      // The Python sidecar has a separate process identity on macOS. Passing
      // this private marker avoids a second TCC check that can report a false
      // denial after Electron has already received authorization.
      requestParams.__here_macos_microphone_authorized = true;
    }
    try {
      return await sidecar.request(method, requestParams, Math.min(Number(timeoutMs) || 30_000, 10 * 60_000));
    } catch (error) {
      if (method === "start_asr" && isMicrophonePermissionError(error)) {
        await offerMicrophonePermission();
      }
      throw error;
    }
  });
  ipcMain.handle("config:save", async (_event, config: Record<string, unknown>) => {
    const state = await sidecar.request<BackendState>("save_config", config, 60_000);
    backendState = state;
    refreshTrayMenu();
    scheduleScreenContext();
    return desktopState(state);
  });
  ipcMain.handle("character:set-active", async (_event, name: string) => {
    const state = await sidecar.request<BackendState>("set_active_character", { name }, 60_000);
    backendState = state;
    return desktopState(state);
  });
  ipcMain.handle("chat:send", async (_event, request) => {
    void sidecar.request("chat", {
      request_id: request.requestId,
      text: request.text,
      character_name: request.characterName,
      attachments: request.attachments,
    }, 10 * 60_000).catch((error) => publish({
      event: "chat_error",
      payload: { request_id: request.requestId, message: error.message },
    }));
  });
  ipcMain.handle("chat:stop", () => sidecar.request("stop_chat"));
  ipcMain.handle("images:choose", chooseImages);
  ipcMain.handle("screenshots:capture", (_event, displayIds?: unknown) =>
    captureScreenshots(Array.isArray(displayIds) ? displayIds.map(String) : []));
  ipcMain.handle("files:choose", (_event, kind: string) => chooseFiles(kind));
  ipcMain.handle("path:open", async (_event, path: string) => shell.openPath(path));
  ipcMain.handle("asset:save", (_event, sourcePath: string) => saveAsset(sourcePath));
  ipcMain.handle("history:clear", () => sidecar.request("clear_history"));
  ipcMain.handle("history:copy", async () => {
    const state = await sidecar.request<BackendState>("get_state");
    clipboard.writeText(state.history.map((item) => `${item.character_name}: ${item.text}`).join("\n"));
  });
  ipcMain.handle("legacy:import", async (): Promise<LegacyImportReport | null> => {
    if (!mainWindow) return null;
    const choice = await dialog.showOpenDialog(mainWindow, {
      title: "选择旧版 here 仓库或 .local/here 数据目录",
      properties: ["openDirectory"],
      message: "导入只会读取旧目录，并复制到 Electron 用户数据目录。",
    });
    if (choice.canceled || !choice.filePaths[0]) return null;
    return await sidecar.request("import_legacy", { source_path: choice.filePaths[0] }, 120_000);
  });
  ipcMain.handle("codex-pet:import", async () => {
    if (!mainWindow) return null;
    const choice = await dialog.showOpenDialog(mainWindow, {
      title: "选择 Codex Pet 目录",
      properties: ["openDirectory"],
      message: "目录中需要包含 pet.json 和 spritesheet 图片。",
    });
    if (choice.canceled || !choice.filePaths[0]) return null;
    return await sidecar.request("import_codex_pet", { path: choice.filePaths[0] }, 120_000);
  });
  ipcMain.handle("local-file:url", async (_event, path: string) => {
    const allowed = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".m4v", ".wav", ".mp3", ".ogg", ".m4a", ".aac", ".flac"]);
    if (!allowed.has(extname(path).toLowerCase()) || !(await stat(path)).isFile()) {
      throw new Error("Unsupported local asset.");
    }
    const token = randomUUID();
    rememberLocalFile(token, path);
    return `here-local://asset/${token}`;
  });
  ipcMain.handle("window:action", (_event, action: string) => {
    if (!mainWindow) return false;
    if (action === "minimize") mainWindow.minimize();
    if (action === "hide") mainWindow.hide();
    if (action === "close") mainWindow.close();
    if (action === "toggle-pin") {
      windowPreferences.always_on_top = !mainWindow.isAlwaysOnTop();
      mainWindow.setAlwaysOnTop(windowPreferences.always_on_top);
      scheduleWindowStatePersist();
    }
    return mainWindow.isAlwaysOnTop();
  });
  ipcMain.on("window:ignore-mouse", (_event, ignore: boolean, forward = true) => {
    mainWindow?.setIgnoreMouseEvents(Boolean(ignore), { forward: Boolean(forward) });
  });
}

app.whenReady().then(async () => {
  protocol.handle("here-local", async (request) => {
    const token = new URL(request.url).pathname.replace(/^\//, "");
    const path = resolveLocalFile(token);
    if (!path) return new Response("Not found", { status: 404 });
    const response = await net.fetch(pathToFileURL(path).toString());
    const headers = new Headers(response.headers);
    headers.set("Access-Control-Allow-Origin", "*");
    return new Response(response.body, { status: response.status, headers });
  });
  registerIpc();
  sidecar.on("event", publish);
  backendState = await sidecar.start();
  scheduleScreenContext();
  mainWindow = createWindow();
  installTray();
  app.on("activate", showWindow);
}).catch((error) => {
  console.error(error);
  dialog.showErrorBox("here 启动失败", error instanceof Error ? error.message : String(error));
  app.quit();
});

app.on("before-quit", () => {
  isQuitting = true;
  stopScreenContext();
  persistWindowState();
  sidecar.stop();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin" && !windowPreferences.close_to_tray) app.quit();
});
