from typing import Any, TypedDict

class AIDLCState(TypedDict, total=False):
    run_id: str
    status: str
    jira_key: str
    repository: str
    story: str
    requirements: dict[str, Any]
    architecture: dict[str, Any]
    tasks: list[dict[str, Any]]
    branch: str
    workspace: str
    repository_workspace: str
    stack: str
    target: str
    repo_config: dict[str, Any]
    commit_sha: str
    pr_number: int
    pr_url: str
    test_result: dict[str, Any]
    sonar_result: dict[str, Any]
    codeql_result: dict[str, Any]
    quality_result: dict[str, Any]
    approval: dict[str, Any]
    remediation_attempts: int
    agent_outputs: list[dict[str, Any]]
    errors: list[str]
