import asyncio
from unittest.mock import patch

import httpx

from app.integrations.sonarqube_client import SonarClient


def test_sonar_uses_exact_commit_analysis():
    def handler(request):
        if request.url.path.endswith("project_analyses/search"):
            assert request.url.params["branch"] == "ai-dlc/story"
            return httpx.Response(200, json={"analyses": [{"key": "old", "revision": "old"}, {"key": "fresh", "revision": "sha"}]})
        assert request.url.params["analysisId"] == "fresh"
        return httpx.Response(200, json={"projectStatus": {"status": "OK"}})
    client = SonarClient("https://sonar.example", "token")
    with patch("app.integrations.sonarqube_client.httpx.AsyncClient", return_value=httpx.AsyncClient(transport=httpx.MockTransport(handler))):
        result = asyncio.run(client.quality_gate_for_commit("project", "ai-dlc/story", "sha"))
    assert result["passed"] and result["analysis_id"] == "fresh"


def test_old_sonar_result_cannot_pass_new_commit():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"analyses": [{"key": "old", "revision": "old"}]}))
    client = SonarClient("https://sonar.example", "token")
    with patch("app.integrations.sonarqube_client.httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        result = asyncio.run(client.quality_gate_for_commit("project", "branch", "new"))
    assert not result["passed"]