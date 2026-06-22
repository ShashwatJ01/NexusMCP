# NexusMCP Lead AI Engineer Interview Playbook

This guide treats the workspace as a system-design case study. A strong Lead AI Engineer answer connects protocol behavior, failure containment, security policy, and operator evidence rather than discussing an agent as a single model call.

## 1. The 90-second architecture answer

NexusMCP separates four responsibilities:

1. React owns presentation, typed stream state, registry selection, and explicit human decisions.
2. FastAPI owns request validation, SSE framing, lifecycle, and the public contract.
3. The agent service owns bounded conversation memory, model/tool iteration, and semantic failure feedback.
4. The MCP host owns transport lifecycles, capability discovery, schema normalization, protocol calls, and transport spans.

The critical security boundary is between the model proposing a call and the host executing it. A call classified as write/delete becomes an immutable pending record. The agent coroutine waits; a separate HTTP request records the operator decision; only an approval for that exact record releases execution.

## 2. Distributed tracing and context propagation

### Mental model

A trace is a causally related graph of spans. Trace context is not telemetry itself; it is the compact identity (`traceparent`, optional `tracestate`) that lets independently instrumented processes attach spans to the same graph.

For an HTTP MCP server, W3C context can travel in request headers. For stdio, there is no header layer. The parent process creates a client span, instrumentation creates protocol spans, and a cooperating child needs an explicit protocol metadata convention to continue the trace. Do not silently add fields to tool arguments: strict JSON Schemas may reject them, and tool arguments are business input, not transport metadata.

### Interview question: “Where does context get lost?”

Model answer:

- Browser → FastAPI: lost unless the gateway accepts/injects `traceparent` and CORS exposes it.
- FastAPI → model provider: preserved only if the provider client is instrumented or headers are injected.
- Agent → remote MCP: propagated through W3C headers at the HTTP transport boundary.
- Agent → stdio MCP: local parent span survives, but cross-process continuation requires MCP metadata support or child bootstrap configuration.
- HITL pause → decision request: these are two HTTP requests. Store the original trace/span link on the pending record and create a linked decision span; a new request cannot magically inherit an ended browser context.
- Queues/retries: inject context into message metadata and create a consumer span; use span links for batch/fan-in rather than choosing a misleading single parent.

### Trace attributes worth keeping

Use low-cardinality resource attributes for service/environment and carefully controlled span attributes for `mcp.server.id`, `mcp.tool.name`, `mcp.transport`, `tool.access`, model name, finish reason, retry count, and approval outcome. Never attach prompts, secrets, raw tool payloads, or model responses by default. Those belong behind explicit redaction and sampling policy.

### Production checks

- Verify one trace ID spans gateway, agent loop, and remote MCP call.
- Force a tool timeout and confirm the client span is `ERROR` with a sanitized exception.
- Confirm sampling decisions are honored downstream.
- Confirm audit correlation IDs survive even when a trace is unsampled.

## 3. Semantic failure handling

Transport success is not semantic success. An HTTP 200 can contain a JSON-RPC error, and an MCP tool result can set `isError=true`. Conversely, a timeout leaves outcome ambiguity: the server may have committed a write before the response disappeared.

Classify failures into four layers:

| Layer | Example | Correct response |
|---|---|---|
| Transport | EOF, DNS failure, SSE reconnect | Mark server degraded; retry reads with bounded backoff |
| Protocol | Invalid JSON-RPC envelope, ID mismatch | Reject frame; record protocol error; do not guess |
| Tool | `isError=true`, validation error | Return structured result to model; preserve operator-readable cause |
| Semantic | Tool says “success” but invariant failed | Validate domain postconditions or perform read-after-write |

### Retry rule

Retry only when both the failure and operation are safe. Reads are usually retryable. Writes require an idempotency key understood by the server. Deletes should not be retried after an ambiguous timeout unless the operation is naturally idempotent and the server contract says so. Human approval authorizes an intent; it does not make repeated execution safe.

### Circuit breaking

Track failure rate per server/transport. Open the circuit after a threshold, fail fast while open, and allow a limited half-open probe. Keep model failures separate from MCP failures so an unhealthy provider does not label every tool server degraded.

### Good interview follow-up

“How do you prevent the model from hiding a tool failure?” Store tool outcomes as authoritative structured messages, instruct the model never to claim success without confirmation, and expose execution activity directly to the UI/audit trail. The model narrates evidence; it does not define it.

## 4. Memory management under token bloat

Token bloat has three costs: model latency/cost, degraded attention, and application memory pressure. A deque bounded by message count protects process memory but is not sufficient because one tool response may contain 100,000 characters and token density varies.

Use a layered budget:

1. Hard-cap each tool result at ingestion; store the full artifact outside the prompt.
2. Track tokens with the target model tokenizer, not character estimates alone.
3. Preserve the system policy, unresolved user intent, pending tool calls, and recent turns verbatim.
4. Summarize older turns into a versioned memory object with provenance pointers.
5. Retrieve only domain memories relevant to the current turn.
6. Recompute before every model call because tool schemas themselves consume context.

