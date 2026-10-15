import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from copilot import CopilotClient
from copilot.generated.rpc import PermissionDecisionReject

from app.agents.copilot_service import CopilotService
from app.core.config import settings


def test_agent_instructions_timeout_and_read_only_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "private-token")
    monkeypatch.setenv("JIRA_API_TOKEN", "private-jira-token")
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    session = SimpleNamespace(send_and_wait=AsyncMock(return_value=SimpleNamespace(data=SimpleNamespace(content="proposal"))))
    client.create_session = AsyncMock(return_value=session)
    with patch("app.agents.copilot_service.CopilotClient", return_value=client) as constructor:
        result = asyncio.run(CopilotService(timeout=900).run_agent(
            "angular-architect", "story", tmp_path, guidance="Angular guidance", read_only=True,
        ))
    assert result["summary"] == "proposal"
    kwargs = client.create_session.call_args.kwargs
    assert "Angular guidance" in kwargs["system_message"]["content"]
    assert isinstance(kwargs["on_permission_request"](SimpleNamespace(kind="write"), {}), PermissionDecisionReject)
    assert "GITHUB_TOKEN" not in constructor.call_args.kwargs["env"]
    assert "JIRA_API_TOKEN" not in constructor.call_args.kwargs["env"]
    session.send_and_wait.assert_awaited_once_with("story", timeout=900)


def test_existing_agent_file_is_loaded(tmp_path):
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    session = SimpleNamespace(send_and_wait=AsyncMock(return_value=SimpleNamespace(data=SimpleNamespace(content="done"))))
    client.create_session = AsyncMock(return_value=session)
    with patch("app.agents.copilot_service.CopilotClient", return_value=client):
        asyncio.run(CopilotService().run_agent("springboot-developer", "story", tmp_path))
    assert "Spring Boot Developer" in client.create_session.call_args.kwargs["system_message"]["content"]


@pytest.mark.skipif(os.environ.get("AI_DLC_LIVE_COPILOT_CHECK") != "1", reason="Live Copilot probe requires explicit opt-in")
def test_live_copilot_response_without_repository_access(tmp_path):
    async def scenario():
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith(("GITHUB_", "GH_TOKEN", "JIRA_", "SONAR_", "API_TOKEN", "GIT_CONFIG_"))}
        async with CopilotClient(working_directory=str(tmp_path), env=env, use_logged_in_user=True) as client:
            auth = await client.get_auth_status()
            assert auth.isAuthenticated, "Copilot CLI must be authenticated"
            session = await client.create_session(
                model=settings.copilot_model,
                working_directory=str(tmp_path),
                on_permission_request=lambda request, invocation: PermissionDecisionReject(),
                system_message={"content": "This is a connectivity check. Do not use tools, read files or modify anything."},
                enable_config_discovery=False,
                enable_file_hooks=False,
            )
            response = await session.send_and_wait("Reply with exactly SDK_OK. Do not use tools.", timeout=90)
            content = getattr(getattr(response, "data", None), "content", "") or ""
            assert content.strip() == "SDK_OK", "Copilot did not return the expected connectivity response"
    try:
        asyncio.run(asyncio.wait_for(scenario(), timeout=120))
    except AssertionError:
        raise
    except Exception as error:
        pytest.fail(f"Live Copilot probe failed ({type(error).__name__}); check CLI authentication, model availability and network access", pytrace=False)