import asyncio
import base64
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.jira import JiraClient, JiraError


@pytest.mark.parametrize("api_version,auth_type", [("2", "bearer"), ("3", "basic")])
def test_get_story(api_version, auth_type):
    def handler(request):
        assert request.url.path == f"/rest/api/{api_version}/issue/TEST-123"
        expected = "Bearer test-token" if auth_type == "bearer" else (
            "Basic " + base64.b64encode(b"user@example.com:test-token").decode()
        )
        assert request.headers["Authorization"] == expected
        return httpx.Response(200, json={
            "key": "TEST-123",
            "fields": {"summary": "A ticket", "description": "Ticket details"},
        })

    client = JiraClient("https://jira.example.com/", "user@example.com", "test-token",
                        auth_type=auth_type, api_version=api_version)
    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with patch("app.clients.jira.httpx.AsyncClient", return_value=transport_client):
        story = asyncio.run(client.get_story(" test-123 "))
    assert story["summary"] == "A ticket"
    assert story["description"] == "Ticket details"


@pytest.mark.parametrize("api_version", ["2", "3"])
def test_add_comment(api_version):
    def handler(request):
        assert request.url.path == f"/rest/api/{api_version}/issue/TEST-123/comment"
        payload = json.loads(request.content)
        if api_version == "2":
            assert payload == {"body": "Done"}
        else:
            assert payload["body"]["content"][0]["content"][0]["text"] == "Done"
        return httpx.Response(201, json={"id": "100"})

    client = JiraClient("https://jira.example.com", "", "test-token",
                        auth_type="bearer", api_version=api_version)
    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with patch("app.clients.jira.httpx.AsyncClient", return_value=transport_client):
        assert asyncio.run(client.add_comment("TEST-123", "Done")) == {"id": "100"}


@pytest.mark.parametrize("upstream_status,expected_status,message", [
    (401, 502, "authentication failed"),
    (403, 502, "denied access"),
    (404, 404, "not found"),
    (500, 502, "HTTP 500"),
])
def test_jira_http_errors(upstream_status, expected_status, message):
    transport = httpx.MockTransport(lambda request: httpx.Response(upstream_status, text="private upstream body"))
    client = JiraClient("https://jira.example.com", "", "secret-token", auth_type="bearer", api_version="2")
    with patch("app.clients.jira.httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        request = client.get_story("TEST-123")
        with pytest.raises(JiraError, match=message) as error:
            asyncio.run(request)
    assert error.value.status_code == expected_status
    assert "secret-token" not in str(error.value)
    assert "private upstream body" not in str(error.value)


def test_jira_network_error():
    def handler(request):
        raise httpx.ConnectError("private network details", request=request)

    client = JiraClient("https://jira.example.com", "", "test-token", auth_type="bearer", api_version="2")
    transport = httpx.MockTransport(handler)
    with patch("app.clients.jira.httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        request = client.get_story("TEST-123")
        with pytest.raises(JiraError, match="Cannot connect") as error:
            asyncio.run(request)
    assert error.value.status_code == 503


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>SSO login</html>"),
    httpx.Response(200, json={"unexpected": "response"}),
])
def test_jira_unexpected_response(response):
    client = JiraClient("https://jira.example.com", "", "test-token", auth_type="bearer", api_version="2")
    transport = httpx.MockTransport(lambda request: response)
    with patch("app.clients.jira.httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        request = client.get_story("TEST-123")
        with pytest.raises(JiraError):
            asyncio.run(request)


def test_ticket_lookup_endpoint():
    from app.main import app

    story = {"key": "TEST-123", "summary": "A ticket", "description": "Details", "acceptance_criteria": []}
    with patch("app.main.jira.get_story", new=AsyncMock(return_value=story)) as get_story:
        response = TestClient(app).get("/api/jira/issues/TEST-123")
    assert response.status_code == 200
    assert response.json() == story
    get_story.assert_awaited_once_with("TEST-123")


def test_ticket_lookup_endpoint_error():
    from app.main import app

    with patch("app.main.jira.get_story", new=AsyncMock(side_effect=JiraError("Ticket not found", 404))):
        response = TestClient(app).get("/api/jira/issues/TEST-123")
    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket not found"}


def test_mcp_uses_shared_jira_client():
    from app.config import settings
    from mcp_servers.engineering import jira_get_story

    story = {"key": "TEST-123", "summary": "A ticket", "description": "Details"}
    with patch("mcp_servers.engineering.JiraClient") as client_type:
        client_type.return_value.get_story = AsyncMock(return_value=story)
        assert asyncio.run(jira_get_story("TEST-123")) == story
    client_type.assert_called_once_with(
        settings.jira_base_url, settings.jira_email, settings.jira_api_token, settings.mock_mode,
        auth_type=settings.jira_auth_type, api_version=settings.jira_api_version
    )
    client_type.return_value.get_story.assert_awaited_once_with("TEST-123")