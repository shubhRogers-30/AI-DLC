# AI-DLC Reference Implementation

Python + FastAPI + LangGraph + GitHub Copilot SDK + MCP + GitHub + Jira.

Workflow:

Jira Story -> requirements -> architecture -> HUMAN APPROVAL -> planning ->
Stack-aware Copilot coding agent -> verified tests -> PR -> SonarQube/CodeQL ->
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
```

Copy `.env.example` to `.env`. Install/authenticate the GitHub Copilot CLI
for the user running the backend; VS Code login alone is not sufficient.
Verify `copilot --version`, then start `copilot` and use `/login` if needed.
On Windows PowerShell, use `copilot.cmd --version` and `copilot.cmd` if the
`.ps1` launcher is blocked; changing the machine execution policy is unnecessary.
The SDK uses the logged-in CLI account, not the GitHub App installation token.

## Mock mode

```bash
set MOCK_MODE=true
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Create a workflow:

```bash
curl -X POST http://localhost:8000/api/workflows ^
  -H "Content-Type: application/json" ^
  -d "{\"jira_key\":\"DEMO-101\",\"repository\":\"RogersCommunications/sample-springboot\",\"stack\":\"springboot\"}"
```

The response is HTTP 202 with a `run_id`. Poll
`GET /api/workflows/<RUN_ID>` until `phase=awaiting_approval` and
`pending_approval.type=architecture_approval`. Review the proposal, then resume:

```bash
curl -X POST http://localhost:8000/api/workflows/<RUN_ID>/approval ^
  -H "Content-Type: application/json" ^
  -d "{\"approved\":true,\"approval_type\":\"architecture_approval\",\"comment\":\"Architecture approved\"}"
```

Poll again for `merge_approval`, inspect the PR/quality evidence, then send the
same endpoint a decision with `approval_type=merge_approval`. Final success is
`phase=completed`, `state.status=approved_for_merge`; no automatic merge occurs.
Rejection terminates the run. Mock mode never edits, runs builds or calls CI.

## Real-data testing with Postman

Use a sandbox repository and a small real Jira story first. Run the service
in an isolated environment: developer agents and build scripts execute code.
Do not expose the API publicly or use production deployment credentials.

### 1. Configure credentials

Set:

- `MOCK_MODE=false`
- `API_TOKEN` to a strong local API bearer secret
- `GITHUB_ORGANIZATION=RogersCommunications`
- `GITHUB_TOKEN`, or all three `GITHUB_APP_ID`, `GITHUB_INSTALLATION_ID`,
  `GITHUB_PRIVATE_KEY_PATH` for an organization-installed GitHub App
- `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`
- `SONAR_URL`, `SONAR_TOKEN`
- `WORKSPACE_ROOT`

GitHub permissions: Contents write, Pull requests write, Actions write, and
Code scanning alerts read. With a classic PAT, equivalent access typically
requires `repo`, `workflow`, and applicable code-scanning access. Authorize
organization SSO as required. GitHub Apps can access only installed repositories;
private-repository CodeQL also requires the appropriate organization entitlement.
Keep App private keys outside repositories/workspaces. Git authentication is
injected per clone/push operation; tokens are not embedded in clone URLs.

### 2. Configure repository access

Central registration is optional. With `REPOSITORY_REGISTRY_REQUIRED=false`
(the default), accessible repositories in `GITHUB_ORGANIZATION` can start
without an entry in `config/repositories.json`. Nothing needs to be copied or
injected into target repositories. The registry file itself may also be absent.
The backend still verifies organization membership and GitHub write access.

Unregistered repositories use the repository root and the selected stack, or
stack auto-detection when none is selected. Quality defaults are
`SONAR_WORKFLOW_FILE=sonar.yml`, `CODEQL_WORKFLOW_FILE=codeql.yml`, and
`SONAR_PROJECT_KEY` if set; otherwise the project key is `owner_repository`
(for example, `RogersCommunications_rcom-store`). Set these in the orchestrator's
environment to match your CI. Startup does not verify that these workflows or
the Sonar project exist; quality checks still run and fail if they are missing.

Existing registry entries remain optional overrides for target paths, stacks,
and quality configuration. Their `enabled` flag and `setup_blockers` are enforced
only when `REPOSITORY_REGISTRY_REQUIRED=true`. That setting restores central
approval and requires each repository's quality configuration to be complete.
Default branches come from GitHub; the user chooses a base branch in the console.

### 3. Prepare tools and CI

- Spring Boot: install the repository's JDK and Maven/Gradle. Wrappers are
  preferred when present. Checks run Maven `verify` or Gradle `test build`.
- Angular: use the repository's Node/npm versions and private package registry
  authentication. The default profile requires a lockfile, `test:ci`, and
  `build:prod` scripts. Installation uses `npm ci --engine-strict`, so unsupported
  Node/npm versions fail instead of continuing with a warning. DOAT-Client-UI
  currently declares Node >=20.19 and <21; Node 22 does not meet that contract.
- Configure both named GitHub workflows with `workflow_dispatch` on the default
  branch. They must check out and analyze the dispatched branch's exact commit.
- CodeQL must analyze the target language: `java-kotlin` or
  `javascript-typescript`. A successful job alone is insufficient: an analysis
  for that SHA must exist, and any open CodeQL alert blocks approval.
