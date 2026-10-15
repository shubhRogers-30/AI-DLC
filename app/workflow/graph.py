import os
import inspect
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.checkpoint.memory import InMemorySaver
from app.workflow.state import AIDLCState
from app.execution import run_command
from app.stacks import stacks


def build_graph(services):
    jira, github, sonar, copilot, settings = services

    async def load_story(state):
        story = state.get("requirements") or await jira.get_story(state["jira_key"])
        return {"story": story["summary"], "requirements": story, "status": "requirements_loaded"}

    async def architecture(state):
        profile = stacks.get(state["stack"])
        result = await copilot.run_agent(
            f"{profile.name}-architect",
            f"Inspect the repository without modifying it. Propose a concise architecture and test plan for this exact Jira story:\n{state['requirements']}\nDo not invent requirements or use a fixed example endpoint.",
            state["workspace"], guidance=profile.guidance, read_only=True,
        )
        return {
            "architecture": {
                "stack": profile.name,
                "proposal": result["summary"],
                "guidance": profile.guidance,
            },
            "status": "architecture_ready"
        }

    def human_approval(state):
        decision = interrupt({
            "type": "architecture_approval",
            "message": "Approve architecture before coding.",
            "architecture": state["architecture"]
        })
        if not decision.get("approved"):
            return {"status": "rejected", "approval": decision}
        return {"status": "approved", "approval": decision}

    def code_approval(state):
        decision = interrupt({
            "type": "code_approval",
            "message": "Tests passed. Review the live diff before allowing this run to push and open a pull request.",
            "branch": state["branch"],
            "test_result": state["test_result"],
            "diff_url": f"/api/workflows/{state['run_id']}/diff",
        })
        if not decision.get("approved"):
            return {"status": "rejected", "approval": decision}
        return {"status": "code_approved", "approval": decision}

    def plan(state):
        profile = stacks.get(state["stack"])
        return {
            "tasks": [
                {"id": "T1", "agent": f"{profile.name}-developer", "description": "Implement the approved story and architecture"},
                {"id": "T2", "agent": f"{profile.name}-test-generator", "description": "Add tests covering the story acceptance criteria"}
            ],
            "status": "planned"
        }

    async def develop(state):
        profile = stacks.get(state["stack"])
        prompt = f"""
    Implement Jira story {state['jira_key']} in the {profile.display_name} target.

Story:
{state['requirements']}

Architecture:
{state['architecture']}

Tasks:
{state['tasks']}

Rules:
- Inspect the existing repository before editing.
- Reuse existing patterns and dependencies.
- Do not change unrelated code.
- Follow the selected stack guidance and approved architecture.
- Add/update tests.
- Do not commit, push, change branches, merge or deploy.
- Report changed files and test results.
"""
        result = await copilot.run_agent(f"{profile.name}-developer", prompt, state["workspace"], guidance=profile.guidance)
        return {"agent_outputs": state.get("agent_outputs", []) + [result], "status": "developed"}

    async def tests(state):
        profile = stacks.get(state["stack"])
        result = await copilot.run_agent(
            f"{profile.name}-test-generator",
            f"Add or update tests for this story: {state['requirements']}. Fix only story-related issues. Do not commit, push or merge.",
            state["workspace"], guidance=profile.guidance,
        )
        checks = []
        if settings.mock_mode:
            checks = [{"passed": True, "output": "Mock checks; no commands executed"}]
        else:
            env = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(("GITHUB_", "GH_TOKEN", "JIRA_", "SONAR_", "API_TOKEN", "GIT_CONFIG_"))}
            for command in profile.checks(state["workspace"]):
                check = await run_command(command, state["workspace"], settings.command_timeout_seconds, env)
                checks.append(check)
                if not check["passed"]:
                    break
        passed = all(check["passed"] for check in checks)
        return {"test_result": {"status": "PASSED" if passed else "FAILED", "checks": checks, "agent": result},
                "status": "tested" if passed else "tests_failed"}

    def tests_route(state):
        if state["test_result"]["status"] == "PASSED":
            return "code_approval"
        return "failed" if state.get("remediation_attempts", 0) >= settings.max_remediation_attempts else "remediate"

    def code_approval_route(state):
        return "create_pr" if state.get("status") == "code_approved" else "end"

    async def create_pr(state):
        branch = state["branch"]
        sha = "mock-sha" if settings.mock_mode else await github.publish(
            state["repository_workspace"], branch, f"[AI-DLC] {state['jira_key']}: {state['story']}",
            allow_unchanged=bool(state.get("pr_number")),
        )
        if state.get("pr_number"):
            return {"commit_sha": sha, "status": "pr_updated"}
        pr = await github.create_pr(
            state["repository"],
            f"[AI-DLC] {state['jira_key']}: {state['story']}",
            branch,
            state["repo_config"]["default_branch"],
            "Generated by AI-DLC. Human review required."
        )
        return {"commit_sha": sha, "pr_number": pr["number"], "pr_url": pr["html_url"], "status": "pr_created"}

    async def quality(state):
        config = state["repo_config"]["quality"]
        codeql = await github.dispatch_and_wait(
            state["repository"], config["codeql_workflow"], state["branch"], state["commit_sha"],
            settings.ci_timeout_seconds, settings.ci_poll_interval_seconds,
        )
        if codeql.get("conclusion") == "success":
            codeql = {**codeql, **await github.codeql_gate(state["repository"], state["branch"], state["commit_sha"])}
        analysis = await github.dispatch_and_wait(
            state["repository"], config["sonar_workflow"], state["branch"], state["commit_sha"],
            settings.ci_timeout_seconds, settings.ci_poll_interval_seconds,
        )
        sonar_result = await sonar.quality_gate_for_commit(
            config["sonar_project_key"], state["branch"], state["commit_sha"],
        )
        sonar_result = {**sonar_result, "workflow": analysis}
        codeql_ok = codeql.get("conclusion") == "success" and codeql.get("passed", False)
        passed = analysis.get("conclusion") == "success" and sonar_result.get("passed", False) and codeql_ok
        return {
            "sonar_result": sonar_result,
            "codeql_result": codeql,
            "quality_result": {"passed": passed, "sonar": sonar_result, "codeql": codeql},
            "status": "quality_passed" if passed else "quality_failed"
        }

    def quality_route(state):
        if state["quality_result"].get("passed"):
            return "final_approval"
        if state.get("remediation_attempts", 0) >= settings.max_remediation_attempts:
            return "failed"
        return "remediate"

    async def remediate(state):
        profile = stacks.get(state["stack"])
        attempt = state.get("remediation_attempts", 0) + 1
        prompt = f"""
The AI-DLC quality gate failed.

SonarQube:
{state.get('sonar_result')}

CodeQL:
{state.get('codeql_result')}

Tests:
{state.get('test_result')}

Remediation attempt: {attempt}

Inspect the repository and current changes. Fix genuine findings caused by this story.
Run tests after fixing. Do not commit, push, change branches, merge or deploy.
"""
        result = await copilot.run_agent(f"{profile.name}-remediation", prompt, state["workspace"], guidance=profile.guidance)
        return {
            "remediation_attempts": attempt,
            "agent_outputs": state.get("agent_outputs", []) + [result],
            "status": "remediated"
        }

    async def final_approval(state):
        decision = interrupt({
            "type": "merge_approval",
            "message": "Quality gates passed. Approve merge manually.",
            "pr_url": state.get("pr_url"),
            "quality_result": state.get("quality_result")
        })
        if not decision.get("approved"):
            return {"status": "rejected", "approval": decision}
        if await github.branch_sha(state["repository"], state["branch"]) != state["commit_sha"]:
            raise ValueError("PR branch changed after quality verification; start a new reviewed workflow")
        return {"status": "approved_for_merge", "approval": decision}

    def failed(state):
        return {"status": "failed", "errors": state.get("errors", []) + ["Tests or quality gates failed after the remediation limit"]}

    async def tracked(name, fn, state):
        writer = get_stream_writer()
        writer({"stage": name, "event": "started"})
        result = fn(state)
        if inspect.isawaitable(result):
            result = await result
        writer({"stage": name, "event": "completed", "status": result.get("status")})
        return result

    def make_tracked(name, fn):
        async def node(state):
            return await tracked(name, fn, state)
        return node

    builder = StateGraph(AIDLCState)
    for name, fn in [
        ("load_story", load_story), ("architecture", architecture),
        ("human_approval", human_approval), ("code_approval", code_approval), ("plan", plan),
        ("develop", develop), ("tests", tests), ("create_pr", create_pr),
        ("quality", quality), ("remediate", remediate), ("final_approval", final_approval), ("failed", failed)
    ]:
        builder.add_node(name, make_tracked(name, fn))

    builder.add_edge(START, "load_story")
    builder.add_edge("load_story", "architecture")
    builder.add_edge("architecture", "human_approval")
    builder.add_conditional_edges("human_approval", lambda state: "plan" if state["status"] == "approved" else "end",
                                  {"plan": "plan", "end": END})
    builder.add_edge("plan", "develop")
    builder.add_edge("develop", "tests")
    builder.add_conditional_edges("tests", tests_route, {"code_approval": "code_approval", "remediate": "remediate", "failed": "failed"})
    builder.add_conditional_edges("code_approval", code_approval_route, {"create_pr": "create_pr", "end": END})
    builder.add_edge("create_pr", "quality")
    builder.add_conditional_edges("quality", quality_route, {
        "final_approval": "final_approval",
        "remediate": "remediate",
        "failed": "failed"
    })
    builder.add_edge("remediate", "tests")
    builder.add_edge("final_approval", END)
    builder.add_edge("failed", END)

    return builder.compile(checkpointer=InMemorySaver())
