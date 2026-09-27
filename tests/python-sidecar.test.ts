import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { resolvePythonRuntime } from "../src/main/python-sidecar";


const roots: string[] = [];

afterEach(() => {
  delete process.env.HERE_PYTHON;
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function root(): string {
  const value = mkdtempSync(join(tmpdir(), "here-sidecar-"));
  roots.push(value);
  writeFileSync(join(value, "rpc_bridge.py"), "# test\n");
  return value;
}

describe("resolvePythonRuntime", () => {
  it("prefers the relocatable packaged Python runtime", () => {
    const value = root();
    const runtime = join(value, "runtime", "bin", "python3");
    mkdirSync(join(value, "runtime", "bin"), { recursive: true });
    writeFileSync(runtime, "");
    expect(resolvePythonRuntime(value)).toEqual({ command: runtime, args: [join(value, "rpc_bridge.py")] });
  });

  it("falls back to the development virtual environment", () => {
    const value = root();
    const python = join(value, ".venv", "bin", "python");
    mkdirSync(join(value, ".venv", "bin"), { recursive: true });
    writeFileSync(python, "");
    expect(resolvePythonRuntime(value).command).toBe(python);
  });

  it("fails with an actionable message when no runtime exists", () => {
    expect(() => resolvePythonRuntime(root())).toThrow(/backend:setup.*backend:runtime/);
  });
});