- The Sonar workflow must build/test and scan with the configured project key,
  `sonar.branch.name` equal to `github.ref_name`, `sonar.scm.revision` equal to
  `github.sha`, and `sonar.qualitygate.wait=true`. Store scan credentials in
  GitHub Actions secrets. Branch analysis requires a compatible Sonar edition;
  a main-branch-only Community setup is not sufficient for this workflow.

### 4. Start one backend worker

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Do not use `--reload`, multiple workers, or restart between approvals: graph
checkpoints, run state and background tasks are currently in memory. Environment
variables override `.env`; remove stale `MOCK_MODE=true` terminal overrides.

### 5. Import and run the Postman requests individually

Import `postman/AI-DLC.postman_collection.json` and
`postman/AI-DLC.postman_environment.json`. Select the environment and replace
`api_token`, `repository`, `jira_key`, `target`, `stack`, and `approver`.
The API bearer token must match `API_TOKEN`. Do not share populated environments.

1. Health: verify `mock_mode=false`; this does not check upstream connectivity.
2. Supported stacks: inspect the registered profiles and build commands.
3. Repository discovery: verify your sandbox appears under RogersCommunications.
4. Targets: verify `enabled=true`, target path/stack, branch and quality settings.
5. Jira lookup: verify actual summary, description and acceptance criteria.
6. Start workflow: HTTP 202 saves `run_id` automatically in the environment.
   Initial cloning happens before this response; coding/CI execute in background.
7. Poll until `awaiting_approval` / `architecture_approval`; review the proposal.
8. Send architecture approval. Only now can coding, tests and publication proceed.
9. Poll through development/CI. Inspect `state.test_result.checks`, `commit_sha`,
   `pr_url`, and quality results. Wait for `merge_approval`, then review GitHub.
10. Send final approval with `approval_type=merge_approval`.
11. Poll for `completed` / `approved_for_merge`, then merge manually under normal
    branch protections. A changed branch SHA prevents stale final approval.

Do not use Run Collection: approvals require review. A wrong-stage, duplicate,
or premature approval returns 409. On `phase=failed`, inspect `state.errors`,
command output and linked CI runs; correct the underlying issue and start a new
run. Remediation is bounded and updates the existing PR rather than opening more.
Repeat with `approved=false` on a separate run: it must stop before development.
Also test a failing build/security baseline in a sandbox: it must not get merge
approval. For stories spanning two repositories, use one run per repository with
the same Jira key and agree the API contract before frontend implementation.

## Workflow Console

The separate Angular 20 console is in `frontend/`; it does not modify the
existing `workspaces/DOAT-Client-UI` application. It lists unresolved Jira
issues assigned to the Jira account configured on the backend, extracts
RogersCommunications repository links (including Jira Cloud rich-text links),
and requires an explicit repository/target choice if multiple candidates exist.
When no repository is mentioned, select one from the accessible organization
repositories. Only repositories opted in on their default branch can start.

Start the backend as described above, then run this in a second terminal:

```powershell
Set-Location frontend
npm ci
npm start
```

Open `http://127.0.0.1:4200/`. Use the generated local Postman environment's
API token in the console connection form. The token is kept in this browser's
session storage and sent only in the API Authorization header. The development
proxy forwards `/api` and `/health` to the backend, avoiding local browser CORS.

The console polls workflow state, custom stage events, and sanitized working
diffs. Its approval sequence is architecture, tested-code/pre-push review, and
final PR review. A remediation cycle returns to the code-review approval before
republishing. Final approval does not merge; merge remains a manual GitHub
action. UI visibility follows completed agent operations and 1.6-second diff
snapshots; it does not expose Copilot's private token-by-token reasoning.

Before starting, enter a new branch name and choose its base branch. The default
name is `feature/<JIRA-KEY>`. If that name already exists, the backend generates
a six-digit numeric suffix and rechecks until unused. Existing branches and PRs
are never reused. The new remote branch is created when the workflow starts;
agent code is pushed only after the pre-push approval.

### Extending stacks

Add a server-controlled JSON profile under `stacks/`, following the existing
profiles: guidance, CodeQL language, detection rules and command arrays. Restart
the backend, then reference the profile name in a target. No graph edit is
required. Commands are never accepted from API requests or repository config.
Existing matching agent instructions are loaded from `.github/agents`; otherwise
the profile's stack guidance and role instructions drive the SDK session.

### Jira connection

For Jira Cloud, use `JIRA_AUTH_TYPE=basic`, `JIRA_API_VERSION=3`, your
`JIRA_EMAIL`, and a Jira Cloud API token in `JIRA_API_TOKEN`.

For Jira Server/Data Center with a personal access token, use
`JIRA_AUTH_TYPE=bearer` and `JIRA_API_VERSION=2`. Set `JIRA_API_TOKEN` to the
personal access token; `JIRA_EMAIL` is not used in Bearer mode. Set
`JIRA_BASE_URL` to the Jira installation URL, including a context path such
as `/jira` if required. Restart the app after changing `.env`.

To retrieve a ticket without starting a coding workflow, use Postman with
`GET /api/jira/issues/{issue_key}` and the API bearer header. Enter a full ticket
key such as `PROJECT-123`. The response contains the key, summary and description.
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
- Persist Copilot session IDs for controlled resumability.
