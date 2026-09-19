#!/usr/bin/env node
// Prune the compiled Electron main/preload output before a fresh build.
//
// `tsc` does not delete JS emitted for sources that were renamed or removed,
// and `vite build` only empties the renderer output. Without this step a stale
// `dist-electron` would still be packaged by electron-builder (`dist-electron/**/*`).
import { rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const target = resolve(projectRoot, "dist-electron");
rmSync(target, { recursive: true, force: true });
