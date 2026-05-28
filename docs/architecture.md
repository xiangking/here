# here Architecture

This repository uses a direct, non-compatible module layout. Old import paths, aliases, and migration shims are intentionally not preserved.

## Top-Level Layout

- `app/`: application entrypoints and product assembly.
- `core/`: product-agnostic runtime, messaging, handlers, delivery, lifecycle-adjacent domain code, and agent backend bridges.
- `internal_agent/`: the built-in here agent implementation.
- `services/`: service integrations such as ASR, TTS, image generation, configuration, and i18n.
- `ui/`: desktop UI modules and shared UI assets.
- `infrastructure/`: filesystem paths, logging, storage primitives, and other platform concerns.
- `assets/`: bundled product assets.
- `defaults/`: default configuration and templates copied into the app home.
- `scripts/`: developer and startup scripts.
- `test/`: unit, integration, and end-to-end tests.
- `docs/`: architecture and product documentation.

## Agent Boundary

`internal_agent/` is the concrete built-in agent. It remains a first-level module because it owns memory, sessions, and internal reasoning behavior.

`core/agent/` is only the bridge layer. It adapts configured backends into the runtime through modules such as `internal_agent_backend.py`, `hermes_backend.py`, and `backend_factory.py`. Future backends should add another `*_backend.py` adapter here, while their implementation should live outside `core/agent/`.

## Runtime Files

Runtime files are resolved through `infrastructure.paths`. Development runs use `.local/here` under the repository root. Packaged system runs use the platform app home:

- macOS: `~/Library/Application Support/here`
- Windows: `%APPDATA%/here`
- Linux: `~/.local/share/here`

The app home owns these folders: `config`, `state`, `memory`, `characters`, `backgrounds`, `generated`, `cache`, `models`, `logs`, and `exports`.

Code that needs a runtime path should depend on `infrastructure.paths.get_app_paths()` instead of constructing repository-relative runtime locations.
