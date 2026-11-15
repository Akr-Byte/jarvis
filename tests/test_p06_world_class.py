"""P0.6 world-class hardening: MCP handshake (CLI-14), SIGTERM durability
(CLI-15), patch-approval diff + undo stack (CLI-12), identity-scoped dedupe
(CLI-18), and bare-task routing (CLI-19)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from jarvis_cli.client import APIError
from jarvis_cli.local_agent import (
    LocalConfig,
    LocalTools,
    _run_single_agent,
    undo_last_patch,
)
from jarvis_cli.mcp import MCP_PROTOCOL_VERSION, HTTPMCPClient, MCPClient
from jarvis_cli.main import CLI_COMMANDS, normalize_argv

# --- CLI-14: HTTP MCP initialize handshake + session tracking --------------


class _FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self._body = body
        self.headers = headers

    def read(self, size=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeMCPServer:
    """Stateful Streamable-HTTP server double driven by a script."""

    def __init__(self, handler):
        self.handler = handler
        self.requests: list = []
        self._opener = self

    def open(self, request, timeout=None):
        self.requests.append(request)
        body, headers = self.handler(self, json.loads(request.data.decode("utf-8")))
        return _FakeResponse(body, headers)


def _result_response(result, headers=None):
    def handler(server, payload):
        rid = payload.get("id")
        body = json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}).encode()
        return body, headers or {}

    return handler


def _methods(server):
    return [
        json.loads(request.data.decode("utf-8")).get("method")
        for request in server.requests
    ]


def test_http_mcp_client_performs_initialize_and_tracks_session():
    server_state: dict = {}

    def handler(server, payload):
        method = payload.get("method")
        if method == "initialize":
            server_state["initialized"] = True
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake", "version": "1.0"},
                    },
                }
            ).encode()
            return body, {"Mcp-Session-Id": "sess-123"}
        if method == "notifications/initialized":
            return b"", {}
        if method == "tools/list":
            assert payload["id"] is not None
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {"tools": [{"name": "ping", "inputSchema": {}}]},
                }
            ).encode()
            return body, {}
        raise AssertionError(f"unexpected method {method}")

    server = FakeMCPServer(handler)
    client = HTTPMCPClient("https://mcp.example/mcp")
    client._opener = server

    tools = client.list_tools()

    assert tools == [{"name": "ping", "inputSchema": {}}]
    assert _methods(server) == ["initialize", "notifications/initialized", "tools/list"]
    assert client.protocol_version == MCP_PROTOCOL_VERSION
    assert client.server_info == {"name": "fake", "version": "1.0"}
    assert client.server_capabilities == {"tools": {}}
    assert client._session_id == "sess-123"
    assert client.health()["session"] is True
    # Every post-handshake request carries the session id.
    assert server.requests[-1].get_header("Mcp-session-id") == "sess-123"


def test_http_mcp_client_rejects_initialize_without_protocol_version():
    server = FakeMCPServer(_result_response({"capabilities": {}}))
    client = HTTPMCPClient("https://mcp.example/mcp")
    client._opener = server

    with pytest.raises(APIError, match="protocolVersion"):
        client.list_tools()


def test_http_mcp_client_rejects_invalid_session_header():
    server = FakeMCPServer(
        _result_response(
            {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {}},
            headers={"Mcp-Session-Id": "bad header\ninjected"},
        )
    )
    client = HTTPMCPClient("https://mcp.example/mcp")
    client._opener = server

    with pytest.raises(APIError, match="Mcp-Session-Id"):
        client.list_tools()


def test_stdio_mcp_client_records_negotiated_protocol():
    script = """
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "initialize":
        sys.stdout.write(json.dumps({
            "jsonrpc": "2.0", "id": req["id"],
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-stdio", "version": "0.1"},
            },
        }) + "\\n")
        sys.stdout.flush()
    elif method == "tools/list":
        sys.stdout.write(json.dumps({
            "jsonrpc": "2.0", "id": req["id"],
            "result": {"tools": [{"name": "ping", "inputSchema": {}}]},
        }) + "\\n")
        sys.stdout.flush()
