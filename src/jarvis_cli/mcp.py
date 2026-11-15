"""Persistent policy-enforced MCP clients for stdio and HTTP transports."""

from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import queue
import re
import subprocess
from threading import RLock, Thread
from time import monotonic
from typing import Any
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from jarvis_core import MCPServerConfig, ToolPermission

from .client import APIError
from .process_env import sanitized_subprocess_env

MAX_MCP_RESPONSE_BYTES = max(
    65_536,
    int(os.getenv("JARVIS_MAX_MCP_RESPONSE_BYTES", "4194304")),
)
MAX_MCP_ERROR_BYTES = 4_096

# CLI-14: advertise a real MCP protocol revision and validate the server's
# response. Streamable-HTTP servers reject requests that skip the handshake.
MCP_PROTOCOL_VERSION = "2025-06-18"
_SESSION_ID_PATTERN = re.compile(r"[\x21-\x7e]{1,512}")


def _client_info() -> dict[str, Any]:
    from . import __version__

    return {"name": "jarvis", "version": __version__}


def _error_detail(exc: HTTPError) -> str:
    """Extract a bounded JSON-RPC message from an error response body."""
    try:
        payload = json.loads(exc.read(MAX_MCP_ERROR_BYTES).decode("utf-8", "replace"))
    except Exception:
        return ""
    message = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "")
        elif isinstance(error, (str, int, float)):
            message = str(error)
    return f": {message}" if message else ""


