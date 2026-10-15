import asyncio
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app, execute, settings, store
from app.schemas.models import Approval, WorkflowRequest
from app.configure_postman import export_environment


def test_api_runs_both_approvals_without_network(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(settings, "api_token", "")
    with TestClient(app) as client, patch("app.main.launch") as launch:
        response = client.post("/api/workflows", json={"jira_key": "TEST-123", "repository": "RogersCommunications/DOAT-Client-UI", "stack": "angular"})
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        payload = launch.call_args.args[1]
        asyncio.run(execute(run_id, payload))
        first = client.get(f"/api/workflows/{run_id}").json()
        assert first["phase"] == "awaiting_approval"
        assert first["pending_approval"]["type"] == "architecture_approval"
        assert client.post(f"/api/workflows/{run_id}/approval", json={"approved": True, "approval_type": "merge_approval"}).status_code == 409
        assert client.post(f"/api/workflows/{run_id}/approval", json={"approved": True}).status_code == 202
        assert client.post(f"/api/workflows/{run_id}/approval", json={"approved": True}).status_code == 409
        asyncio.run(execute(run_id, launch.call_args.args[1]))
        second = client.get(f"/api/workflows/{run_id}").json()
        assert second["pending_approval"]["type"] == "code_approval"
        assert client.post(f"/api/workflows/{run_id}/approval", json={"approved": True, "approval_type": "code_approval"}).status_code == 202
        asyncio.run(execute(run_id, launch.call_args.args[1]))
        second = client.get(f"/api/workflows/{run_id}").json()
        assert second["pending_approval"]["type"] == "merge_approval"
        assert client.post(f"/api/workflows/{run_id}/approval", json={"approved": True}).status_code == 202
        asyncio.run(execute(run_id, launch.call_args.args[1]))
        last = client.get(f"/api/workflows/{run_id}").json()
        assert last["phase"] == "completed"
        assert last["state"]["status"] == "approved_for_merge"


def test_real_mode_requires_api_authentication(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "api_token", "test-api-token")
    with TestClient(app) as client:
        assert client.get("/api/stacks").status_code == 401
        assert client.get("/api/stacks", headers={"Authorization": "Bearer test-api-token"}).status_code == 200


def test_outside_org_and_discovery(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(settings, "api_token", "")
    with TestClient(app) as client:
        assert client.post("/api/workflows", json={"jira_key": "TEST-123", "repository": "other/repo"}).status_code == 403
        assert client.get("/api/repositories").json()["organization"] == "RogersCommunications"
        assert client.get("/api/repositories/RogersCommunications/DOAT-Client-UI/targets").json()["targets"][0]["stack"] == "angular"


def test_assigned_issues_endpoint_uses_backend_jira_identity(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(settings, "api_token", "")
    with TestClient(app) as client, patch("app.main.jira.assigned_issues", new=AsyncMock(return_value={"issues": [], "next_page": None})) as assigned:
        response = client.get("/api/jira/my-issues")
    assert response.status_code == 200
    assigned.assert_awaited_once_with("RogersCommunications", 50, 0)


def test_workflow_rejects_repository_conflicting_with_description(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(settings, "api_token", "")
    story = {"key": "TEST-123", "summary": "Story", "description": "https://github.com/RogersCommunications/api-service"}
    with TestClient(app) as client, patch("app.main.jira.get_story", new=AsyncMock(return_value=story)):
        response = client.post("/api/workflows", json={
            "jira_key": "TEST-123", "repository": "RogersCommunications/web-client",
        })
    assert response.status_code == 422
    assert response.json()["detail"]["repository_candidates"] == ["RogersCommunications/api-service"]


def test_existing_branch_requires_explicit_reuse_confirmation(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(settings, "api_token", "")
    with TestClient(app) as client:
        body = {"jira_key": "TEST-123", "repository": "RogersCommunications/demo", "target": "default",
            "stack": "angular", "branch_name": "main", "base_branch": "develop"}
        conflict = client.post("/api/workflows", json=body)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "branch_exists"
        assert conflict.json()["detail"]["branch"]["exists"] is True
        body["reuse_existing_branch"] = True
        protected = client.post("/api/workflows", json=body)
        assert protected.status_code == 409
        assert protected.json()["detail"]["code"] == "branch_protected"
        body.update(branch_name="develop", base_branch="main")
        accepted = client.post("/api/workflows", json=body)
        assert accepted.status_code == 202
        run_id = accepted.json()["run_id"]
        assert accepted.json()["state"]["branch"] == "develop"
        assert asyncio.run(store.get(run_id))["events"][0]["status"] == "branch_reused"


def test_worker_failure_is_saved(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(settings, "api_token", "")
    story = {"key": "TEST-123", "summary": "A ticket", "description": "No repository reference", "acceptance_criteria": []}
    with TestClient(app) as client, patch("app.main.launch") as launch, patch("app.main.jira.get_story", new=AsyncMock(return_value=story)), patch("app.main.copilot.run_agent", new=AsyncMock(side_effect=RuntimeError("private secret"))):
        response = client.post("/api/workflows", json={"jira_key": "TEST-123", "repository": "RogersCommunications/service"})
        run_id = response.json()["run_id"]
        asyncio.run(execute(run_id, launch.call_args.args[1]))
        result = client.get(f"/api/workflows/{run_id}").json()
        assert result["phase"] == "failed"
        assert "private secret" not in str(result)


def test_actual_background_scheduling(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(settings, "api_token", "")
    with TestClient(app) as client:
        response = client.post("/api/workflows", json={"jira_key": "TEST-123", "repository": "RogersCommunications/DOAT-Client-UI"})
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        for _ in range(100):
            result = client.get(f"/api/workflows/{run_id}").json()
            if result["phase"] != "running":
                break
        assert result["phase"] == "awaiting_approval"
        assert result["pending_approval"]["type"] == "architecture_approval"
        client.post(f"/api/workflows/{run_id}/approval", json={"approved": False, "approval_type": "architecture_approval"})
        for _ in range(100):
            result = client.get(f"/api/workflows/{run_id}").json()
            if result["phase"] != "running":
                break
        assert result["phase"] == "completed"
        assert result["state"]["status"] == "rejected"


@pytest.mark.parametrize("stack", ["springboot", "angular"])
def test_full_background_workflow_over_api(monkeypatch, stack):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(settings, "api_token", "")
    with TestClient(app) as client:
        response = client.post("/api/workflows", json={
            "jira_key": "TEST-123", "repository": "RogersCommunications/demo", "stack": stack,
            "branch_name": f"feature/{stack}-TEST-123", "base_branch": "develop",
        })
        assert response.status_code == 202
        run_id = response.json()["run_id"]

        def poll_phase():
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = client.get(f"/api/workflows/{run_id}")
                assert result.status_code == 200
                payload = result.json()
                if payload["phase"] != "running":
                    return payload
            pytest.fail("Background workflow did not reach its next checkpoint")

        architecture = poll_phase()
        assert architecture["phase"] == "awaiting_approval"
        assert architecture["pending_approval"]["type"] == "architecture_approval"
        assert architecture["state"]["stack"] == stack
        assert architecture["state"]["branch"] == f"feature/{stack}-TEST-123"
        assert architecture["state"]["repo_config"]["default_branch"] == "develop"
        response = client.post(f"/api/workflows/{run_id}/approval", json={
            "approved": True, "approval_type": "architecture_approval", "approver": "test-reviewer",
        })
        assert response.status_code == 202
        review = poll_phase()
        assert review["phase"] == "awaiting_approval"
        assert review["pending_approval"]["type"] == "code_approval"
        response = client.post(f"/api/workflows/{run_id}/approval", json={
            "approved": True, "approval_type": "code_approval", "approver": "test-reviewer",
        })
        assert response.status_code == 202
        review = poll_phase()
        assert review["phase"] == "awaiting_approval"
        assert review["pending_approval"]["type"] == "merge_approval"
        assert review["state"]["test_result"]["status"] == "PASSED"
        assert review["state"]["quality_result"]["passed"] is True
        assert review["state"]["pr_url"].startswith("https://github.com/RogersCommunications/demo/pull/")
        response = client.post(f"/api/workflows/{run_id}/approval", json={
            "approved": True, "approval_type": "merge_approval", "approver": "test-reviewer",
        })
        assert response.status_code == 202
        completed = poll_phase()
        assert completed["phase"] == "completed"
        assert completed["pending_approval"] is None
        assert completed["state"]["status"] == "approved_for_merge"
        events = client.get(f"/api/workflows/{run_id}/events").json()["events"]
        assert any(event.get("stage") == "develop" and event["event"] == "started" for event in events)
        assert any(event.get("stage") == "create_pr" and event["event"] == "completed" for event in events)
        assert [event["approval_type"] for event in events if event["event"] == "awaiting_approval"] == [
            "architecture_approval", "code_approval", "merge_approval",
        ]
        assert events[0]["stage"] == "branch"
        assert client.get(f"/api/workflows/{run_id}/diff").json()["diff"] == ""


def test_postman_collection_json_and_request_contracts():
    root = Path(__file__).resolve().parents[1] / "postman"
    collection = json.loads((root / "AI-DLC.postman_collection.json").read_text(encoding="utf-8"))
    environment = json.loads((root / "AI-DLC.postman_environment.json").read_text(encoding="utf-8"))
    values = {item["key"]: item["value"] for item in environment["values"]}
    assert len(collection["item"]) == 13
    assert collection["auth"]["type"] == "bearer"
    for item in collection["item"]:
        request = item["request"]
        if "body" not in request:
            continue
        raw = request["body"]["raw"]
        for key, value in values.items():
            raw = raw.replace("{{" + key + "}}", value)
        payload = json.loads(raw)
        if request["url"].endswith("/approval"):
            Approval.model_validate(payload)
        else:
            WorkflowRequest.model_validate(payload)


def test_live_diff_includes_new_files_and_redacts_environment_files(tmp_path, monkeypatch):
    repository = tmp_path / "run" / "repository"
    repository.mkdir(parents=True)
    git_env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args):
        subprocess.run(["git", *args], cwd=repository, env=git_env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    source = repository / "src" / "app.ts"
    source.parent.mkdir()
    source.write_text("export const value = 'base';\n", encoding="utf-8")
    secret_file = repository / ".env"
    secret_file.write_text("TOKEN=secret-before\n", encoding="utf-8")
    git("add", "--all")
    git("commit", "-m", "base")
    base_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, env=git_env, text=True).strip()
    source.write_text("export const value = 'changed';\n", encoding="utf-8")
    secret_file.write_text("TOKEN=secret-after\n", encoding="utf-8")
    (repository / "new-test.spec.ts").write_text("describe('change', () => {});\n", encoding="utf-8")

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "api_token", "local-test-token")
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    run_id = str(uuid.uuid4())
    asyncio.run(store.put(run_id, {
        "state": {"repository_workspace": str(repository), "base_sha": base_sha},
        "config": {}, "phase": "running", "pending_approval": None,
    }))
    with TestClient(app) as client:
        response = client.get(f"/api/workflows/{run_id}/diff", headers={"Authorization": "Bearer local-test-token"})
    assert response.status_code == 200
    assert "src/app.ts" in response.json()["files"]
    assert "new-test.spec.ts" in response.json()["files"]
    assert ".env" not in response.json()["diff"]
    assert "secret-before" not in response.json()["diff"]
    assert "secret-after" not in response.json()["diff"]


def test_local_postman_export_preserves_settings_and_template(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "test-only-api-secret")
    template = Path(__file__).resolve().parents[1] / "postman" / "AI-DLC.postman_environment.json"
    before = template.read_bytes()
    destination = tmp_path / "AI-DLC.local.postman_environment.json"
    export_environment(destination)
    environment = json.loads(destination.read_text(encoding="utf-8"))
    token = next(item for item in environment["values"] if item["key"] == "api_token")
    assert token["value"] == "test-only-api-secret"
    assert token["type"] == "secret"
    repository = next(item for item in environment["values"] if item["key"] == "repository")
    repository["value"] = "RogersCommunications/my-sandbox"
    destination.write_text(json.dumps(environment), encoding="utf-8")
    monkeypatch.setattr(settings, "api_token", "replacement-test-secret")
    export_environment(destination)
    updated = json.loads(destination.read_text(encoding="utf-8"))
    assert next(item for item in updated["values"] if item["key"] == "repository")["value"] == "RogersCommunications/my-sandbox"
    assert next(item for item in updated["values"] if item["key"] == "api_token")["value"] == "replacement-test-secret"
    assert template.read_bytes() == before