### What a safe summary contains

- Stable user preferences and constraints.
- Decisions made and who approved them.
- Resource identifiers required for subsequent calls.
- Unresolved questions and failed attempts.
- Links to complete source artifacts.

Never let a model-generated summary erase security constraints or turn an unapproved proposal into an approved fact. Policy state and approval state remain structured application data outside narrative memory.

### Capacity planning drill

If 2,000 concurrent conversations each retain 40 messages averaging 4 KB, raw content alone is roughly 320 MB before Python object overhead. Shared durable memory, TTL eviction, per-tenant quotas, and backpressure become requirements. If the system must survive worker restarts, a process-local deque is a cache, not the source of truth.

## 5. JSON-RPC network parsing

MCP messages use JSON-RPC 2.0 semantics. The three shapes are:

```json
{"jsonrpc":"2.0","id":17,"method":"tools/call","params":{"name":"search","arguments":{"q":"risk"}}}
{"jsonrpc":"2.0","id":17,"result":{"content":[{"type":"text","text":"..."}]}}
{"jsonrpc":"2.0","id":17,"error":{"code":-32602,"message":"Invalid params"}}
```

Notifications omit `id` and must not receive a response. IDs correlate responses and may be strings or numbers. A parser must not assume transport chunks equal messages:

- stdio commonly uses newline-delimited frames; buffer partial reads and enforce a maximum frame size.
- SSE provides named fields and blank-line frame termination; join multiple `data:` lines before JSON parsing.
- Streamable HTTP may return a JSON response or a stream; inspect content type and protocol version.
- Decode UTF-8 incrementally because a multi-byte character can straddle chunks.
- Validate `jsonrpc`, exclusive `result`/`error`, known response ID, and expected schema.

### Threat model

Bound frame size, nesting depth, string length, in-flight request count, and parse time. Reject duplicate object keys if the security policy requires canonical interpretation. Do not log raw frames containing secrets. Treat tool descriptions and schemas as untrusted remote input: they can contain prompt injection and pathological schemas.

### Interview trap

“Just call `json.loads()` on every socket read” is wrong. Reads are arbitrary byte chunks; one read can contain half a message or many messages. Framing belongs below JSON decoding.

## 6. HITL policy design

The UI modal is not the security boundary; the backend gate is. Browser state can be modified. A robust approval record binds:

- tenant and authenticated operator;
- conversation, model call, server, and tool;
- canonical hash of exact arguments;
- access classification and policy version;
- created/expiry time and decision reason;
- one-time nonce and final status.

For horizontally scaled workers, use a transactional shared store. Resolve approval with compare-and-set from `pending` to a terminal state, publish the result to the waiting agent, and reject duplicate decisions. On restart, pending calls should expire closed; never auto-approve.

## 7. Staff-level design questions

### “How would you scale to 10,000 live streams?”

Separate stateless HTTP ingress from long-running agent jobs. Persist event streams to a broker, expose resumable SSE with event IDs, keep MCP connection pools in dedicated workers, apply tenant concurrency quotas, and use cancellation/backpressure end to end. Sticky sessions alone are operationally fragile.

### “How do you evolve tool schemas?”

Capture the catalog version/hash used for model selection. Validate arguments against that exact schema before execution. Refresh catalogs out of band, invalidate aliases atomically, and handle a server’s `tools/list_changed` notification. Never execute arguments generated against one schema under another without revalidation.

### “How do you secure remote servers?”

Use workload identity or short-lived tokens from a secret manager, TLS with verification (mTLS where appropriate), egress allowlists, DNS rebinding defenses, request/response size bounds, and per-server policy. Do not accept arbitrary operator URLs in a high-trust production tenant without SSRF controls.

### “What SLOs would you define?”

- Availability and p95 time-to-first-token for chat.
- Tool discovery freshness.
- MCP call success/timeout rate by server.
- Approval notification latency and expiry rate.
- Trace export loss rate.
- Percentage of mutation attempts with a valid audit decision (target 100%).

## 8. Practical exercises

1. Add a fake MCP server with one read and one destructive tool; prove destructive execution never occurs before approval.
2. Split an SSE JSON event at every possible byte boundary and property-test the decoder.
3. Add token-based memory compaction and verify policy messages survive summarization.
4. Kill a remote server mid-write and document the ambiguity strategy.
5. Export traces to Jaeger/Tempo and demonstrate the HITL decision as a linked span.
6. Move approval state to a transactional store and race two decision requests; exactly one must win.

## 9. Review rubric

A lead-level response identifies boundaries and invariants before naming libraries. It distinguishes evidence from model narrative, transport failures from semantic failures, authorization from idempotency, and context windows from durable memory. It also names what this reference does not solve yet: organization identity, shared state, resumable streams, secret injection, schema-hash validation, and multi-region routing.

