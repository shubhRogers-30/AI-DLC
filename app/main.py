import uuid
from fastapi import FastAPI, HTTPException
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

app = FastAPI(title="AI-DLC Orchestrator", version="0.1.0")

jira = JiraClient(
    settings.jira_base_url, settings.jira_email, settings.jira_api_token, settings.mock_mode,
    auth_type=settings.jira_auth_type, api_version=settings.jira_api_version
)
github = GitHubClient(settings.github_token, settings.github_api_url, settings.mock_mode)
sonar = SonarClient(settings.sonar_url, settings.sonar_token, settings.mock_mode)
copilot = CopilotService(settings.copilot_model, settings.mock_mode)
graph = build_graph((jira, github, sonar, copilot, settings))

@app.exception_handler(JiraError)
async def jira_error_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

@app.get("/health")
async def health():
    return {"status": "ok", "mock_mode": settings.mock_mode}

@app.get("/api/jira/issues/{issue_key}")
async def get_jira_issue(issue_key: str):
    return await jira.get_story(issue_key)

@app.post("/api/workflows")
async def create_workflow(req: WorkflowRequest):
    run_id = str(uuid.uuid4())
    workspace = (
        await github.clone_if_needed(req.repository, settings.workspace_root)
        if not settings.mock_mode else settings.workspace_root
    )
    initial = {
        "run_id": run_id,
        "status": "created",
        "jira_key": req.jira_key,
        "repository": req.repository,
        "story": req.story or "",
        "workspace": workspace,
        "remediation_attempts": 0,
        "agent_outputs": [],
        "errors": []
    }
    config = {"configurable": {"thread_id": run_id}}
    result = await graph.ainvoke(initial, config)
    await store.put(run_id, {"state": result, "config": config})
    return {"run_id": run_id, "state": result, "next": "approval required if interrupted"}

@app.get("/api/workflows/{run_id}")
async def get_workflow(run_id: str):
    item = await store.get(run_id)
    if not item:
        raise HTTPException(404, "run not found")
    return {"run_id": run_id, "state": item["state"]}

@app.post("/api/workflows/{run_id}/approval")
async def approve_workflow(run_id: str, approval: Approval):
    item = await store.get(run_id)
    if not item:
        raise HTTPException(404, "run not found")
    result = await graph.ainvoke(
        Command(resume=approval.model_dump()),
        item["config"]
    )
    await store.put(run_id, {"state": result, "config": item["config"]})
    return {"run_id": run_id, "state": result}
