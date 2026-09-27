import { execFileSync, spawn } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);

function stableMacElectronApp() {
  const sourceApp = join(projectRoot, "node_modules", "electron", "dist", "Electron.app");
  const targetRoot = join(projectRoot, ".dev");
  const targetApp = join(targetRoot, "here-dev.app");
  const markerPath = join(targetRoot, "here-dev-fingerprint.json");
  const electronPackage = JSON.parse(readFileSync(join(projectRoot, "node_modules", "electron", "package.json"), "utf8"));
  const fingerprint = JSON.stringify({
    electronVersion: electronPackage.version,
    sourceModifiedAt: statSync(sourceApp).mtimeMs,
  });
  const currentFingerprint = existsSync(markerPath) ? readFileSync(markerPath, "utf8") : "";

  if (!existsSync(targetApp) || currentFingerprint !== fingerprint) {
    mkdirSync(targetRoot, { recursive: true });
    rmSync(targetApp, { recursive: true, force: true });
    execFileSync("/usr/bin/ditto", [sourceApp, targetApp], { stdio: "inherit" });
    const plist = join(targetApp, "Contents", "Info.plist");
    execFileSync("/usr/bin/plutil", ["-replace", "CFBundleIdentifier", "-string", "com.here.companion.dev", plist]);
    execFileSync("/usr/bin/plutil", ["-replace", "CFBundleName", "-string", "here", plist]);
    execFileSync("/usr/bin/plutil", ["-replace", "CFBundleDisplayName", "-string", "here", plist]);
    execFileSync("/usr/bin/plutil", [
      "-replace",
      "NSMicrophoneUsageDescription",
      "-string",
      "here 需要访问麦克风以进行语音输入。",
      plist,
    ]);
    execFileSync("/usr/bin/codesign", ["--force", "--deep", "--sign", "-", targetApp], { stdio: "inherit" });
    writeFileSync(markerPath, fingerprint, "utf8");
  }

  return targetApp;
}

const macElectronApp = process.platform === "darwin" ? stableMacElectronApp() : "";
const electronPath = process.platform === "darwin" ? "/usr/bin/open" : require("electron");
const electronArgs = process.platform === "darwin"
  ? [
      "-W",
      "-n",
      "--env", `VITE_DEV_SERVER_URL=${process.env.VITE_DEV_SERVER_URL ?? ""}`,
      macElectronApp,
      "--args", projectRoot,
    ]
  : [projectRoot];
const child = spawn(electronPath, electronArgs, {
  cwd: projectRoot,
  env: process.env,
  stdio: "inherit",
});

let stopping = false;
function stopChild(signal) {
  if (stopping) return;
  stopping = true;
  if (process.platform === "darwin") {
    const executable = join(macElectronApp, "Contents", "MacOS", "Electron");
    try {
      execFileSync("/usr/bin/pkill", ["-TERM", "-f", executable], { stdio: "ignore" });
    } catch {
      // The app may already have exited before the runner receives the signal.
    }
  }
  child.kill(signal);
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => stopChild(signal));
}

child.on("exit", (code, signal) => {
  if (signal && !stopping) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
