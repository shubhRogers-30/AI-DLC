import uuid
import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from langgraph.types import Command
from app.config import settings
from app.models import WorkflowRequest, Approval
from app.store import store
from app.clients.jira import JiraClient, JiraError
from app.clients.github import GitHubClient
from app.clients.sonar import SonarClient
from app.copilot_service import CopilotService
from app.graph import build_graph
from app.integrations.github_client import GitHubError
from app.execution import run_command
from pathlib import Path
import asyncio
from datetime import datetime, timezone
from app.repositories import RepositoryConfig, Target, select_target, resolve_workspace, repository_registry
from app.stacks import stacks
from app.jira_tickets import repository_candidates

tasks = set()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    yield
    for task in list(tasks):
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def authorize(request: Request):
    if request.url.path == "/health":
        return
    if not settings.mock_mode and not settings.api_token:
        raise HTTPException(503, "Set API_TOKEN before enabling real-mode API access")
    if settings.api_token and not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {settings.api_token}"):
        raise HTTPException(401, "Valid API bearer token required")


app = FastAPI(title="AI-DLC Orchestrator", version="0.2.0", lifespan=lifespan, dependencies=[Depends(authorize)])

jira = JiraClient(
    settings.jira_base_url, settings.jira_email, settings.jira_api_token, settings.mock_mode,
    auth_type=settings.jira_auth_type, api_version=settings.jira_api_version
)
github = GitHubClient(settings.github_token, settings.github_api_url, settings.mock_mode,
                      settings.github_organization, settings.github_app_id,
                      settings.github_installation_id, settings.github_private_key_path)
sonar = SonarClient(settings.sonar_url, settings.sonar_token, settings.mock_mode)
copilot = CopilotService(settings.copilot_model, settings.mock_mode, settings.agent_timeout_seconds)
graph = build_graph((jira, github, sonar, copilot, settings))

@app.exception_handler(JiraError)
async def jira_error_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(GitHubError)
async def github_error_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def configuration_error_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": "Invalid repository configuration, target, or stack: " + str(exc)})


def response_for(run_id, item):
    return {"run_id": run_id, "phase": item["phase"], "state": item["state"],
            "pending_approval": item.get("pending_approval")}


async def execute(run_id, payload):
    item = await store.get(run_id)
    config = item["config"]
    state = item["state"]
    try:
        await store.add_event(run_id, {"time": datetime.now(timezone.utc).isoformat(), "event": "workflow_started"})
        async for mode, update in graph.astream(payload, config, stream_mode=["custom", "values"]):
            if mode == "custom":
                await store.add_event(run_id, {"time": datetime.now(timezone.utc).isoformat(), **update})
                continue
            if "__interrupt__" not in update:
                state = dict(update)
                await store.update(run_id, state=state, config=config, phase="running", pending_approval=None)
        snapshot = await graph.aget_state(config)
        state = dict(snapshot.values)
        interrupts = [interrupt for task in snapshot.tasks for interrupt in task.interrupts]
        pending = interrupts[0].value if interrupts else None
        phase = "awaiting_approval" if pending else "failed" if state.get("status") == "failed" else "completed"
        await store.update(run_id, state=state, config=config, phase=phase, pending_approval=pending)
        await store.add_event(run_id, {"time": datetime.now(timezone.utc).isoformat(), "event": phase,
                          "approval_type": pending.get("type") if pending else None})
    except Exception as error:
        message = str(error) if isinstance(error, (GitHubError, JiraError)) else f"{type(error).__name__}: execution failed; check runtime authentication, build tools and CI configuration"
        logger.error("Workflow %s failed (%s)", run_id, type(error).__name__)
        state = {**state, "status": "failed", "errors": state.get("errors", []) + [message]}
        await store.update(run_id, state=state, config=config, phase="failed", pending_approval=None)
        await store.add_event(run_id, {"time": datetime.now(timezone.utc).isoformat(), "event": "failed", "error": message})


def launch(run_id, payload):
    task = asyncio.create_task(execute(run_id, payload))
    tasks.add(task)
    task.add_done_callback(tasks.discard)

@app.get("/health")
async def health():
    return {"status": "ok", "mock_mode": settings.mock_mode}

@app.get("/api/jira/issues/{issue_key}")
async def get_jira_issue(issue_key: str):
    return await jira.get_story(issue_key)


@app.get("/api/jira/my-issues")
async def get_my_jira_issues(page_size: int = 50, start_at: int = 0):
    return await jira.assigned_issues(settings.github_organization, page_size, start_at)


@app.get("/api/stacks")
async def list_stacks():
    return {"stacks": [{"name": profile.name, "display_name": profile.display_name,
                        "codeql_language": profile.codeql_language, "commands": profile.commands}
                       for profile in stacks.profiles.values()]}


