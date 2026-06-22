import type {
  ChatRequest,
  ConnectServerRequest,
  HitlDecision,
  PendingToolCall,
  ServerView,
  StreamEvent,
  ToolDescriptor,
} from "./types/mcp";

const API_ROOT = import.meta.env.VITE_API_ROOT ?? "/api";

async function checked<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  servers: (): Promise<ServerView[]> => checked(`${API_ROOT}/mcp/servers`),
  tools: (): Promise<ToolDescriptor[]> => checked(`${API_ROOT}/mcp/tools`),
  connect: (payload: ConnectServerRequest): Promise<ServerView> =>
    checked(`${API_ROOT}/mcp/servers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  disconnect: async (serverId: string): Promise<void> => {
    const response = await fetch(`${API_ROOT}/mcp/servers/${encodeURIComponent(serverId)}`, {
      method: "DELETE",
    });
    if (!response.ok) throw new Error(`Disconnect failed with status ${response.status}`);
  },
  decide: (
    approvalId: string,
    decision: HitlDecision,
    reason?: string,
  ): Promise<PendingToolCall> =>
    checked(`${API_ROOT}/hitl/${encodeURIComponent(approvalId)}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reason: reason || null }),
    }),
};

export async function* streamChat(
  payload: ChatRequest,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API_ROOT}/chat/stream`, {
    method: "POST",
    headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`Chat stream failed with status ${response.status}`);
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += value;
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data) yield JSON.parse(data) as StreamEvent;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

