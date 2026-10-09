from pathlib import Path
from copilot import CopilotClient
from copilot.session import PermissionHandler

class CopilotService:
    def __init__(self, model="auto", mock=False):
        self.model, self.mock = model, mock

    async def run_agent(self, agent_name, prompt, workspace):
        if self.mock:
            return {
                "agent": agent_name,
                "summary": f"MOCK execution of {agent_name}",
                "changes": [
                    "src/main/java/example/CustomerEligibilityController.java",
                    "src/test/java/example/CustomerEligibilityControllerTest.java"
                ]
            }

        async with CopilotClient() as client:
            session = await client.create_session(
                model=self.model,
                working_directory=str(Path(workspace).resolve()),
                on_permission_request=PermissionHandler.approve_all,
                session_id=f"ai-dlc-{agent_name}-{Path(workspace).name}"
            )
            response = await session.send_and_wait(prompt)
            content = getattr(getattr(response, "data", None), "content", None)
            return {"agent": agent_name, "summary": content or "Agent completed", "changes": []}
