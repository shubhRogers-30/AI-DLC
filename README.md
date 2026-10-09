# AI-DLC Reference Implementation

Python + FastAPI + LangGraph + GitHub Copilot SDK + MCP + GitHub + Jira.

Workflow:

Jira Story -> requirements -> architecture -> HUMAN APPROVAL -> planning ->
Spring Boot Copilot coding agent -> tests -> PR -> SonarQube/CodeQL ->
quality gate -> remediation loop -> final human approval.

The implementation deliberately separates:
- LangGraph: workflow/state/orchestration
- Copilot SDK: coding-agent execution
- MCP: agent-facing enterprise tools
- GitHub Actions: deterministic CI/security gates
- Jira/GitHub/Sonar: system-of-record integrations

## Project structure

```text
app/
  api/routes/       FastAPI Jira and workflow endpoints
  agents/           Copilot SDK integration
  core/             Application configuration
  integrations/     GitHub, Jira, and SonarQube clients
  schemas/          API request and approval models
  workflow/         LangGraph state and workflow definition
  main.py           FastAPI application entry point (app.main:app)
  registry.py       Agent registry
  store.py          In-memory workflow state store
mcp_servers/
  engineering_server.py  Jira and SonarQube MCP tools
tests/              API, client, and registry tests
```

The previous module paths and `mcp_servers.engineering` command remain as
compatibility shims; the canonical implementations are in the folders above.

## Prerequisites

Python 3.11+, GitHub Copilot access, and optionally Jira/SonarQube.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m copilot download-runtime
```

Copy `.env.example` to `.env`.

## Mock mode

```bash
set MOCK_MODE=true
uvicorn app.main:app --reload
```

Create a workflow:

```bash
curl -X POST http://localhost:8000/api/workflows ^
  -H "Content-Type: application/json" ^
  -d "{\"jira_key\":\"DEMO-101\",\"repository\":\"acme/sample-springboot\",\"story\":\"Add customer eligibility endpoint\"}"
```

The graph pauses at human approval. Resume:

```bash
curl -X POST http://localhost:8000/api/workflows/<RUN_ID>/approval ^
  -H "Content-Type: application/json" ^
  -d "{\"approved\":true,\"comment\":\"Architecture approved\"}"
```

## Real mode

Set:

- `MOCK_MODE=false`
- `GITHUB_TOKEN`
- `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`
- `SONAR_URL`, `SONAR_TOKEN`
- `WORKSPACE_ROOT`

Clone the target repository under `WORKSPACE_ROOT` or let the GitHub adapter clone it.

### Jira connection

For Jira Cloud, use `JIRA_AUTH_TYPE=basic`, `JIRA_API_VERSION=3`, your
`JIRA_EMAIL`, and a Jira Cloud API token in `JIRA_API_TOKEN`.

For Jira Server/Data Center with a personal access token, use
`JIRA_AUTH_TYPE=bearer` and `JIRA_API_VERSION=2`. Set `JIRA_API_TOKEN` to the
personal access token; `JIRA_EMAIL` is not used in Bearer mode. Set
`JIRA_BASE_URL` to the Jira installation URL, including a context path such
as `/jira` if required. Restart the app after changing `.env`.

To retrieve a ticket without starting a coding workflow, open `/docs`, select
`GET /api/jira/issues/{issue_key}`, and enter a full ticket key such as
`PROJECT-123`. The response contains the key, summary and description.
The same Jira client loads the `jira_key` submitted to `POST /api/workflows`
and serves the MCP `jira_get_story` tool. Connection and permission failures
return a descriptive error instead of an unhandled server exception.

## Production hardening

- Replace `InMemorySaver` with a PostgreSQL-backed LangGraph checkpointer.
- Move long-running graph execution to a worker queue.
- Add OIDC/SSO and role-based approvals.
- Never grant the orchestration service merge-to-protected-branch or production-deploy permissions.
- Use GitHub Actions as the authoritative build/test/security gate.
- Persist agent/version/tool/audit information.
- Use stable Copilot `session_id` values for resumability.
