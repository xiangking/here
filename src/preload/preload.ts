import { contextBridge, ipcRenderer } from "electron";
import type { BackendEvent, DesktopState } from "../shared/backend-types";
import type { Attachment, HereDesktopApi, LegacyImportReport } from "../shared/types";

function normalizeInvokeError(error: unknown): Error {
  const raw = error instanceof Error ? error.message : String(error || "未知错误");
  // Electron prefixes rejected ipcRenderer.invoke calls with the channel name.
  // Keep the backend's actionable message visible to the renderer instead.
  const normalized = raw
    .replace(/^Error invoking remote method ['"][^'"]+['"]:\s*/i, "")
    .replace(/^Error:\s*/i, "")
    .trim();
  return new Error(normalized || "远程调用失败。");
}

const api: HereDesktopApi = {
  getState: () => ipcRenderer.invoke("state:get") as Promise<DesktopState>,
  backendCall: async (method, params = {}, timeoutMs = 30_000) => {
    try {
      return await ipcRenderer.invoke("backend:call", method, params, timeoutMs);
    } catch (error) {
      throw normalizeInvokeError(error);
    }
  },
  saveConfig: (config) => ipcRenderer.invoke("config:save", config) as Promise<DesktopState>,
  setActiveCharacter: (name) => ipcRenderer.invoke("character:set-active", name) as Promise<DesktopState>,
  sendMessage: (request) => ipcRenderer.invoke("chat:send", request),
  stopMessage: () => ipcRenderer.invoke("chat:stop"),
  chooseImages: () => ipcRenderer.invoke("images:choose") as Promise<Attachment[]>,
  captureScreenshots: () => ipcRenderer.invoke("screenshots:capture") as Promise<Attachment[]>,
  chooseFiles: (kind) => ipcRenderer.invoke("files:choose", kind) as Promise<string[]>,
  openPath: (path) => ipcRenderer.invoke("path:open", path) as Promise<string>,
  saveAsset: (sourcePath) => ipcRenderer.invoke("asset:save", sourcePath) as Promise<string>,
  clearHistory: () => ipcRenderer.invoke("history:clear"),
  copyHistory: () => ipcRenderer.invoke("history:copy"),
  importLegacy: () => ipcRenderer.invoke("legacy:import") as Promise<LegacyImportReport | null>,
  importCodexPet: () => ipcRenderer.invoke("codex-pet:import"),
  localFileUrl: (path) => ipcRenderer.invoke("local-file:url", path),
  windowAction: (action) => ipcRenderer.invoke("window:action", action),
  setIgnoreMouseEvents: (ignore, forward = true) =>
    ipcRenderer.send("window:ignore-mouse", ignore, forward),
  onBackendEvent: (listener) => {
    const handler = (_event: Electron.IpcRendererEvent, value: BackendEvent) => listener(value);
    ipcRenderer.on("backend:event", handler);
    return () => ipcRenderer.removeListener("backend:event", handler);
  },
};

contextBridge.exposeInMainWorld("hereDesktop", api);

declare global {
  interface Window {
    hereDesktop: HereDesktopApi;
  }
}