@app.get("/api/repositories")
async def list_repositories():
    repositories = await github.list_repositories()
    for repository in repositories:
        config = repository_registry.get(repository["full_name"])
        repository.update({"ai_dlc_approved": repository_registry.is_approved(repository["full_name"]),
                           "workflow_ready": config.workflow_ready,
                           "setup_blockers": config.setup_blockers})
    return {"organization": settings.github_organization, "repositories": repositories}


async def repository_configuration(repo):
    metadata = await github.repository(repo)
    if settings.mock_mode:
        config = repository_registry.get(metadata["full_name"])
        if not repository_registry.is_approved(metadata["full_name"]):
            profile = "angular" if repo.lower().endswith("ui") else "springboot"
            config = RepositoryConfig(enabled=True, targets=[Target(name="default", stack=profile)])
        config = config.model_copy(update={
            "quality": {"sonar_project_key": "mock", "sonar_workflow": "sonar.yml", "codeql_workflow": "codeql.yml"},
            "setup_blockers": [],
        })
    else:
        config = repository_registry.get(metadata["full_name"])
    return metadata, config


@app.get("/api/repositories/{owner}/{name}/targets")
async def repository_targets(owner: str, name: str):
    metadata, config = await repository_configuration(f"{owner}/{name}")
    return {"repository": metadata["full_name"], "default_branch": metadata["default_branch"],
            "approved": config.enabled, "workflow_ready": config.workflow_ready, **config.model_dump()}


@app.get("/api/repositories/{owner}/{name}/branches")
async def list_repository_branches(owner: str, name: str):
    repo = f"{owner}/{name}"
    metadata = await github.repository(repo)
    branches = await github.list_branches(metadata["full_name"])
    return {"repository": metadata["full_name"], "default_branch": metadata["default_branch"],
            "branches": branches}


@app.get("/api/repositories/{owner}/{name}/branch-check")
async def check_repository_branch(owner: str, name: str, branch: str, base_branch: str):
    return await github.available_branch_name(f"{owner}/{name}", branch, base_branch)


@app.post("/api/workflows", status_code=202)
async def create_workflow(req: WorkflowRequest):
    story = await jira.get_story(req.jira_key)
    candidates = repository_candidates(story.get("description", ""), settings.github_organization)
    if candidates and req.repository.casefold() not in {candidate.casefold() for candidate in candidates}:
        raise HTTPException(422, detail={"message": "Selected repository conflicts with the Jira description", "repository_candidates": candidates})
    metadata, repo = await repository_configuration(req.repository)
    if not repo.enabled:
        raise HTTPException(403, "Repository is not centrally approved for AI-DLC. Ask an orchestrator administrator to add it to config/repositories.json.")
    if not repo.workflow_ready:
        raise HTTPException(422, detail={
            "message": "Repository is centrally approved but its CI quality configuration is incomplete.",
            "setup_blockers": repo.setup_blockers or ["Configure SonarQube and CodeQL workflows in the central registry."],
        })
    if not settings.mock_mode and (not settings.sonar_url or not settings.sonar_token):
        raise HTTPException(503, "Configure SONAR_URL and SONAR_TOKEN before starting a real workflow")
    target = select_target(repo, req.target, None if settings.mock_mode else req.stack)
    repository = metadata["full_name"]
    run_id = str(uuid.uuid4())
    requested_branch = req.branch_name or f"feature/{req.jira_key}"
    github.validate_branch_name(requested_branch)
    base_branch = req.base_branch or metadata["default_branch"]
    github.validate_branch_name(base_branch)
    if settings.mock_mode:
        branch_selection = await github.available_branch_name(repository, requested_branch, base_branch)
        branch = branch_selection["branch_name"]
        workspace = repository_workspace = settings.workspace_root
        base_sha = None
        profile = stacks.get(req.stack or target.stack or "springboot")
    else:
        repository_workspace, branch, branch_selection = await github.prepare_workspace(
            repository, settings.workspace_root, run_id, requested_branch, base_branch,
        )
        base_sha = await github.local_sha(repository_workspace)
        workspace = resolve_workspace(repository_workspace, target)
        profile = stacks.get(req.stack or target.stack) if req.stack or target.stack else stacks.detect(workspace)
        profile.checks(workspace)
    initial = {
        "run_id": run_id,
        "status": "created",
        "jira_key": req.jira_key,
        "repository": repository,
        "story": req.story or "",
        "requirements": story,
        "workspace": workspace,
        "repository_workspace": repository_workspace,
        "stack": profile.name,
        "target": target.name,
        "branch": branch,
        "base_sha": base_sha,
        "repo_config": {"default_branch": base_branch, "quality": repo.quality.model_dump()},
        "remediation_attempts": 0,
        "agent_outputs": [],
        "errors": []
    }
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 100}
    item = {"state": initial, "config": config, "phase": "running", "pending_approval": None, "events": []}
    await store.put(run_id, item)
    await store.add_event(run_id, {
        "time": datetime.now(timezone.utc).isoformat(),
        "stage": "branch",
        "event": "completed",
        "status": "branch_created",
        "requested_branch": requested_branch,
        "branch": branch,
        "base_branch": base_branch,
        "collision_count": branch_selection["collision_count"],
    })
    launch(run_id, initial)
    return response_for(run_id, item)

