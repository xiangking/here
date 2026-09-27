---
name: here-companion-mode
description: "Build or extend a desktop app's 同桌模式 (companion-at-the-desk mode): capture permitted screen context, let the companion proactively notice work state, offer timely care or reminders, and retain only useful long-term user habits. Use when implementing screen-aware desktop companionship, proactive in-app check-ins, work-session observation, habit extraction from visual context, or privacy-safe Electron/macOS screen recording flows for here."
---

# here 同桌模式

## Core Intent

Treat 同桌模式 as a temporary shared-work presence, not as surveillance and not as a screenshot gallery. When enabled, here stays near the user, periodically understands the current work context, speaks only when it can help, and gradually learns stable working habits.

Keep the mode separate from proactive contact. Proactive contact is scheduled outreach or delivery through external channels. 同桌模式 is local, context-aware companionship: it may show a desktop dialogue, care, remind, suggest a break, or ask a useful question, but it must never use external delivery routes unless the user explicitly starts a separate workflow.

## Behavior Contract

Implement the following contract before adding UI polish:

1. Require an explicit mode toggle and platform screen-recording permission. Default to off.
2. Start a bounded session with a visible active state and a configurable observation interval. Stop cleanly when disabled, on quit, or when permission fails.
3. Capture only the selected displays. Keep raw frames temporary, size-bounded, and deleted after analysis unless the user explicitly enables retention.
4. Send frames to the existing multimodal agent path instead of creating a second provider stack. Keep screen observations out of ordinary chat history.
5. Ask the model for two independent results: stable habit candidates and an optional desktop intervention. Use strict structured output and validate it before acting.
6. Speak only when the intervention is useful, specific to the current context, and not inside a cooldown or quiet period. Prefer one short, warm line over a status report.
7. Write only repeated, high-confidence, non-sensitive habits to the existing user profile memory. Never persist raw screenshots or copied document/chat text as memory.
8. Keep interventions local to here. Do not route them through proactive contact, messaging platforms, external delivery limits, or scheduled life-plan outreach.

## Implementation Workflow

### 1. Inspect the host application

Find the existing settings model, secure preload/context bridge, chat attachment format, multimodal adapter, memory store, notification/dialog event, and background scheduler. Reuse those boundaries. Do not expose Electron objects or filesystem paths to the renderer unless an existing protocol requires it.

### 2. Add the capture boundary

Implement screen capture in the privileged desktop layer (Electron main on macOS/Windows/Linux). Return a narrow attachment DTO containing a stable display label, MIME type, and bounded data URL or temporary token. Handle empty thumbnails and denied permissions as explicit errors. Consider DPI scaling, multi-display IDs, platform sources with missing `display_id`, and a hard image-size limit before transmission.

### 3. Add a dedicated observation RPC

Do not send periodic observations through the normal user-chat method. Add a sidecar/domain operation such as `observe_screen` that:

- saves incoming attachments only in a temporary input directory;
- invokes the existing multimodal agent with a screen-observer prompt;
- returns structured habit/intervention results without appending a fake user turn;
- writes accepted habits to the existing user memory store;
- emits a local dialog event only for an accepted intervention;
- deletes temporary files in a `finally` path.

Use the active character's persona for tone, but keep the observer's output schema separate from character dialogue parsing.

### 4. Design the observer prompt

Require strict JSON with fields equivalent to:

```json
{
  "habits": [{"habit": "用户通常在晚上进行编程工作", "confidence": 0.82}],
  "should_speak": false,
  "message": ""
}
```

Tell the model to infer habits only from repeated or strong evidence, avoid secrets and personal content, avoid claiming certainty about the user's intent, and return an empty intervention when no help is warranted. Treat malformed output, low confidence, long messages, and sensitive terms as no-op results.

### 5. Add pacing and care

Store the last intervention time in memory and enforce a cooldown (normally at least 30 minutes). Respect the app's quiet-hours convention where one exists. Avoid intervening while a user-initiated reply is streaming, during audio playback, or immediately after the user sends a message. Make the assistant's active lines concrete:

- notice: “你已经在这个问题上停留一会儿了，需要我陪你拆一下吗？”
- care: “你一直在切窗口，像是在找线索。要不要先把目标写成一句话？”
- break: “你连续工作很久了，喝口水再回来，我还在。”

Do not narrate pixels (“我看到某某窗口”) unless the user asks. Do not pretend to know an unobserved reason.

### 6. Persist habits carefully

Normalize and deduplicate candidate habits before writing. Require a confidence threshold, length bound, and a repeated-observation policy when possible. Reject passwords, tokens, verification codes, financial/identity data, private message contents, names, addresses, and document quotations. Store concise behavioral statements, not timestamps or raw visual descriptions. Cap memory growth and preserve the user's existing memory format.

### 7. Build the UI around presence

Give 同桌模式 its own settings area, separate from 主动联系. Use one clear toggle, interval, display scope, and a compact active indicator. Explain the relationship in one sentence: “让 here 陪你工作，并逐渐理解你的工作节奏。” Provide a stop action and a permission error state. Do not add a separate one-shot mode unless the product explicitly asks for it.

## Separation Rules

Keep these paths distinct:

| Concern | 同桌模式 | 主动联系 |
| --- | --- | --- |
| Trigger | current screen/work context | life plan, schedule, or contact plan |
| Output | local dialogue, care, reminder, suggestion | planned message, optional external delivery |
| Data | temporary visual context and habit candidates | life/contact state and delivery history |
| Routing | desktop UI only | desktop or configured external channel |
| Pacing | observation interval and intervention cooldown | daily limit, quiet hours, confirmation policy |

Never solve a 同桌 intervention by enabling the proactive-contact scheduler.

## Verification

Test the capture boundary with mocked displays and sources: multiple displays, high-DPI sizing, empty thumbnails, missing platform display IDs, denied permission, and cleanup after success or failure. Test the observer with valid JSON, fenced JSON, malformed output, duplicate habits, low-confidence habits, sensitive candidates, and cooldown behavior. Test that interventions emit local dialogue but do not create fake user history or external-delivery events. Run the host project's typecheck, frontend tests, backend tests, and production build.

For the detailed behavior matrix and example prompts, read [references/behavior-contract.md](references/behavior-contract.md).
