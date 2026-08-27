import { API_BASE_URL, api, tokenStore } from "@/lib/api/client";

/**
 * The AI coach.
 *
 * Streaming is not decoration here. A coaching turn assembles context, runs a tool loop
 * and then generates — ten seconds is normal — and ten seconds of spinner reads as a
 * hang. Tokens arriving as they are produced is the difference between "thinking" and
 * "broken".
 *
 * React Native's `fetch` does not expose a readable body, so the browser's
 * `response.body.getReader()` approach is unavailable. `XMLHttpRequest` does grow
 * `responseText` during `onprogress`, which is how every React Native SSE library works
 * and what this uses. The frame parsing below is deliberately identical to the web
 * client's, because the two are reading the same protocol and any divergence is a bug
 * waiting for a long reply to expose it.
 */

export type CoachMessage = {
  id: string;
  /** `user` or `assistant`. Left open because the server owns the vocabulary. */
  role: string;
  content: string;
  createdAt: string | null;
  model: string | null;
  /**
   * Set when safety triage intercepted the turn.
   *
   * Such replies never reached the model — they are scripted. Presenting them as
   * coaching would be a lie about where the words came from, so the UI marks them.
   */
  safetyCategory: string | null;
};

export type Conversation = {
  id: string;
  title: string | null;
  lastMessageAt: string | null;
  messageCount: number;
  isArchived: boolean;
};

export type Insight = {
  id: string;
  insightType: string;
  severity: string;
  title: string;
  body: string;
  /** What justified it. An insight you cannot interrogate is an assertion. */
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

export const coachKeys = {
  all: ["coach"] as const,
  conversations: () => [...coachKeys.all, "conversations"] as const,
  messages: (id: string) => [...coachKeys.all, "messages", id] as const,
  insights: () => [...coachKeys.all, "insights"] as const,
  usage: () => [...coachKeys.all, "usage"] as const,
};

export const coachApi = {
  conversations: () =>
    api.get<{ conversations: Conversation[] }>("/v1/ai/conversations"),

  messages: (conversationId: string) =>
    api.get<{ conversationId: string; messages: CoachMessage[] }>(
      `/v1/ai/conversations/${conversationId}/messages`,
    ),

  deleteConversation: (conversationId: string) =>
    api.delete<void>(`/v1/ai/conversations/${conversationId}`),

  insights: () => api.get<{ insights: Insight[] }>("/v1/ai/insights"),

  acknowledgeInsight: (insightId: string, feedback?: "helpful" | "not_helpful") =>
    api.post<void>(
      `/v1/ai/insights/${insightId}/acknowledge`,
      feedback ? { feedback } : {},
    ),

  usage: () => api.get<Usage>("/v1/ai/usage"),
};

// ------------------------------------------------------------------- streaming
export type StreamEvent =
  | { type: "delta"; text: string }
  | { type: "replace"; text: string }
  | { type: "tools"; tools: string[] }
  | { type: "message"; conversationId: string; message: CoachMessage; toolsUsed: string[] }
  | { type: "error"; message: string }
  | { type: "done" };

/**
 * Split a buffer into complete SSE frames, keeping the partial tail.
 *
 * Exported for its own sake: this is the part that breaks, and it breaks only on long
 * replies where a frame straddles two `onprogress` callbacks. Returning the remainder
 * rather than dropping it is the whole contract.
 */
/**
 * A field from a decoded frame, as a string, or "" when it is anything else.
 *
 * Not `String(value)`: that turns an object into the literal text "[object Object]" and
 * renders it into the reply as if the coach had said it.
 */
function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** A list of strings, filtering out anything that is not one. */
function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function parseFrames(buffer: string): { events: StreamEvent[]; rest: string } {
  const frames = buffer.split("\n\n");
  // Anything after the last blank line is a partial frame and must stay buffered.
  const rest = frames.pop() ?? "";
  const events: StreamEvent[] = [];

  for (const frame of frames) {
    let event = "message";
    let data = "";
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) continue;

    try {
      const parsed = JSON.parse(data) as Record<string, unknown>;
      switch (event) {
        case "delta":
          events.push({ type: "delta", text: text(parsed.text) });
          break;
        case "replace":
          // The output guard withheld the tail and is substituting a safe answer.
          // Everything shown so far must be discarded, not appended to.
          events.push({ type: "replace", text: text(parsed.text) });
          break;
        case "tools":
          events.push({ type: "tools", tools: strings(parsed.tools) });
          break;
        case "message":
          events.push({
            type: "message",
            conversationId: text(parsed.conversationId),
            message: parsed.message as CoachMessage,
            toolsUsed: strings(parsed.toolsUsed),
          });
          break;
        case "error":
          events.push({
            type: "error",
            message: text(parsed.message) || "Something went wrong.",
          });
          break;
        case "done":
          events.push({ type: "done" });
          break;
      }
    } catch {
      // A malformed frame is not worth failing the whole answer over.
    }
  }

  return { events, rest };
}

/**
 * Stream one coaching turn.
 *
 * Returns an abort function. Cancelling matters more on a phone than on a desktop: the
 * screen can be dismissed mid-reply, and an XHR left running holds the connection and
 * still counts against the daily allowance.
 */
export function streamMessage(
  input: { content: string; conversationId?: string | null },
  handlers: {
    onEvent: (event: StreamEvent) => void;
    onDone: () => void;
    onError: (message: string) => void;
  },
): () => void {
  const xhr = new XMLHttpRequest();
  let consumed = 0;
  let buffer = "";
  let finished = false;

  const finish = (fn: () => void) => {
    if (finished) return;
    finished = true;
    fn();
  };

  xhr.open("POST", `${API_BASE_URL}/v1/ai/chat/stream`);
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.setRequestHeader("Accept", "text/event-stream");

  const token = tokenStore.get();
  if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

  xhr.onprogress = () => {
    // `responseText` accumulates; only the newly arrived slice is unparsed.
    const chunk = xhr.responseText.slice(consumed);
    consumed = xhr.responseText.length;
    buffer += chunk;

    const { events, rest } = parseFrames(buffer);
    buffer = rest;
    for (const event of events) handlers.onEvent(event);
  };

  xhr.onload = () => {
    if (xhr.status >= 400) {
      // 402 is the daily allowance, 503 is the provider being unavailable. Both are
      // things to tell the user plainly rather than a generic failure.
      finish(() =>
        handlers.onError(
          xhr.status === 402
            ? "You have used your coaching messages for today."
            : xhr.status === 503
              ? "The coach is unavailable right now. Try again shortly."
              : "Something went wrong.",
        ),
      );
      return;
    }
    // Flush whatever the last progress event left behind.
    const { events } = parseFrames(`${buffer}\n\n`);
    for (const event of events) handlers.onEvent(event);
    finish(handlers.onDone);
  };

  xhr.onerror = () => {
    finish(() => handlers.onError("No connection. The coach needs one."));
  };

  xhr.ontimeout = () => {
    finish(() => handlers.onError("The coach took too long to answer."));
  };

  xhr.send(
    JSON.stringify({
      content: input.content,
      conversationId: input.conversationId ?? undefined,
    }),
  );

  return () => {
    // Marked finished first so aborting does not fire onerror and show a failure for
    // something the user chose to do.
    finished = true;
    xhr.abort();
  };
}

/** `3 left today`, or null when there is no meaningful limit to report. */
export function remainingLabel(usage: Usage | undefined): string | null {
  if (!usage || usage.messagesLimit <= 0) return null;
  if (usage.messagesRemaining <= 0) return "No messages left today";
  return `${usage.messagesRemaining} left today`;
}
