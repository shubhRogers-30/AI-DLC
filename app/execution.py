import asyncio
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path


def _terminate_process(process):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.kill()
    process.wait()


def _run_windows_command(command, root, timeout, env, output_limit, cancelled):
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        timed_out = False
        while process.poll() is None:
            if cancelled.is_set():
                _terminate_process(process)
                raise asyncio.CancelledError
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _terminate_process(process)
                break
            try:
                process.wait(timeout=min(remaining, 0.1))
            except subprocess.TimeoutExpired:
                pass
        output.seek(0, 2)
        output.seek(max(0, output.tell() - output_limit))
        text = output.read().decode("utf-8", errors="replace")
    return {"passed": not timed_out and process.returncode == 0, "exit_code": process.returncode,
            "output": "Command timed out" if timed_out else text}


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
    if os.name == "nt":
        cancelled = threading.Event()
        worker = asyncio.create_task(asyncio.to_thread(
            _run_windows_command, command, root, timeout, env, output_limit, cancelled,
        ))
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled.set()
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                pass
            raise
        return {"command": command, **result}
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