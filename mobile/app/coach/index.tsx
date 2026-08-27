import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Send, ShieldAlert } from "lucide-react-native";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  TextInput,
  View,
} from "react-native";

import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import {
  type CoachMessage,
  coachApi,
  coachKeys,
  remainingLabel,
  streamMessage,
} from "@/features/coach/api";
import { useTranslate } from "@/lib/i18n";
import { radius, space, type, useTheme } from "@/theme";

/**
 * Talking to the coach.
 *
 * The streamed reply lives in local state rather than the query cache: it is not a
 * server fact until the `message` frame lands with the persisted row. Writing partial
 * text into the cache would mean a refetch mid-generation could wipe half a sentence.
 */
export default function CoachScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const listRef = useRef<FlatList<CoachMessage>>(null);
  const abortRef = useRef<(() => void) | null>(null);

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);

  const usage = useQuery({ queryKey: coachKeys.usage(), queryFn: coachApi.usage });

  const history = useQuery({
    queryKey: coachKeys.messages(conversationId ?? ""),
    queryFn: () => coachApi.messages(conversationId ?? ""),
    enabled: Boolean(conversationId),
  });

  // A stream left running holds the connection and still spends the daily allowance.
  useEffect(() => () => abortRef.current?.(), []);

  const messages = history.data?.messages ?? [];

  const send = useCallback(() => {
    const content = draft.trim();
    if (content.length === 0 || streaming) return;

    setDraft("");
    setError(null);
    setPartial("");
    setStreaming(true);

    // Shown immediately. The turn takes seconds and the sender should see their own
    // words land the moment they tap, not when the server acknowledges them.
    const optimistic: CoachMessage = {
      id: `local-${String(Date.now())}`,
      role: "user",
      content,
      createdAt: new Date().toISOString(),
      model: null,
      safetyCategory: null,
    };
    queryClient.setQueryData<{ conversationId: string; messages: CoachMessage[] }>(
      coachKeys.messages(conversationId ?? ""),
      (current) => ({
        conversationId: conversationId ?? "",
        messages: [...(current?.messages ?? []), optimistic],
      }),
    );

    abortRef.current = streamMessage(
      { content, conversationId },
      {
        onEvent: (event) => {
          switch (event.type) {
            case "delta":
              setPartial((current) => current + event.text);
              break;
            case "replace":
              // The output guard withheld the tail. Everything shown so far is
              // discarded rather than appended to — that is the point of the frame.
              setPartial(event.text);
              break;
            case "message": {
              const id = event.conversationId;
              setConversationId(id);
              setPartial("");
              // Refetch rather than splice: the server owns message ids and ordering,
              // and the optimistic row has to be replaced by the real one.
              void queryClient.invalidateQueries({ queryKey: coachKeys.messages(id) });
              void queryClient.invalidateQueries({ queryKey: coachKeys.usage() });
              break;
            }
            case "error":
              setError(event.message);
              setPartial("");
              break;
            case "tools":
            case "done":
              break;
          }
        },
        onDone: () => {
          setStreaming(false);
          abortRef.current = null;
        },
        onError: (message) => {
          setError(message);
          setPartial("");
          setStreaming(false);
          abortRef.current = null;
        },
      },
    );
  }, [conversationId, draft, queryClient, streaming]);

  const remaining = remainingLabel(usage.data);
  const exhausted = usage.data ? usage.data.messagesRemaining <= 0 : false;

  return (
    <Screen edges={["top"]} padded={false}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={0}
        style={styles.grow}
      >
        <View style={[styles.header, { borderBottomColor: theme.border }]}>
          <View style={styles.grow}>
            <Text variant="h3">{t("coach.title")}</Text>
            {remaining && (
              <Text variant="caption" tone="muted">
                {remaining}
              </Text>
            )}
          </View>
          <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.close}>
            <Text tone="accent">{t("common.done")}</Text>
          </Pressable>
        </View>

        <FlatList
          ref={listRef}
          data={messages}
          keyExtractor={(message) => message.id}
          contentContainerStyle={styles.list}
          onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
          keyboardShouldPersistTaps="handled"
          ListEmptyComponent={
            history.isLoading ? (
              <ActivityIndicator color={theme.textMuted} style={styles.spinner} />
            ) : (
              <View style={styles.empty}>
                <Text variant="body" tone="secondary" style={styles.centred}>
                  {t("coach.emptyPrompt")}
                </Text>
                <Text variant="caption" tone="muted" style={styles.centred}>
                  {t("coach.emptyHint")}
                </Text>
              </View>
            )
          }
          renderItem={({ item }) => <Bubble message={item} />}
          ListFooterComponent={
            <>
              {partial.length > 0 && (
                <Bubble
                  message={{
                    id: "streaming",
                    role: "assistant",
                    content: partial,
                    createdAt: null,
                    model: null,
                    safetyCategory: null,
                  }}
                />
              )}
              {streaming && partial.length === 0 && (
                <View style={styles.thinking}>
                  <ActivityIndicator color={theme.textMuted} size="small" />
                  <Text variant="caption" tone="muted">
                    {t("coach.thinking")}
                  </Text>
                </View>
              )}
              {error && (
                <Card style={[styles.error, { borderColor: theme.border }]}>
                  <Text variant="caption" tone="secondary">
                    {error}
                  </Text>
                </Card>
              )}
            </>
          }
        />

        <View style={[styles.composer, { borderTopColor: theme.border }]}>
          <TextInput
            value={draft}
            onChangeText={setDraft}
            placeholder={exhausted ? t("coach.noneLeftToday") : t("coach.askTheCoach")}
            placeholderTextColor={theme.textMuted}
            accessibilityLabel={t("coach.messageLabel")}
            editable={!exhausted}
            multiline
            maxLength={2000}
            style={[styles.input, { color: theme.text, backgroundColor: theme.surfaceWell }]}
          />
          <Pressable
            onPress={send}
            disabled={draft.trim().length === 0 || streaming || exhausted}
            accessibilityRole="button"
            accessibilityLabel={t("coach.send")}
            style={({ pressed }) => [
              styles.send,
              {
                backgroundColor: theme.accent,
                opacity:
                  draft.trim().length === 0 || streaming || exhausted ? 0.3 : pressed ? 0.7 : 1,
              },
            ]}
          >
            <Send size={18} color={theme.accentInk} />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

