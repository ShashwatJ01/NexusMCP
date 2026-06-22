export type TransportKind = "stdio" | "sse" | "streamable_http";
export type ServerStatus = "connecting" | "connected" | "degraded" | "disconnected";
export type ToolAccess = "read" | "write" | "delete" | "unknown";
export type HitlDecision = "approve" | "reject";

export interface StdioServerConfig {
  transport: "stdio";
  command: string;
  args: string[];
  env: Record<string, string>;
  cwd: string | null;
}

export interface RemoteServerConfig {
  transport: "sse" | "streamable_http";
  url: string;
  headers: Record<string, string>;
}

export type ServerConnection = StdioServerConfig | RemoteServerConfig;

export interface ConnectServerRequest {
  id: string;
  name: string;
  connection: ServerConnection;
}

export interface ServerView {
  id: string;
  name: string;
  transport: TransportKind;
  status: ServerStatus;
  tool_count: number;
  error: string | null;
  connected_at: string | null;
}

export type JsonSchema = {
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  enum?: unknown[];
  additionalProperties?: boolean | JsonSchema;
  [key: string]: unknown;
};

export interface ToolDescriptor {
  server_id: string;
  name: string;
  title: string;
  description: string;
  input_schema: JsonSchema;
  access: ToolAccess;
}

export interface PendingToolCall {
  id: string;
  conversation_id: string;
  server_id: string;
  tool_name: string;
  access: ToolAccess;
  arguments: Record<string, unknown>;
  created_at: string;
  expires_at: string;
  status: "pending" | "approved" | "rejected" | "expired";
}

export interface ChatRequest {
  conversation_id: string;
  message: string;
  server_ids: string[] | null;
}

interface EventEnvelope<TEvent extends string, TData> {
  event: TEvent;
  data: TData;
  trace_id: string | null;
}

export type SessionEvent = EventEnvelope<"session", { conversation_id: string }>;
export type TokenEvent = EventEnvelope<"token", { text: string }>;
export type ToolCallEvent = EventEnvelope<
  "tool_call",
  {
    call_id: string;
    server_id: string;
    tool_name: string;
    access: ToolAccess;
    arguments: Record<string, unknown>;
  }
>;
export type ToolResultEvent = EventEnvelope<
  "tool_result",
  { call_id: string; result: Record<string, unknown> }
>;
export type HitlRequiredEvent = EventEnvelope<"hitl_required", PendingToolCall>;
export type ErrorEvent = EventEnvelope<"error", { message: string; detail?: string }>;
export type DoneEvent = EventEnvelope<
  "done",
  { status: "complete" | "error" | "blocked" | "limit"; turn?: number }
>;

export type StreamEvent =
  | SessionEvent
  | TokenEvent
  | ToolCallEvent
  | ToolResultEvent
  | HitlRequiredEvent
  | ErrorEvent
  | DoneEvent;

export interface ChatMessageView {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  state?: "streaming" | "complete" | "error";
  traceId?: string;
}

