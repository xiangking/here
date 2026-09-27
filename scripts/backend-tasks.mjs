import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const backendRoot = join(projectRoot, "backend");
const venvRoot = join(backendRoot, ".venv");
const isWindows = process.platform === "win32";

function printCommand(command, args) {
  console.log("+", [command, ...args].join(" "));
}

function run(command, args, options = {}) {
  printCommand(command, args);
  const result = spawnSync(command, args, {
    cwd: projectRoot,
    env: process.env,
    stdio: "inherit",
    ...options,
  });
  if (result.error) {
    console.error(`无法执行 ${command}: ${result.error.message}`);
    process.exit(result.error.code === "ENOENT" ? 127 : 1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function uvCommand() {
  return process.env.HERE_UV || "uv";
}

function venvPythonPath() {
  const candidates = isWindows
    ? [join(venvRoot, "Scripts", "python.exe")]
    : [join(venvRoot, "bin", "python"), join(venvRoot, "bin", "python3")];
  return candidates.find((candidate) => existsSync(candidate)) || candidates[0];
}

function hostPythonCommand() {
  const configured = process.env.HERE_BUILD_PYTHON || process.env.PYTHON;
  const candidates = configured
    ? [configured]
    : (isWindows ? ["python", "python3"] : ["python3", "python"]);
  for (const candidate of candidates) {
    const probe = spawnSync(candidate, ["--version"], { cwd: projectRoot, stdio: "ignore" });
    if (!probe.error && probe.status === 0) return candidate;
  }
  throw new Error(`未找到可用的 Python。请安装 Python 3.11，或设置 HERE_BUILD_PYTHON 指向 Python 可执行文件。`);
}

function install(requirements) {
  run(uvCommand(), [
    "pip",
    "install",
    "--python",
    venvPythonPath(),
    ...requirements.flatMap((name) => ["-r", join(backendRoot, name)]),
  ]);
}

function setup() {
  run(uvCommand(), ["venv", venvRoot, "--python", "3.11"]);
  install(["requirements.txt"]);
}

function setupFull() {
  setup();
  install(["requirements-asr.txt", "requirements-hermes.txt"]);
}

function buildRuntime() {
  run(hostPythonCommand(), [join(backendRoot, "build_runtime.py"), ...process.argv.slice(3)]);
}

function test() {
  run(venvPythonPath(), [
    "-m",
    "unittest",
    "discover",
    "-s",
    join(backendRoot, "tests"),
    "-v",
    ...process.argv.slice(3),
  ]);
}

const action = process.argv[2];
try {
  switch (action) {
    case "setup":
      setup();
      break;
    case "setup-full":
      setupFull();
      break;
    case "runtime":
      buildRuntime();
      break;
    case "test":
      test();
      break;
    default:
      console.error("用法: node scripts/backend-tasks.mjs <setup|setup-full|runtime|test> [参数]");
      process.exitCode = 1;
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
