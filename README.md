# NexusMCP

NexusMCP is a typed FastAPI + React operations hub for discovering MCP tools, routing model tool calls across stdio/SSE/streamable HTTP transports, and pausing sensitive mutations for explicit human approval.

## Run locally

Requirements: Python 3.11+, Node 20+, and an OpenAI API key.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Set NEXUS_OPENAI_API_KEY in .env
uvicorn main:app --reload
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. API documentation is at `http://localhost:8000/docs`.

For containers, copy `backend/.env.example` to `backend/.env`, set secrets, then run `docker compose up --build`. The UI is exposed at `http://localhost:8080`.

## Security and scaling boundaries

- Write/delete classification uses MCP annotations first and conservative name heuristics second. Tool authors should publish `readOnlyHint` and `destructiveHint` annotations.
- Approval tokens are one-shot, payload-specific, and expire. Pending state is intentionally process-local in this reference. Multi-worker deployments must put conversations and approvals in a shared store and route events through a broker before enabling more than one application worker.
- Remote authentication headers are accepted by the backend API contract but should be injected from a secret manager in production; the browser form never collects them.
- Add identity middleware and organization policy at the API gateway. The code records decisions but does not invent an enterprise identity provider.
- Diagnostic and audit JSONL streams are separated. Ship both to immutable storage with different retention/access policies.

## Checks

```powershell
cd backend
python -m compileall .
pytest

cd ..\frontend
npm run typecheck
npm run build
```

See [WORKFLOW_SPEC.md](WORKFLOW_SPEC.md) for the network trace and [STUDY_GUIDE.md](STUDY_GUIDE.md) for the architecture interview playbook.
