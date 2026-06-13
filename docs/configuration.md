# Configuration Guide

This document covers the `api.yaml` configuration system, the Provider Profile mechanism, and platform-specific notes for common API providers.

## Configuration Files

All runtime configuration lives in the app home directory (see [architecture.md](architecture.md) for location details):

| File | Purpose |
|---|---|
| `config/api.yaml` | Agent backend, TTS, T2I, ASR, Hermes, and provider profiles |
| `config/system_config.yaml` | UI, language, proactive contact, delivery channels |
| `config/characters.yaml` | Character definitions |
| `config/background.yaml` | Background groups |
| `config/messaging.yaml` | External messaging channel settings |
| `config/storage_paths.yaml` | Custom character memory/asset directories |

Defaults are seeded from `defaults/config/` on first run.

## Environment Variables

The application automatically loads `.env` and `.env.local` from the project root at startup (before any config is read). This is handled by `_load_dotenv_files()` in `app/desktop/bootstrap.py`.

API keys can be provided through environment variables instead of writing them into YAML files. The resolution order depends on the service (see sections below).

## Provider Profiles

The `provider_profiles` section in `api.yaml` defines reusable API provider entries. Each profile specifies a `base_url` and an `api_key` (or an environment variable name), and can be referenced by multiple services.

```yaml
provider_profiles:
  siliconflow:
    base_url: https://api.siliconflow.cn/v1
    api_key: ''                        # leave empty to use env var
    api_key_env: SILICONFLOW_API_KEY   # env var name for API key lookup
  openai:
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
```

Three services can bind to a profile:

| Field | Service | Fallback when empty |
|---|---|---|
| `agent_profile` | Agent backend (chat completions) | `internal_agent_base_url` + `internal_agent_api_key` |
| `tts_profile` | OpenAI-compatible TTS | `tts_extra_configs.<adapter>.base_url` + `api_key` |
| `t2i_profile` | Text-to-image | `t2i_extra_configs.<adapter>.api_url` + `api_key` |

### API Key Resolution

When a profile's `api_key` field is empty, the system looks up the key in this order:

1. The environment variable named in `api_key_env` (e.g. `SILICONFLOW_API_KEY`)
2. A guessed env var based on the profile name: `{PROFILE_NAME_UPPER}_API_KEY`
3. `OPENAI_API_KEY` as a final fallback

### Priority

Explicit per-service fields always override profile values. This preserves full backward compatibility with configurations that predate the profile system.

## Agent Backend

Configured via `agent_backend` (`auto` / `internal-agent` / `hermes-agent`) and the `internal_agent_*` fields. When `agent_profile` is set and `internal_agent_base_url` / `internal_agent_api_key` are left empty, values are inherited from the profile.

The Internal Agent uses the OpenAI Python SDK internally. The environment variable fallback chain in `internal_agent/agent.py` is:

```
{PROVIDER}_API_KEY  ->  OPENAI_API_KEY  ->  API_KEY
```

where `{PROVIDER}` is derived from `internal_agent_provider` (e.g. `siliconflow` -> `SILICONFLOW_API_KEY`).

## TTS (Text-to-Speech)

Configured via `tts_provider` and `tts_extra_configs`. Supported providers: `edge-tts`, `openai-tts`, `elevenlabs`, `minimax-tts`, `fish-audio`, `none`.

When `tts_provider` is `openai-tts` and `tts_profile` points to a valid profile, the `base_url` and `api_key` are injected automatically. Service-specific parameters (model, voice, response format) are still configured per-adapter in `tts_extra_configs`.

## T2I (Text-to-Image)

Configured via `t2i_provider` and `t2i_extra_configs`. Supported providers: `image-api`, `xai-grok-imagine`, `openai-gpt-image`.

When `t2i_profile` points to a valid profile, the `api_url` (from profile `base_url`) and `api_key` are injected automatically. Model and size settings remain in `t2i_extra_configs`.

## Provider-Specific Notes

### SiliconFlow (siliconflow.cn)

SiliconFlow provides OpenAI-compatible endpoints for chat, TTS, and image generation under a single API key.

**Base URL:** `https://api.siliconflow.cn/v1`

**Environment variable:** `SILICONFLOW_API_KEY`

#### Chat (Agent Backend)

Works out of the box with standard OpenAI SDK calls. Example models: `deepseek-ai/DeepSeek-V3`, `Pro/zai-org/GLM-4.7`, `Qwen/Qwen2.5-Coder-32B-Instruct`.

#### TTS

SiliconFlow's TTS endpoint requires the voice name to be **prefixed with the model name**, separated by a colon:

```yaml
tts_extra_configs:
  openai-tts:
    model: FunAudioLLM/CosyVoice2-0.5B
    voice: FunAudioLLM/CosyVoice2-0.5B:alex    # "model:voice" format required
    response_format: mp3
```

Available voices for CosyVoice2: `alex`, `anna`, `bella`, `benjamin`, `charles`, `claire`, `david`, `diana`.

Using the short voice name (e.g. `alex`) without the model prefix will result in a **400 Bad Request** with error code `20047: Invalid voice`.

#### Image Generation

The `openai-gpt-image` adapter sends requests to `{base_url}/images/generations` with Bearer token auth. Example model: `Kwai-Kolors/Kolors`. The `_normalize_image_generation_url()` helper appends `/images/generations` automatically when the profile `base_url` ends with `/v1`.

#### Complete Configuration Example

```yaml
provider_profiles:
  siliconflow:
    base_url: https://api.siliconflow.cn/v1
    api_key: ''
    api_key_env: SILICONFLOW_API_KEY

agent_profile: siliconflow
tts_profile: siliconflow
t2i_profile: siliconflow

agent_backend: internal-agent
internal_agent_provider: siliconflow
internal_agent_model: deepseek-ai/DeepSeek-V3
internal_agent_base_url: ''
internal_agent_api_key: ''

tts_provider: openai-tts
tts_extra_configs:
  openai-tts:
    model: FunAudioLLM/CosyVoice2-0.5B
    voice: FunAudioLLM/CosyVoice2-0.5B:alex
    response_format: mp3

t2i_provider: openai-gpt-image
t2i_api_url: ''
t2i_extra_configs:
  openai-gpt-image:
    default_model: Kwai-Kolors/Kolors
    size: 1024x1024
```

With `.env.local`:
```
SILICONFLOW_API_KEY=sk-your-key-here
```

This single key powers all three services (chat, speech, image).
