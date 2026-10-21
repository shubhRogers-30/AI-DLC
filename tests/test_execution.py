import asyncio
import json
import os
import shutil
import sys

import pytest
from app.execution import run_command
from app.integrations.github_client import GitHubClient
from app.stacks import stacks


def test_real_process_exit_codes_and_timeout(tmp_path):
    async def scenario():
        passed = await run_command([sys.executable, "-c", "print('verified')"], tmp_path)
        assert passed["passed"] and "verified" in passed["output"]
        failed = await run_command([sys.executable, "-c", "raise SystemExit(3)"], tmp_path)
        assert not failed["passed"] and failed["exit_code"] == 3
        timed_out = await run_command([sys.executable, "-c", "while True: pass"], tmp_path, timeout=0.2)
        assert not timed_out["passed"] and timed_out["output"] == "Command timed out"
    asyncio.run(scenario())


@pytest.mark.skipif(os.name != "nt", reason="Windows selector loop regression")
def test_command_runs_with_windows_selector_loop(tmp_path):
    async def scenario():
        result = await run_command([sys.executable, "-c", "print('selector loop works')"], tmp_path)
        assert result["passed"]
        assert "selector loop works" in result["output"]

    loop = asyncio.SelectorEventLoop()
    try:
        loop.run_until_complete(scenario())
    finally:
        loop.close()


def test_local_git_publication(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    async def scenario():
        remote = tmp_path / "remote.git"
        checkout = tmp_path / "checkout"
        remote.mkdir()
        checkout.mkdir()
        client = GitHubClient("not-a-real-token", "https://api.github.com")
        original_git = client._git

        async def bounded_git(command, *args, **kwargs):
            try:
                result = await asyncio.wait_for(original_git(command, *args, **kwargs), timeout=15)
                return result
            except asyncio.TimeoutError as error:
                raise AssertionError(f"Local Git step timed out: {command[0]}") from error

        client._git = bounded_git
        await client._git(["init", "--bare"], remote)
        await client._git(["init", "-b", "main"], checkout)
        await client._git(["config", "user.name", "Test"], checkout)
        await client._git(["config", "user.email", "test@example.invalid"], checkout)
        (checkout / "initial.txt").write_text("initial", encoding="utf-8")
        await client._git(["add", "."], checkout)
        await client._git(["commit", "-m", "initial"], checkout)
        await client._git(["remote", "add", "origin", remote.as_uri()], checkout)
        await client._git(["push", "origin", "main"], checkout)
        await client._git(["checkout", "-b", "ai-dlc/test"], checkout)
        (checkout / "implementation.txt").write_text("implementation", encoding="utf-8")
        sha = await client.publish(checkout, "ai-dlc/test", "story")
        assert await client._git(["rev-parse", "refs/heads/ai-dlc/test"], remote) == sha
        assert await client.publish(checkout, "ai-dlc/test", "retry", allow_unchanged=True) == sha
        (checkout / "implementation.txt").write_text("remediated", encoding="utf-8")
        updated = await client.publish(checkout, "ai-dlc/test", "remediation", allow_unchanged=True)
        assert updated != sha
        assert await client._git(["rev-parse", "refs/heads/ai-dlc/test"], remote) == updated
    asyncio.run(scenario())


def test_angular_install_rejects_unsupported_node(tmp_path):
    if not shutil.which("npm"):
        pytest.skip("npm is not installed")
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "runtime-check", "version": "1.0.0", "private": True, "engines": {"node": ">=999"},
    }), encoding="utf-8")

    async def scenario():
        lock = await run_command([
            "npm", "install", "--package-lock-only", "--ignore-scripts", "--offline", "--no-audit",
            "--no-fund", "--engine-strict=false",
        ], tmp_path, timeout=60)
        assert lock["passed"], lock["output"]
        command = stacks.get("angular").checks(tmp_path)[0]
        result = await run_command([*command, "--offline", "--ignore-scripts", "--no-audit", "--no-fund"], tmp_path, timeout=60)
        assert not result["passed"]
        assert "EBADENGINE" in result["output"]
    asyncio.run(scenario())