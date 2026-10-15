import httpx

class SonarClient:
    def __init__(self, url, token, mock=False):
        self.url, self.token, self.mock = url.rstrip("/"), token, mock

    async def quality_gate(self, project_key):
        if self.mock:
            return {"status": "OK", "passed": True}
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"{self.url}/api/qualitygates/project_status",
                params={"projectKey": project_key},
                auth=(self.token, "")
            )
            r.raise_for_status()
            status = r.json()["projectStatus"]["status"]
            return {"status": status, "passed": status == "OK"}

    async def quality_gate_for_commit(self, project_key, branch, sha):
        if self.mock:
            return {"status": "OK", "passed": True, "revision": sha}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.url}/api/project_analyses/search", params={"project": project_key, "branch": branch, "ps": 100},
                auth=(self.token, ""),
            )
            response.raise_for_status()
            analysis = next((item for item in response.json().get("analyses", []) if item.get("revision") == sha), None)
            if analysis is None:
                return {"passed": False, "status": "NO_ANALYSIS_FOR_COMMIT", "revision": sha}
            gate = await client.get(f"{self.url}/api/qualitygates/project_status",
                                    params={"analysisId": analysis["key"]}, auth=(self.token, ""))
            gate.raise_for_status()
            project_status = gate.json()["projectStatus"]
            status = project_status["status"]
            result = {"status": status, "passed": status == "OK", "revision": sha, "analysis_id": analysis["key"],
                      "conditions": project_status.get("conditions", [])}
            if status != "OK":
                issues = await client.get(f"{self.url}/api/issues/search",
                                          params={"componentKeys": project_key, "branch": branch, "resolved": "false", "ps": 100},
                                          auth=(self.token, ""))
                issues.raise_for_status()
                result["issues"] = [{key: issue.get(key) for key in ("key", "rule", "component", "line", "message", "severity")}
                                    for issue in issues.json().get("issues", [])]
            return result
