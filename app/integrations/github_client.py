import asyncio
import base64
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from app.execution import run_command


class GitHubError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


class GitHubClient:
    def __init__(self, token, api_url, mock=False, organization="RogersCommunications",
                 app_id="", installation_id="", private_key_path=""):
        self.token, self.api_url, self.mock = token, api_url.rstrip("/"), mock
        self.organization = organization
        self.app_id, self.installation_id, self.private_key_path = app_id, installation_id, private_key_path
        self._expires = 0
        self._installation_permissions = {}
        self._token_lock = asyncio.Lock()

    def validate_repository(self, repo):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or repo.split("/")[-1] in (".", ".."):
            raise GitHubError("Use owner/repository, not a URL or local path", 422)
        if repo.split("/", 1)[0].casefold() != self.organization.casefold():
            raise GitHubError(f"Repository must belong to {self.organization}", 403)

    @staticmethod
    def split_repo(repo):
        return repo.split("/", 1)

    @staticmethod
    def validate_branch_name(branch):
        if (not branch or len(branch) > 240 or branch.startswith("/") or branch.endswith("/")
                or "//" in branch or ".." in branch or "@{" in branch
                or branch.endswith(".") or branch.lower().endswith(".lock")
                or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch)):
            raise GitHubError("Enter a valid Git branch name without spaces or Git-reserved sequences", 422)
        return branch

    async def list_branches(self, repo):
        self.validate_repository(repo)
        if self.mock:
            return [{"name": "main", "protected": True}, {"name": "develop", "protected": False}]
        branches = []
        page = 1
        while True:
            batch = await self._request("GET", f"/repos/{repo}/branches",
                                        params={"per_page": 100, "page": page})
            branches.extend({"name": item["name"], "protected": item.get("protected", False)} for item in batch)
            if len(batch) < 100:
                return branches
            page += 1

    async def branch_summary(self, repo, branch, base):
        self.validate_repository(repo)
        self.validate_branch_name(branch)
        self.validate_branch_name(base)
        if branch == base:
            raise GitHubError("The working branch must differ from the base branch", 422)
        if self.mock:
            if branch in {"main", "develop"}:
                return {"exists": True, "name": branch, "base_branch": base,
                        "protected": branch == "main", "ahead_by": 0,
                        "recent_commits": [], "open_pull_requests": []}
            return {"exists": False, "name": branch, "base_branch": base,
                    "protected": False, "ahead_by": 0,
                    "recent_commits": [], "open_pull_requests": []}
        base_ref = await self._request("GET", f"/repos/{repo}/git/ref/heads/{quote(base, safe='/')}", allow_missing=True)
        if not base_ref:
            raise GitHubError("Selected base branch does not exist in this repository", 422)
        branch_ref = await self._request("GET", f"/repos/{repo}/git/ref/heads/{quote(branch, safe='/')}", allow_missing=True)
        if not branch_ref:
            return {"exists": False, "name": branch, "base_branch": base,
                    "protected": False, "ahead_by": 0,
                    "recent_commits": [], "open_pull_requests": []}
        branch_details = await self._request("GET", f"/repos/{repo}/branches/{quote(branch, safe='/')}")
        comparison = await self._request(
            "GET", f"/repos/{repo}/compare/{quote(base, safe='')}...{quote(branch, safe='')}")
        commits = comparison.get("commits", [])
        pulls = await self._request("GET", f"/repos/{repo}/pulls", params={
            "state": "open", "head": f"{repo.split('/', 1)[0]}:{branch}", "base": base, "per_page": 10,
        })
        return {
            "exists": True,
            "name": branch,
            "base_branch": base,
            "protected": branch_details.get("protected", False),
            "ahead_by": comparison.get("ahead_by", len(commits)),
            "recent_commits": [{"sha": commit["sha"],
                                "message": commit["commit"]["message"].splitlines()[0],
                                "author": (commit["commit"].get("author") or {}).get("name", "Unknown")}
                               for commit in commits[-5:]],
            "open_pull_requests": [{"number": pull["number"], "title": pull["title"], "url": pull["html_url"]}
                                    for pull in pulls],
        }

    async def access_token(self):
        if not self.app_id:
            if not self.token:
                raise GitHubError("Configure GITHUB_TOKEN or GitHub App credentials", 503)
            return self.token
        async with self._token_lock:
            if self.token and time.time() < self._expires:
                return self.token
            if not self.installation_id or not self.private_key_path:
                raise GitHubError("GitHub App requires installation ID and private key path", 503)
            import jwt
            now = int(time.time())
            assertion = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id},
                                   Path(self.private_key_path).read_text(encoding="utf-8"), algorithm="RS256")
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.api_url}/app/installations/{self.installation_id}/access_tokens",
                    headers={"Authorization": f"Bearer {assertion}", "Accept": "application/vnd.github+json"},
                )
            if response.status_code != 201:
                raise GitHubError("Cannot obtain GitHub installation token; check App installation and permissions")
            self.token = response.json()["token"]
            self._installation_permissions = response.json().get("permissions", {})
            self._expires = time.time() + 3300
            return self.token

    async def _request(self, method, path, allow_missing=False, **kwargs):
        headers = {"Authorization": f"Bearer {await self.access_token()}",
                   "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(method, f"{self.api_url}{path}", headers=headers, **kwargs)
        except httpx.RequestError as error:
            raise GitHubError("Cannot connect to GitHub", 503) from error
        if allow_missing and response.status_code == 404:
            return None
        if response.is_error:
            raise GitHubError(f"GitHub returned HTTP {response.status_code}; check access and repository configuration")
        return response.json() if response.content else {}

    async def list_repositories(self):
        if self.mock:
            return [{"full_name": f"{self.organization}/sample-springboot", "default_branch": "main"},
                    {"full_name": f"{self.organization}/DOAT-Client-UI", "default_branch": "main"}]
        repositories = []
        page = 1
        while True:
            path = "/installation/repositories" if self.app_id else f"/orgs/{self.organization}/repos"
            result = await self._request("GET", path, params={"per_page": 100, "page": page, "type": "all"})
            batch = result["repositories"] if self.app_id else result
            repositories.extend({"full_name": item["full_name"], "default_branch": item["default_branch"]}
                                for item in batch if item["owner"]["login"].casefold() == self.organization.casefold()
                                and not item.get("archived") and not item.get("disabled"))
            if len(batch) < 100:
                return repositories
            page += 1

    async def repository(self, repo):
        self.validate_repository(repo)
        if self.mock:
            return {"full_name": repo, "default_branch": "main", "permissions": {"push": True}}
        metadata = await self._request("GET", f"/repos/{repo}")
        self.validate_repository(metadata["full_name"])
        if metadata.get("archived") or metadata.get("disabled"):
            raise GitHubError("Archived or disabled repositories cannot be developed", 403)
        can_push = metadata.get("permissions", {}).get("push")
        if self.app_id:
            accessible = await self.list_repositories()
            installed = any(item["full_name"].casefold() == metadata["full_name"].casefold() for item in accessible)
            can_push = installed and self._installation_permissions.get("contents") == "write"
        if not can_push:
            raise GitHubError("GitHub credentials require write access to this repository", 403)
        return metadata

    async def repository_config(self, repo, ref):
        if self.mock:
            return None
        content = await self._request("GET", f"/repos/{repo}/contents/.github/ai-dlc.json",
                                      allow_missing=True, params={"ref": ref})
        if content is None:
            return None
        import json
        try:
            return json.loads(base64.b64decode(content["content"]).decode("utf-8"))
        except (KeyError, ValueError, UnicodeError) as error:
            raise GitHubError("Invalid .github/ai-dlc.json on the default branch", 422) from error

    async def create_branch(self, repo, branch, base):
        self.validate_branch_name(branch)
        self.validate_branch_name(base)
        if self.mock:
            return {"ref": f"refs/heads/{branch}"}
        reference = await self._request("GET", f"/repos/{repo}/git/ref/heads/{base}")
        return await self._request("POST", f"/repos/{repo}/git/refs",
                                   json={"ref": f"refs/heads/{branch}", "sha": reference["object"]["sha"]})

    async def create_pr(self, repo, title, head, base, body):
        if self.mock:
            return {"number": 1, "html_url": f"https://github.com/{repo}/pull/1"}
        return await self._request("POST", f"/repos/{repo}/pulls",
                                   json={"title": title, "head": head, "base": base, "body": body})

    async def trigger_workflow(self, repo, workflow_file, ref):
        if self.mock:
            return {"triggered": True}
        await self._request("POST", f"/repos/{repo}/actions/workflows/{workflow_file}/dispatches", json={"ref": ref})
        return {"triggered": True}

    async def _runs(self, repo, workflow_file, branch):
        result = await self._request("GET", f"/repos/{repo}/actions/workflows/{workflow_file}/runs",
                                     params={"branch": branch, "event": "workflow_dispatch", "per_page": 100})
        return result.get("workflow_runs", [])

    async def branch_sha(self, repo, branch):
        if self.mock:
            return "mock-sha"
        reference = await self._request("GET", f"/repos/{repo}/git/ref/heads/{branch}")
        return reference["object"]["sha"]

    async def codeql_gate(self, repo, branch, sha):
        if self.mock:
            return {"passed": True, "alerts": [], "head_sha": sha}
        analyses = await self._request("GET", f"/repos/{repo}/code-scanning/analyses",
                                       params={"ref": f"refs/heads/{branch}", "tool_name": "CodeQL", "per_page": 100})
        if not any(item.get("commit_sha") == sha for item in analyses):
            return {"passed": False, "status": "NO_CODEQL_ANALYSIS_FOR_COMMIT", "head_sha": sha}
        alerts = []
        page = 1
        while True:
            batch = await self._request("GET", f"/repos/{repo}/code-scanning/alerts",
                                        params={"ref": f"refs/heads/{branch}", "state": "open", "tool_name": "CodeQL", "per_page": 100, "page": page})
            alerts.extend({"number": alert["number"], "rule": alert["rule"]["id"], "url": alert["html_url"],
                           "location": alert.get("most_recent_instance", {}).get("location"),
                           "message": alert.get("most_recent_instance", {}).get("message")}
                          for alert in batch)
            if len(batch) < 100:
                break
            page += 1
        return {"passed": not alerts, "alerts": alerts, "head_sha": sha}

    async def workflow_runs(self, repo, workflow_file, branch):
        if self.mock:
            return {"status": "completed", "conclusion": "success"}
        runs = await self._runs(repo, workflow_file, branch)
        return runs[0] if runs else {"status": "unknown", "conclusion": None}

    async def dispatch_and_wait(self, repo, workflow_file, branch, sha, timeout=1800, interval=10):
        if self.mock:
            return {"status": "completed", "conclusion": "success", "head_sha": sha}
        previous = {run["id"] for run in await self._runs(repo, workflow_file, branch)}
        await self.trigger_workflow(repo, workflow_file, branch)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            runs = await self._runs(repo, workflow_file, branch)
            matching = [run for run in runs if run["id"] not in previous and run.get("head_sha") == sha]
            if matching and matching[0]["status"] == "completed":
                run = matching[0]
                return {"id": run["id"], "status": run["status"], "conclusion": run["conclusion"],
                        "head_sha": sha, "url": run["html_url"]}
            await asyncio.sleep(interval)
        return {"status": "timed_out", "conclusion": "failure", "head_sha": sha}

    async def _git(self, command, workspace, authenticated=False):
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "never"
        if authenticated:
            encoded = base64.b64encode(f"x-access-token:{await self.access_token()}".encode()).decode()
            env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {encoded}"})
        result = await run_command(["git", *command], workspace, env=env)
        if not result["passed"]:
            raise GitHubError("Git operation failed; check credentials, repository state and Git installation")
        return result["output"].strip()

    async def prepare_workspace(self, repo, workspace_root, run_id, branch, base, reuse_existing=False):
        self.validate_repository(repo)
        self.validate_branch_name(branch)
        self.validate_branch_name(base)
        summary = await self.branch_summary(repo, branch, base)
        if summary["exists"] and not reuse_existing:
            raise GitHubError("Branch already exists; confirm reuse or choose another branch name", 409)
        if not summary["exists"] and reuse_existing:
            raise GitHubError("The selected branch no longer exists; check the name and try again", 409)
        if not summary["exists"]:
            await self.create_branch(repo, branch, base)
        target = Path(workspace_root).resolve() / run_id / repo.split("/", 1)[1]
        target.parent.mkdir(parents=True, exist_ok=True)
        await self._git(["clone", "--branch", branch, "--single-branch", f"https://github.com/{repo}.git", str(target)],
                        target.parent, authenticated=True)
        await self._git(["config", "user.name", "AI-DLC"], target)
        await self._git(["config", "user.email", "ai-dlc@users.noreply.github.com"], target)
        return str(target), summary

    async def local_sha(self, workspace):
        return await self._git(["rev-parse", "HEAD"], workspace)

    async def publish(self, workspace, branch, message, allow_unchanged=False):
        current = await self._git(["branch", "--show-current"], workspace)
        if current != branch:
            raise GitHubError("Agent changed the working branch; refusing to publish")
        await self._git(["add", "--all"], workspace)
        staged = await self._git(["diff", "--cached", "--name-only"], workspace)
        blocked = [name for name in staged.splitlines()
                   if Path(name).name == ".env" or Path(name).name.startswith(".env.") and Path(name).name != ".env.example"
                   or name.endswith((".pem", ".key"))]
        if blocked:
            raise GitHubError("Refusing to commit environment or private-key files", 409)
        if staged:
            await self._git(["commit", "-m", message], workspace)
        ahead = await self._git(["rev-list", "--count", "HEAD", "--not", "--remotes=origin"], workspace)
        if not staged and ahead == "0" and not allow_unchanged:
            raise GitHubError("No implementation changes to publish", 409)
        sha = await self._git(["rev-parse", "HEAD"], workspace)
        await self._git(["push", "origin", f"HEAD:refs/heads/{branch}"], workspace, authenticated=True)
        return sha

    async def clone_if_needed(self, repo, workspace_root):
        self.validate_repository(repo)
        target = Path(workspace_root) / repo.split("/", 1)[1]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target / ".git").exists():
            await self._git(["clone", f"https://github.com/{repo}.git", str(target.resolve())], target.parent, authenticated=True)
        return str(target)
