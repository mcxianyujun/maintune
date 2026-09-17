import asyncio
import os
import re
import signal
import shutil
from pathlib import Path, PureWindowsPath
from typing import Protocol

import httpx


class SandboxProvider(Protocol):
    async def create(self, task_id: str, ttl: int = 3600) -> str: ...
    async def read_file(self, sandbox: str, path: str) -> str: ...
    async def write_file(self, sandbox: str, path: str, content: str) -> None: ...
    async def exec(self, sandbox: str, command: str, timeout: int, cwd: str = ".") -> dict: ...
    async def destroy(self, sandbox: str) -> None: ...


class LocalSandbox:
    """File-only default. A cwd restriction cannot safely confine arbitrary shell."""
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def workspace(self, sandbox: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", sandbox):
            raise ValueError("Invalid sandbox ID")
        path = self.root / sandbox
        if path.is_symlink() or path.is_junction() or path.resolve().parent != self.root:
            raise ValueError("Workspace escape")
        return path

    def path(self, sandbox: str, name: str) -> Path:
        root = self.workspace(sandbox)
        parts = name.replace("\\", "/").split("/")
        if not name or name.startswith(("/", "\\")) or "\x00" in name or ":" in name or PureWindowsPath(name).is_absolute() or Path(name).is_absolute() or ".." in parts:
            raise ValueError("Unsafe path")
        result = root.joinpath(*parts)
        current = root
        for part in parts:
            current /= part
            if current.is_symlink() or current.is_junction():
                raise ValueError("Links are not allowed")
        if not result.resolve().is_relative_to(root.resolve()):
            raise ValueError("Path escape")
        return result

    async def create(self, task_id: str, ttl: int = 3600) -> str:
        self.workspace(task_id).mkdir(exist_ok=False)
        return task_id

    async def read_file(self, sandbox: str, path: str) -> str:
        target = self.path(sandbox, path)
        if target.stat().st_size > 1_000_000:
            raise ValueError("File too large")
        return target.read_text(encoding="utf-8")

    async def write_file(self, sandbox: str, path: str, content: str) -> None:
        if len(content.encode()) > 1_000_000:
            raise ValueError("File too large")
        target = self.path(sandbox, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    async def exec(self, sandbox: str, command: str, timeout: int, cwd: str = ".") -> dict:
        if not 1 <= timeout <= 7200 or not command or len(command) > 4000:
            raise ValueError("Invalid command or timeout")
        working = self.path(sandbox, cwd)
        working.mkdir(parents=True, exist_ok=True)
        allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "LANG", "LC_ALL", "PATHEXT"}
        environment = {k: v for k, v in os.environ.items() if k.upper() in allowed}
        environment.update({"HOME": str(self.workspace(sandbox)), "USERPROFILE": str(self.workspace(sandbox)), "GIT_TERMINAL_PROMPT": "0", "CI": "1"})
        options = {"cwd": working, "env": environment, "stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.STDOUT}
        if os.name == "nt":
            options["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        process = await asyncio.create_subprocess_shell(command, **options)
        communication = asyncio.create_task(process.communicate())
        done, _ = await asyncio.wait({communication}, timeout=timeout)
        if not done:
            if os.name == "nt":
                # CREATE_NEW_PROCESS_GROUP lets CTRL_BREAK reach the shell and all
                # descendants without requiring administrative taskkill rights.
                os.kill(process.pid, signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            try:
                await asyncio.wait_for(asyncio.shield(communication), 2)
            except TimeoutError:
                if process.returncode is None:
                    process.kill()
                communication.cancel()
                await asyncio.gather(communication, return_exceptions=True)
            raise TimeoutError("Sandbox command timed out") from None
        output, _ = communication.result()
        decoded = output.decode("utf-8", errors="replace")
        truncated = len(decoded) > 100_000
        return {"exit_code": process.returncode, "output": decoded[:100_000], "truncated": truncated}

    async def destroy(self, sandbox: str) -> None:
        target = self.workspace(sandbox)
        if target.exists():
            # No untrusted commands run here; reject links before recursive cleanup.
            if any(p.is_symlink() or p.is_junction() for p in target.rglob("*")):
                raise ValueError("Refusing cleanup of workspace containing links")
            shutil.rmtree(target)


class ShipyardConnection:
    """Bay API v1 connection probe; lifecycle/tool bridge is a separate next stage."""
    async def test(self, base_url: str, key: str) -> dict:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = await client.get(base_url.rstrip("/") + "/v1/sandboxes", params={"limit": 1}, headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            if not isinstance(response.json().get("items"), list):
                raise ValueError("Unexpected Bay API response")
        return {"ok": True, "capability": "Bay API authentication and sandbox listing"}


class ShipyardSandbox:
    # Shipyard Neo's ShellExecRequest currently accepts at most 300 seconds.
    # Keep the controller's larger tool deadline as the outer guard, while
    # sending a provider-valid execution timeout to avoid a 422 response.
    MAX_EXEC_TIMEOUT = 300

    def __init__(self, base_url: str, key: str, profile: str = "python-default"):
        self.base_url, self.key, self.profile = base_url.rstrip("/"), key, profile

    def client(self, timeout: int = 320) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, headers={"Authorization": f"Bearer {self.key}"})

    @staticmethod
    def safe_path(path: str) -> str:
        parts = path.replace("\\", "/").split("/")
        if not path or path.startswith(("/", "\\")) or "\x00" in path or ":" in path or ".." in parts:
            raise ValueError("Unsafe path")
        return "/".join(parts)

    async def create(self, task_id: str, ttl: int = 3600) -> str:
        if not 60 <= ttl <= 86400:
            raise ValueError("Invalid sandbox TTL")
        async with self.client() as client:
            response = await client.post(self.base_url + "/v1/sandboxes", json={"profile": self.profile, "ttl": ttl}, headers={"Idempotency-Key": "maintainer-" + task_id})
            response.raise_for_status()
            body = response.json()
            if not body.get("id"):
                raise ValueError("Unexpected Shipyard response")
            return body["id"]

    async def exec(self, sandbox: str, command: str, timeout: int, cwd: str = ".") -> dict:
        if not 1 <= timeout <= 7200:
            raise ValueError("Invalid timeout")
        execution_timeout = min(timeout, self.MAX_EXEC_TIMEOUT)
        async with self.client(execution_timeout + 20) as client:
            response = await client.post(f"{self.base_url}/v1/sandboxes/{sandbox}/shell/exec", json={"command": command, "timeout": execution_timeout, "cwd": self.safe_path(cwd), "include_code": False, "tags": "ai-maintainer"})
            response.raise_for_status()
            body = response.json()
            return {"exit_code": int(body.get("exit_code", 1)), "output": str(body.get("output") or body.get("error") or "")[:100_000], "truncated": len(str(body.get("output") or "")) > 100_000, "execution_id": body.get("execution_id")}

    async def read_file(self, sandbox: str, path: str) -> str:
        async with self.client() as client:
            response = await client.get(f"{self.base_url}/v1/sandboxes/{sandbox}/filesystem/files", params={"path": self.safe_path(path)})
            response.raise_for_status()
            content = response.json()["content"]
            if len(content.encode()) > 1_000_000:
                raise ValueError("File too large")
            return content

    async def write_file(self, sandbox: str, path: str, content: str) -> None:
        if len(content.encode()) > 1_000_000:
            raise ValueError("File too large")
        async with self.client() as client:
            response = await client.put(f"{self.base_url}/v1/sandboxes/{sandbox}/filesystem/files", json={"path": self.safe_path(path), "content": content})
            response.raise_for_status()

    async def destroy(self, sandbox: str) -> None:
        async with self.client() as client:
            response = await client.delete(f"{self.base_url}/v1/sandboxes/{sandbox}")
            if response.status_code not in (204, 404):
                response.raise_for_status()
