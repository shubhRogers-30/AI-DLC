import base64
from urllib.parse import quote
import httpx

class JiraError(RuntimeError):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code

class JiraClient:
    def __init__(self, base_url, email, token, mock=False, auth_type="basic", api_version="3"):
        self.base_url, self.email, self.token, self.mock = base_url.rstrip("/"), email, token, mock
        if auth_type not in {"basic", "bearer"}:
            raise ValueError("Jira auth_type must be basic or bearer")
        if api_version not in {"2", "3"}:
            raise ValueError("Jira api_version must be 2 or 3")
        self.auth_type, self.api_version = auth_type, api_version

    def _headers(self):
        if self.auth_type == "bearer":
            return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        auth = base64.b64encode(f"{self.email}:{self.token}".encode()).decode()
        return {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    async def _request(self, method, path, **kwargs):
        if not self.base_url or not self.token:
            raise JiraError("Jira connection is not configured. Set JIRA_BASE_URL and JIRA_API_TOKEN.", 503)
        if self.auth_type == "basic" and not self.email:
            raise JiraError("Jira Basic authentication requires JIRA_EMAIL.", 503)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(
                    method, f"{self.base_url}/rest/api/{self.api_version}/{path}",
                    headers=self._headers(), **kwargs
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise JiraError("Jira authentication failed. Check the token and JIRA_AUTH_TYPE.") from exc
            if status == 403:
                raise JiraError("Jira denied access. Check authentication mode and ticket permissions.") from exc
            if status == 404:
                raise JiraError("Jira ticket or API endpoint not found. Check the ticket key and JIRA_API_VERSION.", 404) from exc
            raise JiraError(f"Jira request failed (HTTP {status}).") from exc
        except httpx.HTTPError as exc:
            raise JiraError("Cannot connect to Jira. Check JIRA_BASE_URL, network access and VPN.", 503) from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise JiraError("Jira returned a non-JSON response. Check the base URL and authentication; an SSO page is not a Jira API response.") from exc
        if not isinstance(data, dict):
            raise JiraError("Jira returned an unexpected response.")
        return data

    async def get_story(self, key):
        key = key.strip().upper()
        if not key:
            raise JiraError("Enter a Jira ticket key, such as PROJECT-123.", 422)
        if self.mock:
            return {
                "key": key,
                "summary": "Add customer eligibility REST endpoint",
                "description": "Expose GET /api/v1/customers/{id}/eligibility.",
                "acceptance_criteria": [
                    "Return 200 for an eligible customer",
                    "Return 404 when customer does not exist",
                    "Return 400 for invalid customer id"
                ]
            }
        data = await self._request("GET", f"issue/{quote(key, safe='')}")
        fields = data.get("fields")
        if not isinstance(fields, dict):
            raise JiraError("Jira returned an unexpected ticket response.")
        return {
            "key": data.get("key", key),
            "summary": fields.get("summary", ""),
            "description": fields.get("description") or "",
            "acceptance_criteria": []
        }

    async def add_comment(self, key, body):
        if self.mock:
            return {"ok": True}
        payload = {"body": body} if self.api_version == "2" else {
            "body": {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": body}]}
            ]}
        }
        return await self._request("POST", f"issue/{quote(key.strip().upper(), safe='')}/comment", json=payload)
