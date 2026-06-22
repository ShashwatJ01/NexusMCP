import { useCallback, useRef, useState } from "react";
import { api, streamChat } from "../api";
import type {
  ChatMessageView,
  HitlDecision,
  PendingToolCall,
  StreamEvent,
} from "../types/mcp";

const makeId = (): string => crypto.randomUUID();

export function useChatStream() {
  const conversationId = useRef(makeId());
  const activeRequest = useRef<AbortController | null>(null);
  const [messages, setMessages] = useState<ChatMessageView[]>([]);
  const [streamState, setStreamState] = useState<"idle" | "streaming" | "waiting">("idle");
  const [pendingApproval, setPendingApproval] = useState<PendingToolCall | null>(null);
  const [activity, setActivity] = useState<StreamEvent[]>([]);

  const send = useCallback(async (content: string, serverIds: string[]) => {
    const text = content.trim();
    if (!text || activeRequest.current) return;
    const assistantId = makeId();
    const controller = new AbortController();
    activeRequest.current = controller;
    setStreamState("streaming");
    setMessages((current) => [
      ...current,
      { id: makeId(), role: "user", content: text, state: "complete" },
      { id: assistantId, role: "assistant", content: "", state: "streaming" },
    ]);

    try {
      for await (const event of streamChat(
        { conversation_id: conversationId.current, message: text, server_ids: serverIds },
        controller.signal,
      )) {
        if (event.event !== "token") {
          setActivity((current) => [...current.slice(-11), event]);
        }
        if (event.event === "session") {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantId && event.trace_id
                ? { ...message, traceId: event.trace_id }
                : message,
            ),
          );
        } else if (event.event === "token") {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantId
                ? { ...message, content: message.content + event.data.text }
                : message,
            ),
          );
        } else if (event.event === "hitl_required") {
          setPendingApproval(event.data);
          setStreamState("waiting");
        } else if (event.event === "error") {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantId && !message.content
                ? { ...message, content: event.data.message, state: "error" }
                : message,
            ),
          );
        } else if (event.event === "done") {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantId
                ? {
                    ...message,
                    content: message.content || "No response content was returned.",
                    state: event.data.status === "complete" ? "complete" : "error",
                  }
                : message,
            ),
          );
        }
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        const detail = cause instanceof Error ? cause.message : "Connection lost";
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId
              ? { ...message, content: message.content || detail, state: "error" }
              : message,
          ),
        );
      }
    } finally {
      activeRequest.current = null;
      setStreamState("idle");
      setPendingApproval(null);
    }
  }, []);

  const decide = useCallback(
    async (decision: HitlDecision, reason: string) => {
      if (!pendingApproval) return;
      await api.decide(pendingApproval.id, decision, reason);
      setPendingApproval(null);
      setStreamState("streaming");
    },
    [pendingApproval],
  );

  const stop = useCallback(() => {
    activeRequest.current?.abort();
    activeRequest.current = null;
    setPendingApproval(null);
    setStreamState("idle");
  }, []);

  return { messages, streamState, pendingApproval, activity, send, decide, stop };
}
