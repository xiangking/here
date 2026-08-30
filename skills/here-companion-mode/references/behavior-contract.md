# 同桌模式行为契约

Use this reference when tuning observer prompts, intervention rules, or memory extraction.

## Observation Decision Matrix

| Situation | Observe | Speak | Memory |
| --- | --- | --- | --- |
| Mode just enabled | after the configured interval | no immediate welcome interruption | no |
| Stable work pattern repeated | yes | usually no | add concise habit if confidence is high |
| User appears stuck or repeatedly switches context | yes | maybe, subject to cooldown | only if a stable pattern is supported |
| Long continuous work session | yes | offer a gentle break, never guilt | optional habit only after repetition |
| Sensitive-looking screen | capture only with permission; do not quote content | no content-specific speech | never persist content |
| User is actively chatting or assistant is speaking | defer | no | no |
| Quiet hours or mode disabled | no | no | no |

## Intervention Shape

Return a short local line with one purpose:

- Care: acknowledge sustained effort and offer presence.
- Reminder: suggest a concrete next step or break.
- Question: ask one clarifying question when the visual context is ambiguous.

Keep messages under roughly 80 Chinese characters (or 160 Latin characters), avoid UI-window inventories, and avoid certainty words such as “你一定是” or “我知道你在想什么”. Do not mention that a screenshot was stored.

## Habit Shape

Good:

- 用户通常在晚上进行编程工作。
- 用户排查问题时习惯同时打开编辑器和终端。
- 用户经常在多个项目之间切换后再回到主任务。

Bad:

- 用户刚刚打开了 `/secret/project/passwords.txt`。
- 用户今天 22:14 在微信里和某人聊天。
- 用户正在编辑一份标题为“裁员名单”的文档。

Write habits as durable tendencies, not as screenshots, exact file names, private text, or one-off events. Deduplicate after whitespace/case normalization and cap the profile size.

## Example Structured Outputs

No intervention:

```json
{"habits":[],"should_speak":false,"message":""}
```

Useful intervention:

```json
{
  "habits":[{"habit":"用户排查问题时习惯同时打开编辑器和终端","confidence":0.88}],
  "should_speak":true,
  "message":"你像是在来回核对代码和终端输出，要不要我陪你把这条线索整理一下？"
}
```

When the model is uncertain, prefer the no-op shape. The host must validate every field rather than trusting the model's JSON.
