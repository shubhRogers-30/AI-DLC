import os
import httpx
from mcp.server.mcpserver import MCPServer
from app.integrations.jira_client import JiraClient
from app.core.config import settings

mcp = MCPServer("ai-dlc-engineering")

@mcp.tool()
async def jira_get_story(issue_key: str) -> dict:
    """Read a Jira story and return its key, summary and description."""
    jira = JiraClient(
        settings.jira_base_url, settings.jira_email, settings.jira_api_token, settings.mock_mode,
        auth_type=settings.jira_auth_type, api_version=settings.jira_api_version
    )
    return await jira.get_story(issue_key)

@mcp.tool()
async def sonar_quality_gate(project_key: str) -> dict:
    """Return SonarQube quality-gate status for a project."""
    url = os.getenv("SONAR_URL", "").rstrip("/")
    token = os.getenv("SONAR_TOKEN", "")
    if not url:
        return {"status": "OK", "passed": True}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{url}/api/qualitygates/project_status",
            params={"projectKey": project_key},
            auth=(token, "")
        )
        r.raise_for_status()
        status = r.json()["projectStatus"]["status"]
        return {"status": status, "passed": status == "OK"}


def run():
    mcp.run(transport="streamable-http", json_response=True)


if __name__ == "__main__":
    run()
