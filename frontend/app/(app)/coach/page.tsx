"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUp, Bot, LifeBuoy, MessageSquarePlus, Trash2, User, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { coachApi, streamChat, type CoachMessage } from "@/features/coach/api";
import { Markdown } from "@/features/coach/components/markdown";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils/cn";

const SUGGESTED = [
  "How is my squat trending?",
  "What should I focus on this week?",
  "Am I training my back enough?",
  "Why has my bench stalled?",
];

/** Messages the safety layer intercepted are presented as support, not coaching. */
function isSupport(message: CoachMessage) {
  return Boolean(message.safetyCategory);
}

export default function CoachPage() {
  const queryClient = useQueryClient();
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const conversations = useQuery({
    queryKey: ["coach", "conversations"],
    queryFn: coachApi.listConversations,
  });

  const messages = useQuery({
    queryKey: ["coach", "messages", conversationId],
    queryFn: () => coachApi.listMessages(conversationId!),
    enabled: Boolean(conversationId),
  });

  const usage = useQuery({ queryKey: ["coach", "usage"], queryFn: coachApi.usage });

  const [streamed, setStreamed] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [activeTools, setActiveTools] = useState<string[]>([]);

  const remove = useMutation({
    mutationFn: coachApi.deleteConversation,
    onSuccess: (_data, id) => {
      if (id === conversationId) setConversationId(undefined);
      void queryClient.invalidateQueries({ queryKey: ["coach", "conversations"] });
      toast.success("Conversation deleted");
    },
  });

  // Follow the tail as answers arrive.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.data, pending]);

  async function submit(content: string) {
    const trimmed = content.trim();
    if (!trimmed || streaming) return;

    setDraft("");
    setPending(trimmed);
    setStreamed("");
    setActiveTools([]);
    setStreaming(true);

    try {
      for await (const event of streamChat(trimmed, conversationId)) {
        switch (event.type) {
          case "delta":
            setStreamed((current) => current + event.text);
            break;
          case "replace":
            // The server's guard tripped. Everything shown is discarded — this is
            // the mechanism that keeps an unsafe answer off the screen, so it is
            // obeyed rather than merged.
            setStreamed(event.text);
            break;
          case "tools":
            setActiveTools(event.tools);
            break;
          case "message":
            setConversationId(event.conversationId);
            void queryClient.invalidateQueries({
              queryKey: ["coach", "messages", event.conversationId],
            });
            void queryClient.invalidateQueries({ queryKey: ["coach", "conversations"] });
            void queryClient.invalidateQueries({ queryKey: ["coach", "usage"] });
            break;
          case "error":
            toast.error("The coach stopped early", { description: event.message });
            break;
        }
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 402) {
        toast.error("That's today's coaching limit", { description: "It resets tomorrow." });
      } else {
        toast.error("Couldn't send that", { description: "Try again in a moment." });
      }
    } finally {
      setStreaming(false);
      setPending(null);
      setStreamed("");
      setActiveTools([]);
    }
  }

  const thread = messages.data ?? [];
  const isEmpty = !conversationId || (thread.length === 0 && !messages.isLoading);

  return (
    <>
      <TopBar
        title="AI Coach"
        action={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setConversationId(undefined)}
            className="hidden sm:inline-flex"
          >
            <MessageSquarePlus className="h-4 w-4" aria-hidden />
            New chat
          </Button>
        }
      />

      <PageShell className="flex h-[calc(100dvh-4rem)] max-w-6xl flex-col gap-4 py-4 lg:flex-row">
        {/* --- history ------------------------------------------------------ */}
        <aside className="hidden w-64 shrink-0 flex-col lg:flex" aria-label="Conversations">
          <Button
            variant="secondary"
            block
            className="mb-3"
            onClick={() => setConversationId(undefined)}
          >
            <MessageSquarePlus className="h-4 w-4" aria-hidden />
            New chat
          </Button>

          <div className="flex-1 overflow-y-auto scrollbar-thin">
            {conversations.isLoading && (
              <div className="flex flex-col gap-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-11 w-full" />
                ))}
              </div>
            )}

            <ul className="flex flex-col gap-1">
              {(conversations.data ?? []).map((conversation) => (
                <li key={conversation.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => setConversationId(conversation.id)}
                    className={cn(
                      "flex h-11 w-full items-center rounded-md px-3 pr-10 text-left text-body",
                      conversation.id === conversationId
                        ? "bg-surface-well text-text"
                        : "text-text-secondary hover:bg-surface-well hover:text-text",
                    )}
                  >
                    <span className="truncate">{conversation.title ?? "Untitled"}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => remove.mutate(conversation.id)}
                    className="absolute right-1 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-sm text-text-muted opacity-0 transition-opacity hover:text-critical focus-visible:opacity-100 group-hover:opacity-100"
                    aria-label={`Delete ${conversation.title ?? "conversation"}`}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          </div>

          {usage.data && (
            <p className="mt-3 border-t border-border pt-3 text-caption text-text-muted">
              <span className="tabular">{usage.data.messagesRemaining}</span> of{" "}
              <span className="tabular">{usage.data.messagesLimit}</span> messages left today
            </p>
          )}
        </aside>

        {/* --- thread ------------------------------------------------------- */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div
            className="flex-1 overflow-y-auto scrollbar-thin"
            // Answers are announced as they arrive rather than silently appearing
            // for screen-reader users (docs/09 §9).
            aria-live="polite"
            aria-busy={streaming}
          >
            {isEmpty ? (
              <div className="flex h-full flex-col items-center justify-center gap-6 px-4 text-center">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-surface-well text-accent-text">
                  <Bot className="h-7 w-7" aria-hidden />
                </div>
                <div>
                  <h2 className="text-h2 text-text">Ask about your training</h2>
                  <p className="mt-1 max-w-md text-body text-text-secondary">
                    The coach reads your logged sessions, lifts and weight trend before it answers.
                  </p>
                </div>

                <div className="grid w-full max-w-lg gap-2 sm:grid-cols-2">
                  {SUGGESTED.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => void submit(prompt)}
                      className="rounded-md border border-border bg-surface p-3 text-left text-body text-text-secondary transition-colors hover:border-border-strong hover:text-text"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="mx-auto flex max-w-3xl flex-col gap-5 pb-4">
                {messages.isLoading &&
                  Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-20 w-full" />)}

                {thread.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}

                <AnimatePresence>
                  {pending && (
                    <>
                      <MessageBubble
                        message={{
                          id: "pending-user",
                          role: "user",
                          content: pending,
                          createdAt: null,
                        }}
                      />
                      <motion.div
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        className="flex gap-3"
                      >
                        <Avatar role="assistant" />
                        <div className="min-w-0 flex-1">
                          <p className="mb-1 text-overline uppercase text-text-muted">Coach</p>

                          {activeTools.length > 0 && (
                            <p className="mb-2 flex items-center gap-1.5 text-caption text-text-muted">
                              <Wrench className="h-3.5 w-3.5" aria-hidden />
                              Checking {activeTools.join(", ").replace(/_/g, " ")}
                            </p>
                          )}

                          {streamed ? (
                            <>
                              <Markdown content={streamed} />
                              {/* A caret while text is still arriving — the cue that
                                  distinguishes "still writing" from "finished". */}
                              <motion.span
                                className="ml-0.5 inline-block h-4 w-0.5 align-middle bg-accent"
                                animate={{ opacity: [1, 0.2, 1] }}
                                transition={{ duration: 1, repeat: Infinity }}
                                aria-hidden
                              />
                            </>
                          ) : (
                            <div
                              className="flex items-center gap-1.5 pt-2.5"
                              aria-label="Coach is thinking"
                            >
                              {[0, 1, 2].map((i) => (
                                <motion.span
                                  key={i}
                                  className="h-1.5 w-1.5 rounded-full bg-text-muted"
                                  animate={{ opacity: [0.3, 1, 0.3] }}
                                  transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.15 }}
                                />
                              ))}
                            </div>
                          )}
                        </div>
                      </motion.div>
                    </>
                  )}
                </AnimatePresence>

                <div ref={bottomRef} />
              </div>
            )}
          </div>

          {/* --- composer -------------------------------------------------- */}
          <div className="mx-auto w-full max-w-3xl pt-3">
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void submit(draft);
              }}
              className="flex items-end gap-2 rounded-lg border border-border bg-surface p-2"
            >
              <label htmlFor="coach-input" className="sr-only">
                Message the coach
              </label>
              <textarea
                id="coach-input"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  // Enter sends, Shift+Enter breaks the line — the convention
                  // everyone already has muscle memory for.
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void submit(draft);
                  }
                }}
                rows={1}
                maxLength={2000}
                placeholder="Ask about your training…"
                className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-2 py-2.5 text-body text-text placeholder:text-text-muted"
              />
              <Button
                type="submit"
                size="icon"
                disabled={!draft.trim()}
                loading={streaming}
                aria-label="Send message"
              >
                <ArrowUp className="h-4 w-4" aria-hidden />
              </Button>
            </form>

            <p className="mt-2 text-center text-caption text-text-muted">
              Coaching guidance, not medical advice.
            </p>
          </div>
        </div>
      </PageShell>
    </>
  );
}

