from pathlib import Path
import os
import uuid
from copilot import CopilotClient
from copilot.session import PermissionHandler
from copilot.generated.rpc import PermissionDecisionReject
from app.registry import AgentRegistry

class CopilotService:
    def __init__(self, model="auto", mock=False, timeout=1800):
        self.model, self.mock = model, mock
        self.timeout = timeout

    async def run_agent(self, agent_name, prompt, workspace, guidance="", read_only=False):
        if self.mock:
            return {
                "agent": agent_name,
                "summary": f"MOCK execution of {agent_name}",
                "changes": []
            }

        registry = AgentRegistry(Path(__file__).resolve().parents[2] / ".github" / "agents")
        agent = registry.get(agent_name)
        instructions = ""
        if agent:
            text = Path(agent["file"]).read_text(encoding="utf-8")
            instructions = text.split("---", 2)[-1] if text.startswith("---") else text
        system_message = f"You are the {agent_name}.\n{guidance}\n{instructions}\n"
        system_message += "Never commit, push, merge, deploy or change branches. The orchestrator owns Git publication. Never read credentials outside the target workspace."

        def permissions(request, invocation):
            if read_only and getattr(request, "kind", None) != "read":
                return PermissionDecisionReject(feedback="Architecture sessions may only read repository files")
            return PermissionHandler.approve_all(request, invocation)

        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith(("GITHUB_", "GH_TOKEN", "JIRA_", "SONAR_", "API_TOKEN", "GIT_CONFIG_"))}
        async with CopilotClient(working_directory=str(Path(workspace).resolve()), env=env, use_logged_in_user=True) as client:
            session = await client.create_session(
                model=self.model,
                working_directory=str(Path(workspace).resolve()),
                on_permission_request=permissions,
                system_message={"content": system_message},
                session_id=f"ai-dlc-{agent_name}-{uuid.uuid4()}",
                enable_config_discovery=False,
                enable_file_hooks=False,
            )
            response = await session.send_and_wait(prompt, timeout=self.timeout)
            content = getattr(getattr(response, "data", None), "content", None)
            if not content:
                raise RuntimeError("Copilot returned no response; inspect CLI authentication and model access")
            return {"agent": agent_name, "summary": content, "changes": []}
