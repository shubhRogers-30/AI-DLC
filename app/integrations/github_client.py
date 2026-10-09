from pathlib import Path
import httpx

class GitHubClient:
    def __init__(self, token, api_url, mock=False):
        self.token, self.api_url, self.mock = token, api_url.rstrip("/"), mock

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

    @staticmethod
    def split_repo(repo):
        return repo.split("/", 1)

    async def create_branch(self, repo, branch, base):
        if self.mock:
            return {"ref": f"refs/heads/{branch}"}
        owner, name = self.split_repo(repo)
        async with httpx.AsyncClient(timeout=30) as c:
            ref = await c.get(f"{self.api_url}/repos/{owner}/{name}/git/ref/heads/{base}", headers=self._headers())
            ref.raise_for_status()
            sha = ref.json()["object"]["sha"]
            r = await c.post(
                f"{self.api_url}/repos/{owner}/{name}/git/refs",
                headers=self._headers(),
                json={"ref": f"refs/heads/{branch}", "sha": sha}
            )
            r.raise_for_status()
            return r.json()

    async def create_pr(self, repo, title, head, base, body):
        if self.mock:
            return {"number": 1, "html_url": f"https://github.com/{repo}/pull/1"}
        owner, name = self.split_repo(repo)
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{self.api_url}/repos/{owner}/{name}/pulls",
                headers=self._headers(),
                json={"title": title, "head": head, "base": base, "body": body}
            )
            r.raise_for_status()
            return r.json()

    async def trigger_workflow(self, repo, workflow_file, ref):
        if self.mock:
            return {"triggered": True}
        owner, name = self.split_repo(repo)
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{self.api_url}/repos/{owner}/{name}/actions/workflows/{workflow_file}/dispatches",
                headers=self._headers(),
                json={"ref": ref}
            )
            r.raise_for_status()
            return {"triggered": True}

    async def workflow_runs(self, repo, workflow_file, branch):
        if self.mock:
            return {"status": "completed", "conclusion": "success"}
        owner, name = self.split_repo(repo)
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"{self.api_url}/repos/{owner}/{name}/actions/workflows/{workflow_file}/runs",
                headers=self._headers(),
                params={"branch": branch, "per_page": 1}
            )
            r.raise_for_status()
            runs = r.json().get("workflow_runs", [])
            if not runs:
                return {"status": "unknown", "conclusion": "unknown"}
            run = runs[0]
            return {"status": run["status"], "conclusion": run["conclusion"], "url": run["html_url"]}

    async def clone_if_needed(self, repo, workspace_root):
        import asyncio
        import subprocess
        target = Path(workspace_root) / repo.split("/", 1)[1]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target / ".git").exists():
            await asyncio.to_thread(
                subprocess.run,
                ["git", "clone", f"https://github.com/{repo}.git", str(target)],
                check=True,
            )
        return str(target)