function Avatar({ role }: { role: CoachMessage["role"] }) {
  const isUser = role === "user";
  return (
    <span
      className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
        isUser ? "bg-surface-well text-text-secondary" : "bg-accent text-accent-ink",
      )}
      aria-hidden
    >
      {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
    </span>
  );
}

function MessageBubble({ message }: { message: CoachMessage }) {
  const isUser = message.role === "user";
  const support = isSupport(message);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.26, ease: [0.2, 0, 0, 1] }}
      className="flex gap-3"
    >
      <Avatar role={message.role} />

      <div className="min-w-0 flex-1">
        <p className="mb-1 text-overline uppercase text-text-muted">
          {isUser ? "You" : "Coach"}
        </p>

        {support ? (
          // Visually distinct from ordinary coaching: this is a support message,
          // and the design should not let it read as training advice.
          <Card className="border-warning/30 bg-warning/5">
            <div className="mb-2 flex items-center gap-2 text-warning">
              <LifeBuoy className="h-4 w-4" aria-hidden />
              <span className="text-caption font-medium">Support</span>
            </div>
            <Markdown content={message.content} />
          </Card>
        ) : isUser ? (
          <p className="whitespace-pre-wrap text-body text-text">{message.content}</p>
        ) : (
          <Markdown content={message.content} />
        )}
      </div>
    </motion.div>
  );
}
