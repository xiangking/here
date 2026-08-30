import { randomUUID } from "node:crypto";
import type {
  AppConfig,
  ChatEvent,
  ChatMessage,
  ChatRequest,
  Emotion,
} from "../shared/types";
import { ConfigStore } from "./config-store";

type EventSink = (event: ChatEvent) => void;

const emotionRules: Array<[Emotion, RegExp]> = [
  ["happy", /开心|高兴|太好|哈哈|喜欢|期待|happy|glad|great|love/i],
  ["sad", /难过|遗憾|抱歉|失落|伤心|sad|sorry|unfortunately/i],
  ["angry", /生气|愤怒|不满|angry|furious/i],
  ["surprised", /惊讶|居然|没想到|哇|surpris|wow/i],
  ["thinking", /想想|思考|考虑|分析|think|consider/i],
];

export function inferEmotion(text: string): Emotion {
  return emotionRules.find(([, pattern]) => pattern.test(text))?.[0] || "neutral";
}

export function chatCompletionsUrl(baseUrl: string): string {
  const normalized = String(baseUrl || "").trim().replace(/\/+$/, "");
  if (/\/chat\/completions$/i.test(normalized)) return normalized;
  return `${normalized}/chat/completions`;
}

function extractDelta(payload: unknown): string {
  const content = (payload as { choices?: Array<{ delta?: { content?: unknown } }> })
    ?.choices?.[0]?.delta?.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((item) => (typeof item === "string" ? item : (item as { text?: string })?.text || ""))
      .join("");
  }
  return "";
}

function readableHttpError(status: number, body: string): string {
  if (status === 401 || status === 403) return "API Key 无效或没有访问该模型的权限。";
  if (status === 404) return "模型接口不存在，请检查 Base URL 与模型名称。";
  if (status === 429) return "模型服务请求过多或额度不足，请稍后再试。";
  const compact = body.replace(/\s+/g, " ").slice(0, 240);
  return `模型服务返回 ${status}${compact ? `：${compact}` : ""}`;
}

export class ChatService {
  private readonly controllers = new Map<string, AbortController>();

  constructor(
    private readonly store: ConfigStore,
    private readonly emit: EventSink,
  ) {}

  stop(requestId: string): void {
    this.controllers.get(requestId)?.abort();
  }

  async send(request: ChatRequest): Promise<void> {
    const config = await this.store.loadConfig();
    const character = config.characters.find((item) => item.id === request.characterId)
      || config.characters[0];
    const requestId = request.requestId || randomUUID();
    const controller = new AbortController();
    this.controllers.set(requestId, controller);
    this.emit({ requestId, type: "start" });

    const userMessage: ChatMessage = {
      id: randomUUID(),
      characterId: character.id,
      role: "user",
      text: request.text,
      attachmentNames: request.attachments.map((item) => item.name),
      createdAt: new Date().toISOString(),
    };
    const history = await this.store.appendHistory(userMessage);

    try {
      if (!config.api.apiKey) {
        const onboarding = "还没有配置模型 API。打开设置中的“模型”页，填写 OpenAI-compatible Base URL、模型名和 API Key 后，就可以开始聊天。";
        await this.finish(requestId, character.id, onboarding, "thinking");
        return;
      }

      const recent = history
        .filter((item) => item.characterId === character.id)
        .slice(-30)
        .map((item, index, items) => {
          const isCurrent = index === items.length - 1 && item.id === userMessage.id;
          if (!isCurrent || request.attachments.length === 0) {
            return { role: item.role, content: item.text };
          }
          return {
            role: "user",
            content: [
              { type: "text", text: item.text || "请看看这些图片。" },
              ...request.attachments.map((attachment) => ({
                type: "image_url",
                image_url: { url: attachment.dataUrl },
              })),
            ],
          };
        });
      const messages = [
        {
          role: "system",
          content: [
            character.profile,
            `你的名字是 ${character.name}。`,
            `视觉身份：${character.visualIdentity || "未设置"}。`,
            "直接输出要对用户说的话，不要输出 JSON、角色名前缀、舞台指令或情绪标签。",
          ].join("\n"),
        },
        ...recent,
      ];

      const response = await fetch(chatCompletionsUrl(config.api.baseUrl), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${config.api.apiKey}`,
        },
        body: JSON.stringify({
          model: config.api.model,
          messages,
          temperature: config.api.temperature,
          stream: config.api.stream,
        }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(readableHttpError(response.status, await response.text()));

      const text = config.api.stream
        ? await this.readStream(response, requestId)
        : await this.readResponse(response, requestId);
      await this.finish(requestId, character.id, text.trim() || "这次没有拿到有效回复，我们再试一次。", inferEmotion(text));
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        this.emit({ requestId, type: "error", message: "已停止生成。" });
      } else {
        this.emit({
          requestId,
          type: "error",
          message: error instanceof Error ? error.message : "消息处理失败。",
        });
      }
    } finally {
      this.controllers.delete(requestId);
    }
  }

  private async readResponse(response: Response, requestId: string): Promise<string> {
    const payload = await response.json() as {
      choices?: Array<{ message?: { content?: string } }>;
    };
    const text = payload.choices?.[0]?.message?.content || "";
    if (text) this.emit({ requestId, type: "delta", delta: text });
    return text;
  }

  private async readStream(response: Response, requestId: string): Promise<string> {
    if (!response.body) return "";
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let output = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || "";
      for (const line of lines) {
        const data = line.startsWith("data:") ? line.slice(5).trim() : "";
        if (!data || data === "[DONE]") continue;
        try {
          const delta = extractDelta(JSON.parse(data));
          if (delta) {
            output += delta;
            this.emit({ requestId, type: "delta", delta });
          }
        } catch {
          // Some compatible providers include keepalive or non-JSON SSE fields.
        }
      }
      if (done) break;
    }
    return output;
  }

  private async finish(
    requestId: string,
    characterId: string,
    text: string,
    emotion: Emotion,
  ): Promise<void> {
    await this.store.appendHistory({
      id: randomUUID(),
      characterId,
      role: "assistant",
      text,
      emotion,
      createdAt: new Date().toISOString(),
    });
    this.emit({ requestId, type: "done", text, emotion });
  }
}
