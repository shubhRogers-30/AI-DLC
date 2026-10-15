import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.integrations.github_client import GitHubClient, GitHubError


def test_organization_boundary():
    client = GitHubClient("token", "https://api.github.com")
    client.validate_repository("RogersCommunications/DOAT-Client-UI")
    for repo in ("other/repo", "https://github.com/RogersCommunications/repo", "RogersCommunications/../repo"):
        with pytest.raises(GitHubError):
            client.validate_repository(repo)


def test_branch_names_are_validated():
    client = GitHubClient("token", "https://api.github.com")
    assert client.validate_branch_name("feature/TEST-123-ui") == "feature/TEST-123-ui"
    for branch in ("", "../main", "feature//test", "feature name", "main.lock", "feature/@{work}"):
        with pytest.raises(GitHubError):
            client.validate_branch_name(branch)


def test_branch_summary_shows_mock_collision_and_base_options():
    client = GitHubClient("token", "https://api.github.com", mock=True)
    assert asyncio.run(client.list_branches("RogersCommunications/demo")) == [
        {"name": "main", "protected": True}, {"name": "develop", "protected": False},
    ]
    branch = asyncio.run(client.branch_summary("RogersCommunications/demo", "main", "develop"))
    assert branch["exists"]
    assert branch["base_branch"] == "develop"
    assert not branch["open_pull_requests"]


def test_workspace_creates_remote_branch_before_clone_and_reuses_on_confirmation(tmp_path):
    async def scenario():
        client = GitHubClient("token", "https://api.github.com")
        client.branch_summary = AsyncMock(side_effect=[
            {"exists": False, "name": "feature/story", "base_branch": "main"},
            {"exists": True, "name": "feature/story", "base_branch": "main"},
        ])
        client.create_branch = AsyncMock()
        client._git = AsyncMock(return_value="")
        first, new_summary = await client.prepare_workspace(
            "RogersCommunications/demo", str(tmp_path), "new-run", "feature/story", "main",
        )
        client.create_branch.assert_awaited_once_with("RogersCommunications/demo", "feature/story", "main")
        assert Path(first).name == "demo"
        assert not new_summary["exists"]
        assert client._git.call_args_list[0].args[0][1:4] == ["--branch", "feature/story", "--single-branch"]
        client.create_branch.reset_mock()
        second, reused_summary = await client.prepare_workspace(
            "RogersCommunications/demo", str(tmp_path), "reuse-run", "feature/story", "main", True,
        )
        client.create_branch.assert_not_awaited()
        assert Path(second).parent.name == "reuse-run"
        assert reused_summary["exists"]
    asyncio.run(scenario())


def test_discovery_paginates_and_filters():
    client = GitHubClient("token", "https://api.github.com")
    valid = {"full_name": "RogersCommunications/service", "default_branch": "develop",
             "owner": {"login": "RogersCommunications"}}
    client._request = AsyncMock(side_effect=[[dict(valid, archived=True)] * 100, [valid]])
    assert asyncio.run(client.list_repositories()) == [{"full_name": valid["full_name"], "default_branch": "develop"}]
    assert client._request.await_count == 2


def test_wait_ignores_old_and_wrong_commit_runs():
    client = GitHubClient("token", "https://api.github.com")
    old = {"id": 1, "head_sha": "correct", "status": "completed", "conclusion": "success"}
    wrong = {"id": 2, "head_sha": "wrong", "status": "completed", "conclusion": "success"}
    fresh = {"id": 3, "head_sha": "correct", "status": "completed", "conclusion": "success", "html_url": "url"}
    client._runs = AsyncMock(side_effect=[[old], [wrong, old], [fresh, wrong, old]])
    client.trigger_workflow = AsyncMock()
    with patch("app.integrations.github_client.asyncio.sleep", new=AsyncMock()):
        result = asyncio.run(client.dispatch_and_wait("RogersCommunications/repo", "codeql.yml", "branch", "correct"))
    assert result["id"] == 3


def test_publish_refuses_wrong_branch():
    client = GitHubClient("token", "https://api.github.com")
    client._git = AsyncMock(return_value="main")
    with pytest.raises(GitHubError, match="working branch"):
        asyncio.run(client.publish("workspace", "ai-dlc/story", "story"))
    assert client._git.await_count == 1


def test_codeql_job_success_is_not_enough():
    client = GitHubClient("token", "https://api.github.com")
    client._request = AsyncMock(side_effect=[[{"commit_sha": "correct"}],
                                            [{"number": 1, "rule": {"id": "unsafe"}, "html_url": "url"}]])
    result = asyncio.run(client.codeql_gate("RogersCommunications/repo", "branch", "correct"))
    assert not result["passed"]
    assert result["alerts"][0]["rule"] == "unsafe"


def test_codeql_requires_exact_commit_analysis():
    client = GitHubClient("token", "https://api.github.com")
    client._request = AsyncMock(return_value=[{"commit_sha": "old"}])
    assert not asyncio.run(client.codeql_gate("RogersCommunications/repo", "branch", "correct"))["passed"]


def test_app_cannot_authorize_public_repo_outside_installation():
    client = GitHubClient("token", "https://api.github.com", app_id="1")
    client._installation_permissions = {"contents": "write"}
    client._request = AsyncMock(return_value={"full_name": "RogersCommunications/public", "default_branch": "main"})
    client.list_repositories = AsyncMock(return_value=[{"full_name": "RogersCommunications/installed"}])
    with pytest.raises(GitHubError, match="write access"):
        asyncio.run(client.repository("RogersCommunications/public"))


def test_app_can_authorize_installed_writable_repo():
    client = GitHubClient("token", "https://api.github.com", app_id="1")
    client._installation_permissions = {"contents": "write"}
    metadata = {"full_name": "RogersCommunications/installed", "default_branch": "main"}
    client._request = AsyncMock(return_value=metadata)
    client.list_repositories = AsyncMock(return_value=[metadata])
    assert asyncio.run(client.repository(metadata["full_name"])) == metadata