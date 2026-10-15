import asyncio
import os
import shutil
import tempfile
from pathlib import Path


async def run_command(command, workspace, timeout=1800, env=None, output_limit=10000):
    command = list(command)
    root = Path(workspace).resolve()
    wrapper = {"mvn": "mvnw", "gradle": "gradlew"}.get(command[0])
    if wrapper:
        suffix = (".cmd" if wrapper == "mvnw" else ".bat") if os.name == "nt" else ""
        candidate = root / (wrapper + suffix)
        if candidate.is_file():
            command[0] = str(candidate)
    executable = shutil.which(command[0])
    if not executable:
        return {"command": command, "passed": False, "exit_code": None, "output": f"Executable not found: {command[0]}"}
    command[0] = executable
    with tempfile.TemporaryFile() as output:
        process = await asyncio.create_subprocess_exec(
            *command, cwd=root, env=env, stdout=output, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
        )
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError) as error:
            timed_out = True
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec(
                    "taskkill", "/PID", str(process.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await killer.wait()
            else:
                process.kill()
            await process.wait()
            if isinstance(error, asyncio.CancelledError):
                raise
        output.seek(0, 2)
        output.seek(max(0, output.tell() - output_limit))
        text = output.read().decode("utf-8", errors="replace")
    return {"command": command, "passed": not timed_out and process.returncode == 0,
            "exit_code": process.returncode, "output": "Command timed out" if timed_out else text}