@app.get("/api/workflows/{run_id}")
async def get_workflow(run_id: str):
    item = await store.get(run_id)
    if not item:
        raise HTTPException(404, "run not found")
    return response_for(run_id, item)


@app.get("/api/workflows/{run_id}/events")
async def get_workflow_events(run_id: str, after: int = 0):
    item = await store.get(run_id)
    if not item:
        raise HTTPException(404, "run not found")
    return {"events": [event for event in item.get("events", []) if event["id"] > after]}


@app.get("/api/workflows/{run_id}/diff")
async def get_workflow_diff(run_id: str):
    item = await store.get(run_id)
    if not item:
        raise HTTPException(404, "run not found")
    state = item["state"]
    if settings.mock_mode:
        return {"base_sha": None, "files": [], "diff": "", "updated_at": datetime.now(timezone.utc).isoformat()}
    workspace = Path(state["repository_workspace"]).resolve()
    root = Path(settings.workspace_root).resolve()
    if not workspace.is_relative_to(root) or not (workspace / ".git").is_dir():
        raise HTTPException(409, "Workflow workspace is unavailable")
    base_sha = state.get("base_sha")
    if not base_sha:
        return {"base_sha": None, "files": [], "diff": "", "updated_at": datetime.now(timezone.utc).isoformat()}
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("GITHUB_", "GH_TOKEN", "JIRA_", "SONAR_", "API_TOKEN", "GIT_CONFIG_"))}
    changed = await run_command(["git", "diff", "--name-only", base_sha, "--"], workspace, timeout=30, env=env)
    if not changed["passed"]:
        raise HTTPException(502, "Could not read workflow diff")
    safe_paths = [name for name in changed["output"].splitlines()
                  if Path(name).name != ".env" and not (Path(name).name.startswith(".env.") and Path(name).name != ".env.example")
                  and Path(name).suffix.lower() not in {".pem", ".key"}][:50]
    result = await run_command(["git", "diff", "--no-ext-diff", "--no-color", "--unified=3", base_sha, "--", *safe_paths],
                               workspace, timeout=30, env=env, output_limit=100000) if safe_paths else {"passed": True, "output": ""}
    if not result["passed"]:
        raise HTTPException(502, "Could not read workflow diff")
    untracked = await run_command(["git", "ls-files", "--others", "--exclude-standard"], workspace, timeout=30, env=env)
    additions = []
    if untracked["passed"]:
        for name in untracked["output"].splitlines()[:50]:
            path = (workspace / name).resolve()
            if not path.is_relative_to(workspace) or Path(name).name == ".env" or Path(name).name.startswith(".env.") and Path(name).name != ".env.example" or Path(name).suffix.lower() in {".pem", ".key"}:
                continue
            if not path.is_file() or path.stat().st_size > 20000:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeError, OSError):
                continue
            if "\x00" in content:
                continue
            additions.append(f"diff --git a/{name} b/{name}\nnew file mode 100644\n--- /dev/null\n+++ b/{name}\n" +
                             "".join(f"+{line}\n" for line in content.splitlines()))
    diff = result["output"] + "\n".join(additions)
    if len(diff) > 100000:
        diff = diff[:100000] + "\n[Diff truncated at 100 KB]"
    files = sorted(set(line[6:] for line in diff.splitlines() if line.startswith("+++ b/")))
    return {"base_sha": base_sha, "files": files, "diff": diff,
            "updated_at": datetime.now(timezone.utc).isoformat()}

@app.post("/api/workflows/{run_id}/approval", status_code=202)
async def approve_workflow(run_id: str, approval: Approval):
    item = await store.get(run_id)
    if not item:
        raise HTTPException(404, "run not found")
    expected = (item.get("pending_approval") or {}).get("type")
    if expected and (approval.approval_type is not None or not settings.mock_mode) and approval.approval_type != expected:
        raise HTTPException(409, f"Expected approval_type={expected}")
    if not await store.claim_approval(run_id):
        raise HTTPException(409, "Workflow is not awaiting approval; poll its phase first")
    launch(run_id, Command(resume=approval.model_dump()))
    return response_for(run_id, await store.get(run_id))
