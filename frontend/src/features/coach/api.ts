import { API_BASE_URL, api, tokenStore } from "@/lib/api/client";

export type CoachMessage = {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  createdAt: string | null;
  model?: string | null;
  /** Set when triage intercepted the turn — the client styles it as support. */
  safetyCategory?: string | null;
};

export type Conversation = {
  id: string;
  title: string | null;
  lastMessageAt: string | null;
  messageCount: number;
  isArchived: boolean;
};

export type ChatReply = {
  conversationId: string;
  message: CoachMessage;
  toolsUsed: string[];
  promptTokens: number;
  completionTokens: number;
};

export type Insight = {
  id: string;
  insightType: string;
  severity: "info" | "suggestion" | "warning";
  title: string;
  body: string;
  evidence: Record<string, unknown>;
  createdAt: string | null;
  acknowledgedAt: string | null;
  feedback: string | null;
};

export type Usage = {
  messagesUsed: number;
  messagesLimit: number;
  messagesRemaining: number;
  tokensUsed: number;
};

export const coachApi = {
  listConversations: () =>
    api.get<{ conversations: Conversation[] }>("/v1/ai/conversations").then((r) => r.conversations),

  listMessages: (conversationId: string, limit = 50) =>
    api
      .get<{ conversationId: string; messages: CoachMessage[] }>(
        `/v1/ai/conversations/${conversationId}/messages`,
        { query: { limit } },
      )
      .then((r) => r.messages),

  deleteConversation: (conversationId: string) =>
    api.delete<void>(`/v1/ai/conversations/${conversationId}`),

  send: (content: string, conversationId?: string) =>
    api.post<ChatReply>("/v1/ai/chat", { content, conversationId }),

  listInsights: () => api.get<{ insights: Insight[] }>("/v1/ai/insights").then((r) => r.insights),

  generateInsights: () =>
    api.post<{ insights: Insight[] }>("/v1/ai/insights/generate", {}).then((r) => r.insights),

  acknowledgeInsight: (id: string, feedback?: "helpful" | "not_helpful") =>
    api.post<Insight>(`/v1/ai/insights/${id}/acknowledge`, { feedback: feedback ?? null }),

  usage: () => api.get<Usage>("/v1/ai/usage"),
};

export type StreamEvent =
  /** Append to what is already on screen. */
  | { type: "delta"; text: string }
  /**
   * Discard everything shown and substitute `text`.
   *
   * Emitted when the server's output guard trips mid-generation. Honouring it is
   * not optional: it is the mechanism that keeps an unsafe answer off the screen.
   */
  | { type: "replace"; text: string }
  | { type: "tools"; tools: string[] }
  | { type: "message"; conversationId: string; message: CoachMessage; toolsUsed: string[] }
  | { type: "error"; message: string }
  | { type: "done" };

/**
 * Consumes `POST /v1/ai/chat/stream` as server-sent events.
 *
 * `EventSource` cannot be used: it only issues GETs and cannot carry an
 * Authorization header, so the body is read from `fetch` and framed by hand.
 */
export async function* streamChat(
  content: string,
  conversationId?: string,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API_BASE_URL}/v1/ai/chat/stream`, {
    method: "POST",
    credentials: "include",
    signal,
    headers: {
      "Content-Type": "application/json",
      ...(tokenStore.get() ? { Authorization: `Bearer ${tokenStore.get()}` } : {}),
    },
    body: JSON.stringify({ content, conversationId }),
  });

  if (!response.ok || !response.body) {
    yield { type: "error", message: "The coach is unavailable right now." };
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line. Anything after the last blank
    // line is a partial frame and must stay in the buffer.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;

      try {
        const parsed = JSON.parse(data);
        switch (event) {
          case "delta":
            yield { type: "delta", text: parsed.text ?? "" };
            break;
          case "replace":
            yield { type: "replace", text: parsed.text ?? "" };
            break;
          case "tools":
            yield { type: "tools", tools: parsed.tools ?? [] };
            break;
          case "message":
            yield {
              type: "message",
              conversationId: parsed.conversationId,
              message: parsed.message,
              toolsUsed: parsed.toolsUsed ?? [],
            };
            break;
          case "error":
            yield { type: "error", message: parsed.message ?? "Something went wrong." };
            break;
          case "done":
            yield { type: "done" };
            break;
        }
      } catch {
        // A malformed frame is not worth failing the whole answer over.
      }
    }
  }
}