function Bubble({ message }: { message: CoachMessage }) {
  const t = useTranslate();
  const theme = useTheme();
  const mine = message.role === "user";

  return (
    <View style={[styles.bubbleRow, mine ? styles.mine : styles.theirs]}>
      <View
        style={[
          styles.bubble,
          {
            backgroundColor: mine ? theme.accent : theme.surfaceWell,
            borderColor: message.safetyCategory ? theme.border : "transparent",
            borderWidth: message.safetyCategory ? StyleSheet.hairlineWidth : 0,
          },
        ]}
      >
        {message.safetyCategory && (
          // Marked, because this reply never reached the model — it is scripted. Passing
          // it off as coaching would be a lie about where the words came from.
          <View style={styles.safety}>
            <ShieldAlert size={14} color={theme.textMuted} />
            <Text variant="caption" tone="muted">
              {t("coach.supportNotCoaching")}
            </Text>
          </View>
        )}
        <Text variant="body" style={mine ? { color: theme.accentInk } : undefined}>
          {message.content}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  grow: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    padding: space.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  close: { paddingVertical: space.sm },
  list: { padding: space.lg, gap: space.sm, paddingBottom: space.lg },
  empty: { alignItems: "center", gap: space.sm, paddingVertical: space.xxl },
  centred: { textAlign: "center" },
  spinner: { marginVertical: space.lg },
  bubbleRow: { flexDirection: "row" },
  mine: { justifyContent: "flex-end" },
  theirs: { justifyContent: "flex-start" },
  bubble: {
    maxWidth: "86%",
    gap: space.xs,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
    borderRadius: radius.md,
  },
  safety: { flexDirection: "row", alignItems: "center", gap: space.xs },
  thinking: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingVertical: space.sm },
  error: { padding: space.md, borderWidth: StyleSheet.hairlineWidth },
  composer: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: space.sm,
    padding: space.lg,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 120,
    paddingHorizontal: space.md,
    paddingTop: space.sm,
    paddingBottom: space.sm,
    borderRadius: radius.md,
    fontSize: type.body.fontSize,
  },
  send: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
});
