import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useChatStream } from "./hooks/useChatStream";
import { useMcpRegistry } from "./hooks/useMcpRegistry";
import type {
  ConnectServerRequest,
  HitlDecision,
  PendingToolCall,
  ServerView,
  StreamEvent,
  ToolAccess,
  ToolDescriptor,
  TransportKind,
} from "./types/mcp";

const PROMPTS = [
  "Inspect connected systems and summarize operational risk.",
  "List the tools that can mutate data and explain their scope.",
  "Check service health using read-only tools.",
];

function AccessMark({ access }: { access: ToolAccess }) {
  return <span className={`access access--${access}`}>{access}</span>;
}

function Registry({
  servers,
  tools,
  selected,
  onToggle,
  onConnect,
  onDisconnect,
}: {
  servers: ServerView[];
  tools: ToolDescriptor[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onConnect: () => void;
  onDisconnect: (id: string) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const visible = tools.filter((tool) =>
    `${tool.name} ${tool.description} ${tool.server_id}`.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <aside className="registry panel">
      <div className="panel__heading">
        <div>
          <p className="eyebrow">MCP CONTROL PLANE</p>
          <h2>Tool registry</h2>
        </div>
        <button className="icon-button" onClick={onConnect} aria-label="Connect MCP server">
          +
        </button>
      </div>

      <div className="registry__stats" aria-label="Registry summary">
        <div><strong>{servers.length}</strong><span>servers</span></div>
        <div><strong>{tools.length}</strong><span>tools</span></div>
        <div><strong>{tools.filter((tool) => tool.access !== "read").length}</strong><span>guarded</span></div>
      </div>

      <div className="server-rail">
        {servers.length === 0 ? (
          <button className="empty-server" onClick={onConnect}>
            <span>NO CONNECTIONS</span>
            Connect your first MCP server →
          </button>
        ) : (
          servers.map((server) => (
            <div className="server-row" key={server.id}>
              <button
                className={`server-select ${selected.has(server.id) ? "is-selected" : ""}`}
                onClick={() => onToggle(server.id)}
                aria-pressed={selected.has(server.id)}
              >
                <span className={`status-dot status-dot--${server.status}`} />
                <span><b>{server.name}</b><small>{server.transport.replace("_", " · ")}</small></span>
                <em>{server.tool_count}</em>
              </button>
              <button
                className="server-remove"
                onClick={() => void onDisconnect(server.id)}
                aria-label={`Disconnect ${server.name}`}
              >
                ×
              </button>
            </div>
          ))
        )}
      </div>

      <label className="search-box">
        <span>⌕</span>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter tool catalog" />
        <kbd>{visible.length}</kbd>
      </label>

      <div className="tool-list">
        {visible.map((tool) => {
          const isOpen = expanded === `${tool.server_id}/${tool.name}`;
          return (
            <button
              className={`tool-card ${isOpen ? "is-open" : ""}`}
              key={`${tool.server_id}/${tool.name}`}
              onClick={() => setExpanded(isOpen ? null : `${tool.server_id}/${tool.name}`)}
              aria-expanded={isOpen}
            >
              <span className="tool-card__index">{String(visible.indexOf(tool) + 1).padStart(2, "0")}</span>
              <span className="tool-card__body">
                <span className="tool-card__title"><b>{tool.title}</b><AccessMark access={tool.access} /></span>
                <small>{tool.server_id} / {tool.name}</small>
                <p>{tool.description || "No tool description was published."}</p>
                {isOpen && (
                  <code>{JSON.stringify(tool.input_schema, null, 2)}</code>
                )}
              </span>
              <span className="tool-card__arrow">↘</span>
            </button>
          );
        })}
        {servers.length > 0 && visible.length === 0 && (
          <div className="empty-tools">No tools match this view.</div>
        )}
      </div>
    </aside>
  );
}

function ApprovalModal({
  pending,
  onDecision,
}: {
  pending: PendingToolCall;
  onDecision: (decision: HitlDecision, reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lines = JSON.stringify(pending.arguments, null, 2).split("\n");
  const decide = async (decision: HitlDecision) => {
    setWorking(true);
    setError(null);
    try {
      await onDecision(decision, reason);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Decision could not be recorded");
      setWorking(false);
    }
  };

  return (
    <div className="modal-shell" role="dialog" aria-modal="true" aria-labelledby="approval-title">
      <div className="approval-modal">
        <div className="approval-modal__signal"><span>!</span> HUMAN GATE / {pending.access.toUpperCase()}</div>
        <div className="approval-modal__head">
          <div>
            <p className="eyebrow">EXECUTION PAUSED</p>
            <h2 id="approval-title">Review proposed mutation</h2>
          </div>
          <span className="approval-modal__timer">expires {new Date(pending.expires_at).toLocaleTimeString()}</span>
        </div>

        <div className="approval-route">
          <span>{pending.server_id}</span><i>→</i><strong>{pending.tool_name}</strong>
        </div>

        <div className="diff-header"><span>REQUEST PAYLOAD</span><span>+ proposed</span></div>
        <pre className="payload-diff" aria-label="Proposed JSON payload diff">
          {lines.map((line, index) => (
            <span key={`${index}-${line}`}><i>+</i>{line}</span>
          ))}
        </pre>

        <label className="reason-field">
          <span>Decision note <small>captured in audit trail</small></span>
          <textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reference a ticket, policy, or reason…" />
        </label>
        {error && <p className="form-error">{error}</p>}
        <div className="approval-actions">
          <button className="button button--reject" disabled={working} onClick={() => void decide("reject")}>Reject call</button>
          <button className="button button--approve" disabled={working} onClick={() => void decide("approve")}>{working ? "Recording…" : "Approve once"}</button>
        </div>
        <p className="approval-note">Approval applies to this exact payload only. Modified arguments require a new decision.</p>
      </div>
    </div>
  );
}

function ConnectModal({
  onClose,
  onConnect,
}: {
  onClose: () => void;
  onConnect: (request: ConnectServerRequest) => Promise<void>;
}) {
  const [transport, setTransport] = useState<TransportKind>("streamable_http");
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [args, setArgs] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setWorking(true);
    setError(null);
    const connection = transport === "stdio"
      ? { transport, command: endpoint, args: args.trim() ? args.trim().split(/\s+/) : [], env: {}, cwd: null }
      : { transport, url: endpoint, headers: {} };
    try {
      await onConnect({ id, name, connection });
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Connection failed");
      setWorking(false);
    }
  };

  return (
    <div className="modal-shell" role="dialog" aria-modal="true" aria-labelledby="connect-title">
      <form className="connect-modal" onSubmit={(event) => void submit(event)}>
        <div className="connect-modal__head">
          <div><p className="eyebrow">NEW TRANSPORT</p><h2 id="connect-title">Connect MCP server</h2></div>
          <button type="button" className="close-button" onClick={onClose}>×</button>
        </div>
        <div className="transport-tabs">
          {(["streamable_http", "sse", "stdio"] as const).map((kind) => (
            <button type="button" className={transport === kind ? "is-active" : ""} onClick={() => setTransport(kind)} key={kind}>
              {kind.replace("_", " ")}
            </button>
          ))}
        </div>
        <div className="field-grid">
          <label><span>Registry ID</span><input required pattern="[a-zA-Z0-9][a-zA-Z0-9_.-]{1,63}" value={id} onChange={(e) => setId(e.target.value)} placeholder="ops-gateway" /></label>
          <label><span>Display name</span><input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Operations gateway" /></label>
        </div>
        <label className="full-field">
          <span>{transport === "stdio" ? "Executable command" : "Server endpoint"}</span>
          <input required value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder={transport === "stdio" ? "npx" : "https://mcp.example.com/mcp"} />
        </label>
        {transport === "stdio" && (
          <label className="full-field"><span>Arguments</span><input value={args} onChange={(e) => setArgs(e.target.value)} placeholder="-y @modelcontextprotocol/server-filesystem D:\\workspace" /></label>
        )}
        <p className="transport-note">Remote authentication headers belong in backend secrets, never in browser state.</p>
        {error && <p className="form-error">{error}</p>}
        <div className="connect-actions">
          <button type="button" className="button button--quiet" onClick={onClose}>Cancel</button>
          <button className="button button--dark" disabled={working}>{working ? "Negotiating…" : "Connect server"}</button>
        </div>
      </form>
    </div>
  );
}

function ActivityStrip({ events }: { events: StreamEvent[] }) {
  const last = events.at(-1);
  if (!last) return <span>TRACE CHANNEL READY</span>;
  const label = last.event.replace("_", " ").toUpperCase();
  return <span><i className="pulse" /> {label} {last.trace_id ? `· ${last.trace_id.slice(0, 12)}` : ""}</span>;
}

export default function App() {
  const registry = useMcpRegistry();
  const chat = useChatStream();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState("");
  const [connectOpen, setConnectOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat.messages]);

  const activeServers = useMemo(
    () => selected.size ? [...selected] : registry.servers.map((server) => server.id),
    [registry.servers, selected],
  );
  const connected = registry.servers.filter((server) => server.status === "connected").length;

  const toggleServer = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!draft.trim()) return;
    void chat.send(draft, activeServers);
    setDraft("");
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="NexusMCP home"><span className="brand__mark">NX</span><span><b>NEXUS</b><em>MCP</em></span></a>
        <div className="topbar__center"><span>ENTERPRISE AGENT OPERATIONS</span><i /></div>
        <div className="topbar__health"><span className={connected ? "live" : ""}>{connected ? "NETWORK LIVE" : "NO UPLINK"}</span><b>{connected}/{registry.servers.length}</b></div>
      </header>

      <main className="workspace" id="top">
        <section className="chat panel">
          <div className="panel__heading chat__heading">
            <div><p className="eyebrow">AGENT SESSION / {chat.streamState.toUpperCase()}</p><h1>Command surface</h1></div>
            <div className="scope-badge"><span>{activeServers.length}</span> scoped nodes</div>
          </div>

          <div className="chat__stream" aria-live="polite">
            {chat.messages.length === 0 && (
              <div className="chat-empty">
                <div className="orbital-mark"><span /><i /><b>N</b></div>
                <p className="eyebrow">SECURE MODEL ↔ TOOL ROUTING</p>
                <h2>What should the network investigate?</h2>
                <p>Every call is traced. Mutations stop at the human gate.</p>
                <div className="prompt-list">
                  {PROMPTS.map((prompt, index) => <button onClick={() => setDraft(prompt)} key={prompt}><span>0{index + 1}</span>{prompt}<i>↗</i></button>)}
                </div>
              </div>
            )}
            {chat.messages.map((message) => (
              <article className={`message message--${message.role}`} key={message.id}>
                <div className="message__meta"><span>{message.role === "user" ? "OPERATOR" : "NEXUS"}</span>{message.traceId && <code>{message.traceId.slice(0, 16)}</code>}</div>
                <div className="message__content">{message.content}{message.state === "streaming" && <i className="cursor" />}</div>
              </article>
            ))}
            <div ref={bottomRef} />
          </div>

          <form className="composer" onSubmit={submit}>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              disabled={chat.streamState !== "idle"}
              placeholder={chat.streamState === "waiting" ? "Awaiting human decision…" : "Issue a command to the connected tool network…"}
              rows={2}
            />
            <div className="composer__foot">
              <ActivityStrip events={chat.activity} />
              {chat.streamState === "idle" ? (
                <button disabled={!draft.trim()} aria-label="Send message">RUN <i>↗</i></button>
              ) : (
                <button type="button" onClick={chat.stop}>STOP <i>■</i></button>
              )}
            </div>
          </form>
        </section>

        <Registry
          servers={registry.servers}
          tools={registry.tools}
          selected={selected}
          onToggle={toggleServer}
          onConnect={() => setConnectOpen(true)}
          onDisconnect={registry.disconnect}
        />
      </main>

      <footer className="footline">
        <span>NX/01</span><span>OTEL CONTEXT ACTIVE</span><span>LANGSMITH HOOK READY</span><span>{registry.error ?? (registry.loading ? "SYNCING REGISTRY" : "REGISTRY SYNCHRONIZED")}</span>
      </footer>

      {chat.pendingApproval && <ApprovalModal pending={chat.pendingApproval} onDecision={chat.decide} />}
      {connectOpen && <ConnectModal onClose={() => setConnectOpen(false)} onConnect={registry.connect} />}
    </div>
  );
}

