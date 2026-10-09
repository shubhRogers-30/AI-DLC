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