"""
    client = MCPClient([sys.executable, "-c", script], timeout=30)
    try:
        tools = client.list_tools()
        assert tools == [{"name": "ping", "inputSchema": {}}]
        assert client.protocol_version == MCP_PROTOCOL_VERSION
        assert client.server_info == {"name": "fake-stdio", "version": "0.1"}
    finally:
        client.close()


# --- CLI-15: SIGTERM marks the local run failed ----------------------------


def _config(tmp_path):
    return LocalConfig(
        provider="openai",
        model="scripted",
        api_key="secret",
        base_url="https://model.test/v1",
        workspace=tmp_path,
    )


def test_sigterm_during_local_run_marks_session_failed(monkeypatch, tmp_path):
    from jarvis_cli import main as cli_main
    from jarvis_cli.sessions import SessionStore

    monkeypatch.setenv("JARVIS_SESSION_DB", str(tmp_path / "sessions.sqlite3"))
    monkeypatch.delenv("INFERENCE_BASE_URL", raising=False)
    monkeypatch.delenv("INFERENCE_API_KEY", raising=False)
    monkeypatch.setenv("INFERENCE_BASE_URL", "http://model.test/v1")
    monkeypatch.setenv("INFERENCE_API_KEY", "k")

    def terminated_run(*args, **kwargs):
        # Deliver a real SIGTERM mid-run; the CLI must convert it into the
        # normal cancellation path (CLI-15) instead of dying silently and
        # leaving a zombie 'running' session.
        os.kill(os.getpid(), signal.SIGTERM)
        return "never reached"

    monkeypatch.setattr("jarvis_cli.local_agent.run_local_agent", terminated_run)

    rc = cli_main.main(["local", "hold", "the", "line"])

    assert rc == 130
    sessions = SessionStore().list()
    assert len(sessions) == 1
    assert sessions[0].status == "failed"


# --- CLI-12: patch approval shows the diff; undo walks a patch stack -------


def test_patch_approval_prompt_contains_the_diff(monkeypatch, tmp_path):
    prompts: list[str] = []

    def approval(description: str) -> bool:
        prompts.append(description)
        return True

    tools = LocalTools(_config(tmp_path), approval=approval)
    patch = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    # Stub the git plumbing: the test targets the approval UX, not git apply.
    monkeypatch.setattr(
        tools,
        "_patch_stack",
        lambda: None,
        raising=False,
    )
    runs = {
        "check": subprocess.CompletedProcess([], 0, "", ""),
        "apply": subprocess.CompletedProcess([], 0, "", ""),
    }

    def fake_run(argv, **kwargs):
        key = "check" if "--check" in argv else "apply"
        return runs[key]

    monkeypatch.setattr(tools, "_command", lambda *a, **kw: "")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = tools._apply_patch(patch)

    assert "Patch applied" in result
    assert len(prompts) == 1
    # The exact diff is visible at approval time — no more blind y/N.
    assert "+++ b/README.md" in prompts[0]
    assert "-old" in prompts[0] and "+new" in prompts[0]


def test_patch_preview_is_bounded():
    from jarvis_cli.local_agent import _patch_preview

    preview = _patch_preview("x" * 20_000)
    assert len(preview) < 10_000
    assert "truncated" in preview


def _git_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "t@example.com"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)
    return root


def test_undo_walks_the_patch_stack(tmp_path):
    root = _git_repo(tmp_path)

    def patch_for(before: str, after: str, path: str) -> str:
        return (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1 +1 @@\n"
            f"-{before}\n"
            f"+{after}\n"
        )

    tools = LocalTools(
        LocalConfig(
            provider="openai",
            model="scripted",
            api_key="secret",
            base_url="https://model.test/v1",
            workspace=root,
            accept_edits=True,
        )
    )
    tools._apply_patch(patch_for("one", "two", "a.txt"))
    assert (root / "a.txt").read_text() == "two\n"
    tools._apply_patch(patch_for("two", "three", "a.txt"))
    assert (root / "a.txt").read_text() == "three\n"

    assert "earlier patch(es) remain undoable" in undo_last_patch(root)
    assert (root / "a.txt").read_text() == "two\n"
    undo_last_patch(root)
    assert (root / "a.txt").read_text() == "one\n"
    with pytest.raises(APIError, match="No Jarvis patch"):
        undo_last_patch(root)


def test_undo_falls_back_to_legacy_single_patch_file(tmp_path):
    root = _git_repo(tmp_path)
    legacy = subprocess.run(
        ["git", "rev-parse", "--git-path", "jarvis-last.patch"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    legacy_path = root / legacy.stdout.strip()
    patch = (
        "diff --git a/a.txt b/a.txt\n"
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1 +1 @@\n"
        "-one\n"
        "+two\n"
    )
    legacy_path.write_text(patch, encoding="utf-8")
    # The legacy CLI applied the patch before recording it; a.txt now holds
    # the patched content and the stored patch reverses it.
    applied = subprocess.run(
        ["git", "apply", "-"],
        cwd=root,
        input=patch,
        text=True,
        capture_output=True,
        check=True,
    )
    assert (root / "a.txt").read_text() == "two\n"

    undo_last_patch(root)

    assert (root / "a.txt").read_text() == "one\n"
    assert not legacy_path.exists()


# --- CLI-18: dedupe distinguishes same-content different-input calls -------


def test_evidence_dedupe_keys_on_tool_identity(monkeypatch, tmp_path):
    from jarvis_cli import evidence_v07, local_agent

    evidence_v07._INSTALLED = False
    evidence_v07.install_evidence_v07()
    try:
        identity = local_agent._TOOL_IDENTITY
        digests_token = evidence_v07._DIGESTS.set(set())
        try:
            first = identity.set({"name": "read_file", "arguments": {"path": "a.txt"}})
            try:
                first_summary = local_agent.summarize_tool_result(
                    "read_file", "identical body", max_chars=100
                )
            finally:
                identity.reset(first)
            second = identity.set({"name": "read_file", "arguments": {"path": "b.txt"}})
            try:
                second_summary = local_agent.summarize_tool_result(
                    "read_file", "identical body", max_chars=100
                )
            finally:
                identity.reset(second)

            # Different inputs, identical text: the second call must NOT be
            # collapsed into a duplicate (CLI-18).
            assert "duplicate_of" not in json.dumps(first_summary)
            assert "duplicate_of" not in json.dumps(second_summary)

            third = identity.set({"name": "read_file", "arguments": {"path": "a.txt"}})
            try:
                repeat = local_agent.summarize_tool_result(
                    "read_file", "identical body", max_chars=100
                )
            finally:
                identity.reset(third)
            assert "duplicate_of" in json.dumps(repeat)
        finally:
            evidence_v07._DIGESTS.reset(digests_token)
    finally:
        evidence_v07._INSTALLED = False


# --- CLI-19: removed-command words route to the local agent ----------------


def test_removed_command_words_are_not_shadowed_by_cli_commands():
    for word in (
        "run",
        "list",
        "show",
        "resume",
        "approve",
        "discard",
        "cancel",
        "projects",
        "workspaces",
        "doctor",
    ):
        assert word not in CLI_COMMANDS


def test_bare_task_starting_with_run_routes_to_local():
    assert normalize_argv(["run", "the", "tests"], CLI_COMMANDS) == [
        "local",
        "run",
        "the",
        "tests",
    ]
    assert normalize_argv(["doctor"], CLI_COMMANDS) == ["local", "doctor"]


def test_real_subcommands_are_still_shadowed():
    assert normalize_argv(["local", "task"], CLI_COMMANDS) == ["local", "task"]
    assert normalize_argv(["trust", "add", "x"], CLI_COMMANDS) == ["trust", "add", "x"]