class MCPClient:
    def __init__(
        self,
        command: list[str],
        *,
        timeout: float = 30.0,
        permissions: dict[str, ToolPermission] | None = None,
    ) -> None:
        if not command:
            raise ValueError("MCP command cannot be empty")
        self.command = command
        self.timeout = timeout
        self.permissions = permissions or {}
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._lock = RLock()
        self._next_id = 0
        self._initialized = False
        self.protocol_version: str | None = None
        self.server_info: dict[str, Any] | None = None
        self.server_capabilities: dict[str, Any] = {}
        self.last_ok: float | None = None
        atexit.register(self.close)

    def _start_locked(self) -> subprocess.Popen[str]:
        if self._process and self._process.poll() is None:
            return self._process
        process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # Never leave an unread PIPE here: a noisy MCP server can fill the
            # OS pipe buffer and deadlock its JSON-RPC stdout path.
            stderr=subprocess.DEVNULL,
            text=True,
            shell=False,
            bufsize=1,
            env=sanitized_subprocess_env("JARVIS_MCP_ENV_ALLOW"),
        )
        self._process = process
        Thread(target=self._reader, args=(process,), daemon=True).start()
        self._initialized = False
        return process

    def start(self) -> None:
        with self._lock:
            self._start_locked()

    def _reader(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and "id" in item:
                self._responses.put(item)

    def _send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self._lock:
            process = self._start_locked()
            if process.stdin is None:
                raise APIError("MCP process stdin is unavailable")
            self._next_id += 1
            request_id = self._next_id
            process.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": params or {},
                    }
                )
                + "\n"
            )
            process.stdin.flush()
            deadline = monotonic() + self.timeout
            deferred: list[dict[str, Any]] = []
            try:
                while monotonic() < deadline:
                    try:
                        response = self._responses.get(
                            timeout=max(0.01, deadline - monotonic())
                        )
                    except queue.Empty:
                        break
                    if response.get("id") != request_id:
                        deferred.append(response)
                        continue
                    if "error" in response:
                        raise APIError(f"MCP error: {response['error']}")
                    self.last_ok = monotonic()
                    return response.get("result")
            finally:
                for item in deferred:
                    self._responses.put(item)
        raise APIError(f"MCP request timed out: {method}")

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            result = self._send(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": _client_info(),
                },
            )
            # CLI-14: a server that answers initialize without a protocol
            # version is not speaking MCP; fail loudly instead of proceeding.
            if not isinstance(result, dict):
                raise APIError("MCP server returned a non-object initialize result")
            version = result.get("protocolVersion")
            if not isinstance(version, str) or not version.strip():
                raise APIError(
                    "MCP server returned no protocolVersion during initialize"
                )
            self.protocol_version = version
            capabilities = result.get("capabilities")
            self.server_capabilities = (
                capabilities if isinstance(capabilities, dict) else {}
            )
            info = result.get("serverInfo")
            self.server_info = info if isinstance(info, dict) else None
            process = self._start_locked()
            if process.stdin is None:
                raise APIError("MCP process stdin is unavailable")
            process.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {},
                    }
                )
                + "\n"
            )
            process.stdin.flush()
            self._initialized = True

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        return list((self._send("tools/list") or {}).get("tools") or [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        permission = self.permissions.get(name)
        if permission is None or not permission.allow:
            raise APIError(f"MCP tool is denied by policy: {name}")
        if permission.requires_approval:
            raise APIError(
                f"MCP tool requires approval: {name}. "
                "Use authorize_mcp_call() or configure approval in MCP policy."
            )
        self.initialize()
        return self._send("tools/call", {"name": name, "arguments": arguments})

    def health(self) -> dict[str, Any]:
        with self._lock:
            running = self._process is not None and self._process.poll() is None
        return {
            "running": running,
            "last_ok": self.last_ok,
            "command": self.command,
            "initialized": self._initialized,
            "protocol_version": self.protocol_version,
            "server_info": self.server_info,
        }

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._initialized = False
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


class _RejectRedirects(HTTPRedirectHandler):
    """Never forward MCP credentials or requests across redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise APIError(f"MCP endpoint redirects are forbidden ({code} to {newurl})")


class HTTPMCPClient:
    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        timeout: float = 30,
        permissions: dict[str, ToolPermission] | None = None,
    ) -> None:
        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").casefold()
        local_http = parsed.scheme == "http" and host in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if parsed.scheme != "https" and not local_http:
            raise ValueError(
                "remote MCP endpoints must use HTTPS; plain HTTP is limited "
                "to exact loopback hosts"
            )
        if not host or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("MCP endpoint URL contains unsafe authority data")
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout
        self.permissions = permissions or {}
        self._opener = build_opener(_RejectRedirects())
        self._next_id = 0
        self._lock = RLock()
        self._session_id: str | None = None
        self._initialized = False
        self.protocol_version: str | None = None
        self.server_info: dict[str, Any] | None = None
        self.server_capabilities: dict[str, Any] = {}
        self.last_ok: float | None = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _post(
        self, payload: dict[str, Any], *, request_id: int | None
    ) -> tuple[Any, dict[str, str]]:
        """POST one JSON-RPC message and return (result, response headers)."""
        body = json.dumps(payload).encode()
        try:
            with self._opener.open(
                Request(self.endpoint, body, self._headers()), timeout=self.timeout
            ) as response:
                raw = response.read(MAX_MCP_RESPONSE_BYTES + 1)
                response_headers = {
                    key: value for key, value in response.headers.items()
                }
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                raise APIError("MCP endpoint redirects are forbidden") from exc
            raise APIError(
                f"MCP HTTP request failed: {exc.code}{_error_detail(exc)}"
            ) from exc
        if len(raw) > MAX_MCP_RESPONSE_BYTES:
            raise APIError(
                "MCP HTTP response exceeded the configured "
                f"{MAX_MCP_RESPONSE_BYTES}-byte safety limit"
            )
        if request_id is None:
            # Notifications may be answered with an empty body (HTTP 202).
            if not raw.strip():
                return None, response_headers
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise APIError("MCP endpoint returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise APIError("MCP endpoint returned a non-object JSON response")
        if request_id is not None and data.get("id") not in {None, request_id}:
            raise APIError("MCP endpoint returned a mismatched JSON-RPC id")
        if "error" in data:
            raise APIError(f"MCP error: {data['error']}")
        if request_id is not None:
            self.last_ok = monotonic()
        return data.get("result"), response_headers

    def initialize(self) -> None:
        """Perform the MCP initialize handshake (CLI-14).

        Real Streamable-HTTP servers reject tools/list and tools/call from
        clients that never sent `initialize`, and they assign a
        `Mcp-Session-Id` that must accompany every later request.
        """
        with self._lock:
            if self._initialized:
                return
            self._next_id += 1
            request_id = self._next_id
            result, response_headers = self._post(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": _client_info(),
                    },
                },
                request_id=request_id,
            )
            if not isinstance(result, dict):
                raise APIError("MCP server returned a non-object initialize result")
            version = result.get("protocolVersion")
            if not isinstance(version, str) or not version.strip():
                raise APIError(
                    "MCP server returned no protocolVersion during initialize"
                )
            self.protocol_version = version
            capabilities = result.get("capabilities")
            self.server_capabilities = (
                capabilities if isinstance(capabilities, dict) else {}
            )
            info = result.get("serverInfo")
            self.server_info = info if isinstance(info, dict) else None
            session = response_headers.get("Mcp-Session-Id")
            if session:
                session = session.strip()
                if not _SESSION_ID_PATTERN.fullmatch(session):
                    raise APIError("MCP server returned an invalid Mcp-Session-Id")
                self._session_id = session
            self._post(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                },
                request_id=None,
            )
            self._initialized = True

    def _send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            result, _ = self._post(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                },
                request_id=request_id,
            )
            return result

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        return list((self._send("tools/list") or {}).get("tools") or [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        permission = self.permissions.get(name)
        if permission is None or not permission.allow:
            raise APIError(f"MCP tool is denied by policy: {name}")
        if permission.requires_approval:
            raise APIError(
                f"MCP tool requires approval: {name}. "
                "Use authorize_mcp_call() or configure approval in MCP policy."
            )
        self.initialize()
        return self._send("tools/call", {"name": name, "arguments": arguments})

    def health(self) -> dict[str, Any]:
        return {
            "running": True,
            "last_ok": self.last_ok,
            "endpoint": self.endpoint,
            "initialized": self._initialized,
            "protocol_version": self.protocol_version,
            "server_info": self.server_info,
            "session": self._session_id is not None,
        }


def default_mcp_config_path() -> Path:
    configured = os.getenv("JARVIS_MCP_CONFIG")
    if configured:
        return Path(configured).expanduser()
    base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "jarvis/mcp.toml"


def load_mcp_config(
    path: str | Path | None = None,
) -> dict[str, MCPServerConfig]:
    target = Path(path) if path is not None else default_mcp_config_path()
    if not target.exists():
        return {}

    data = tomllib.loads(target.read_text(encoding="utf-8"))
    result = {}
    for name, item in (data.get("servers") or {}).items():
        permissions = tuple(
            ToolPermission(
                name,
                tool,
                bool(policy.get("allow", False)),
                bool(policy.get("requires_approval", True)),
                bool(policy.get("read_only", False)),
            )
            for tool, policy in (item.get("tools") or {}).items()
        )
        result[name] = MCPServerConfig(
            name,
            str(item["transport"]),
            str(item["endpoint"]),
            item.get("oauth_audience"),
            int(item.get("health_interval_seconds", 30)),
            permissions,
        )
    return result


def oauth_token(config: MCPServerConfig) -> str | None:
    env = f"JARVIS_MCP_{config.name.upper().replace('-', '_')}_TOKEN"
    return os.getenv(env)
