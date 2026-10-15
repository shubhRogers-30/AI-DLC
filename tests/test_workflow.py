import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.types import Command

from app.integrations.github_client import GitHubClient
from app.integrations.jira_client import JiraClient
from app.integrations.sonarqube_client import SonarClient
from app.agents.copilot_service import CopilotService
from app.workflow.graph import build_graph


def make_graph(mock=True, attempts=0):
    github = GitHubClient("", "https://api.github.com", mock=True)
    copilot = CopilotService(mock=True)
    settings = SimpleNamespace(mock_mode=mock, max_remediation_attempts=attempts,
                               command_timeout_seconds=60, ci_timeout_seconds=60, ci_poll_interval_seconds=1)
    graph = build_graph((JiraClient("", "", "", mock=True), github, SonarClient("", "", mock=True), copilot, settings))
    return graph, github, copilot


def initial(stack="springboot"):
    return {"run_id": "test-run", "jira_key": "TEST-123", "repository": "RogersCommunications/service",
            "stack": stack, "workspace": ".", "repository_workspace": ".", "branch": "ai-dlc/test",
            "repo_config": {"default_branch": "develop", "quality": {"codeql_workflow": "codeql.yml", "sonar_workflow": "sonar.yml", "sonar_project_key": "service"}},
            "agent_outputs": [], "errors": [], "remediation_attempts": 0}


@pytest.mark.parametrize("stack", ["springboot", "angular"])
def test_three_approvals_and_stack_routing(stack):
    async def scenario():
        graph, github, copilot = make_graph()
        github.create_pr = AsyncMock(wraps=github.create_pr)
        copilot.run_agent = AsyncMock(wraps=copilot.run_agent)
        config = {"configurable": {"thread_id": "run"}}
        first = await graph.ainvoke(initial(stack), config)
        assert first["__interrupt__"][0].value["type"] == "architecture_approval"
        second = await graph.ainvoke(Command(resume={"approved": True}), config)
        assert second["__interrupt__"][0].value["type"] == "code_approval"
        second = await graph.ainvoke(Command(resume={"approved": True}), config)
        assert second["__interrupt__"][0].value["type"] == "merge_approval"
        assert second["quality_result"]["passed"]
        assert github.create_pr.call_args.args[3] == "develop"
        names = [call.args[0] for call in copilot.run_agent.call_args_list]
        assert names == [f"{stack}-architect", f"{stack}-developer", f"{stack}-test-generator"]
        last = await graph.ainvoke(Command(resume={"approved": True}), config)
        assert last["status"] == "approved_for_merge"
    asyncio.run(scenario())


def test_architecture_rejection_does_not_code():
    async def scenario():
        graph, github, copilot = make_graph()
        copilot.run_agent = AsyncMock(wraps=copilot.run_agent)
        config = {"configurable": {"thread_id": "rejection"}}
        await graph.ainvoke(initial(), config)
        result = await graph.ainvoke(Command(resume={"approved": False}), config)
        assert result["status"] == "rejected"
        assert copilot.run_agent.await_count == 1
    asyncio.run(scenario())


def test_real_test_failure_never_creates_pr():
    async def scenario():
        graph, github, copilot = make_graph(mock=False)
        github.create_pr = AsyncMock()
        config = {"configurable": {"thread_id": "failure"}}
        await graph.ainvoke(initial("angular"), config)
        with patch("app.workflow.graph.run_command", new=AsyncMock(return_value={"passed": False, "exit_code": 1, "output": "failed"})):
            result = await graph.ainvoke(Command(resume={"approved": True}), config)
        assert result["status"] == "failed"
        assert result["test_result"]["status"] == "FAILED"
        github.create_pr.assert_not_called()
    asyncio.run(scenario())


def test_remediation_reuses_pr():
    async def scenario():
        graph, github, copilot = make_graph(attempts=1)
        github.create_pr = AsyncMock(wraps=github.create_pr)
        github.dispatch_and_wait = AsyncMock(side_effect=[
            {"conclusion": "failure"}, {"conclusion": "success"},
            {"conclusion": "success"}, {"conclusion": "success"},
        ])
        config = {"configurable": {"thread_id": "remediation"}, "recursion_limit": 100}
        await graph.ainvoke(initial("angular"), config)
        result = await graph.ainvoke(Command(resume={"approved": True}), config)
        assert result["__interrupt__"][0].value["type"] == "code_approval"
        result = await graph.ainvoke(Command(resume={"approved": True}), config)
        assert result["__interrupt__"][0].value["type"] == "code_approval"
        result = await graph.ainvoke(Command(resume={"approved": True}), config)
        assert result["quality_result"]["passed"]
        assert result["remediation_attempts"] == 1
        assert github.create_pr.await_count == 1
    asyncio.run(scenario())


def test_non_mock_success_publishes_before_pr(tmp_path):
    async def scenario():
        graph, github, copilot = make_graph(mock=False)
        github.publish = AsyncMock(return_value="verified-sha")
        github.branch_sha = AsyncMock(return_value="verified-sha")

        async def create_pr(*args):
            github.publish.assert_awaited_once()
            return {"number": 7, "html_url": "https://github.com/RogersCommunications/service/pull/7"}

        github.create_pr = AsyncMock(side_effect=create_pr)
        config = {"configurable": {"thread_id": "real-success"}}
        state = initial("angular")
        state["workspace"] = state["repository_workspace"] = str(tmp_path)
        await graph.ainvoke(state, config)
        with patch("app.workflow.graph.run_command", new=AsyncMock(return_value={"passed": True, "exit_code": 0, "output": "passed"})) as command:
            result = await graph.ainvoke(Command(resume={"approved": True}), config)
        result = await graph.ainvoke(Command(resume={"approved": True}), config)
        assert command.await_count == 3
        assert result["commit_sha"] == "verified-sha"
        assert result["quality_result"]["passed"]
        completed = await graph.ainvoke(Command(resume={"approved": True}), config)
        assert completed["status"] == "approved_for_merge"
    asyncio.run(scenario())