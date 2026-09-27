import { EventEmitter } from "node:events";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { app } from "electron";
import type { BackendEvent, BackendState } from "../shared/backend-types";

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timer: NodeJS.Timeout;
}

interface RpcResponse {
  type: "response";
  id: string;
  ok: boolean;
  result?: unknown;
  error?: { message?: string; kind?: string };
}

function devBackendRoot(): string {
  return join(__dirname, "..", "..", "backend");
}

export function resolvePythonRuntime(root: string): { command: string; args: string[] } {
  const standaloneExecutable = process.platform === "win32"
    ? join(root, "runtime", "here-backend.exe")
    : join(root, "runtime", "here-backend");
  const standalonePython = process.platform === "win32"
    ? join(root, "runtime", "python.exe")
    : join(root, "runtime", "bin", "python3");
  const venvPython = process.platform === "win32"
    ? join(root, ".venv", "Scripts", "python.exe")
    : join(root, ".venv", "bin", "python");
  const command = process.env.HERE_PYTHON
    || [standaloneExecutable, standalonePython, venvPython].find(existsSync)
    || "";
  if (!command) {
    throw new Error(`Python sidecar runtime not found under ${root}. Run npm run backend:setup for development or npm run backend:runtime for packaging.`);
  }
  return {
    command,
    args: command === standaloneExecutable ? [] : [join(root, "rpc_bridge.py")],
  };
}

export class PythonSidecar extends EventEmitter {
  private process: ChildProcessWithoutNullStreams | null = null;
  private readonly pending = new Map<string, PendingRequest>();
  private readyState: BackendState | null = null;

  get backendRoot(): string {
    return app.isPackaged ? join(process.resourcesPath, "backend") : devBackendRoot();
  }

  get dataRoot(): string {
    return join(app.getPath("userData"), "python-data");
  }

  async start(): Promise<BackendState> {
    if (this.readyState) return this.readyState;
    const root = this.backendRoot;
    const { command, args } = resolvePythonRuntime(root);

    this.process = spawn(command, args, {
      cwd: root,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
        PYTHONIOENCODING: "utf-8",
        HERE_PROJECT_ROOT: root,
        HERE_APP_HOME: this.dataRoot,
        DYLD_LIBRARY_PATH: process.platform === "darwin"
          ? [join(root, "runtime", "lib"), process.env.DYLD_LIBRARY_PATH].filter(Boolean).join(":" )
          : process.env.DYLD_LIBRARY_PATH,
      },
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.process.stderr.on("data", (chunk) => {
      const line = String(chunk).trimEnd();
      if (line) console.error(`[here-backend] ${line}`);
    });
    this.process.on("exit", (code, signal) => {
      const error = new Error(`Python sidecar exited (${code ?? signal ?? "unknown"}).`);
      for (const item of this.pending.values()) {
        clearTimeout(item.timer);
        item.reject(error);
      }
      this.pending.clear();
      this.process = null;
      this.readyState = null;
      this.emit("exit", error);
    });
    createInterface({ input: this.process.stdout }).on("line", (line) => this.handleLine(line));

    return await new Promise<BackendState>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Python sidecar startup timed out.")), 60_000);
      const onReady = (state: BackendState) => {
        clearTimeout(timer);
        this.off("fatal", onFatal);
        resolve(state);
      };
      const onFatal = (payload: { message?: string }) => {
        clearTimeout(timer);
        this.off("ready", onReady);
        reject(new Error(payload.message || "Python sidecar failed to start."));
      };
      this.once("ready", onReady);
      this.once("fatal", onFatal);
    });
  }

  request<T>(method: string, params: Record<string, unknown> = {}, timeoutMs = 30_000): Promise<T> {
    if (!this.process) return Promise.reject(new Error("Python sidecar is not running."));
    const id = randomUUID();
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out.`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
        timer,
      });
      this.process?.stdin.write(`${JSON.stringify({ id, method, params })}\n`);
    });
  }

  stop(): void {
    if (!this.process) return;
    this.process.stdin.end();
    setTimeout(() => this.process?.kill(), 2_000).unref();
  }

  private handleLine(line: string): void {
    let message: RpcResponse | (BackendEvent & { type: "event" });
    try {
      message = JSON.parse(line);
    } catch {
      console.error(`[here-backend:protocol] ${line}`);
      return;
    }
    if (message.type === "response") {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.pending.delete(message.id);
      if (message.ok) pending.resolve(message.result);
      else pending.reject(new Error(message.error?.message || "Backend request failed."));
      return;
    }
    if (message.type === "event") {
      if (message.event === "ready") this.readyState = message.payload as BackendState;
      this.emit(message.event, message.payload);
      this.emit("event", { event: message.event, payload: message.payload } satisfies BackendEvent);
    }
  }
}
