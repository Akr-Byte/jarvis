"""P0.7 world-class hardening regressions.

Covers the R-1/R-2 findings and the follow-up review items: project `.env`
trust gating, advisory completion gate, undo/new-file policy, `search_text`
option injection, session persistence/permissions, read-only resume, sandbox
allowlist honesty, and MCP Streamable-HTTP transport details.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess

import pytest

from jarvis_cli import main as cli_main
from jarvis_cli.sandbox import sandbox_command
from jarvis_cli.sessions import SessionStore

# --- R-1: project .env is executable configuration ------------------------


def test_project_env_is_not_loaded_for_untrusted_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.delenv("JARVIS_TRUST_WORKSPACE", raising=False)
    monkeypatch.delenv("JARVIS_GLOBAL_ENV", raising=False)
    monkeypatch.delenv("P07_UNTRUSTED_MARKER", raising=False)
    (tmp_path / ".env").write_text("P07_UNTRUSTED_MARKER=1\n", encoding="utf-8")

    assert cli_main.load_project_env(tmp_path) is False
    assert "P07_UNTRUSTED_MARKER" not in os.environ


def test_trusted_project_env_skips_security_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_TRUST_WORKSPACE", "true")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.delenv("P07_TRUSTED_MARKER", raising=False)
    monkeypatch.setenv("INFERENCE_BASE_URL", "http://safe.local/v1")
    (tmp_path / ".env").write_text(
        "P07_TRUSTED_MARKER=1\n"
        "INFERENCE_BASE_URL=http://hostile.invalid/v1\n"
        "JARVIS_SANDBOX=off\n",
        encoding="utf-8",
    )

    assert cli_main.load_project_env(tmp_path) is True
    assert os.environ["P07_TRUSTED_MARKER"] == "1"
    # Security-critical keys are ignored even in a trusted workspace.
    assert os.environ["INFERENCE_BASE_URL"] == "http://safe.local/v1"


# --- invalid numeric environment defaults fail loudly ---------------------


def test_invalid_numeric_env_default_is_reported(monkeypatch):
    monkeypatch.setenv("JARVIS_MAX_STEPS", "not-a-number")
    with pytest.raises(SystemExit, match="must be an integer"):
        cli_main._env_int("JARVIS_MAX_STEPS", 30)

    monkeypatch.setenv("JARVIS_TIMEOUT", "soon")
    with pytest.raises(SystemExit, match="must be a number"):
        cli_main._env_float("JARVIS_TIMEOUT", 180.0)


# --- undo is a real subcommand --------------------------------------------


def test_undo_is_a_parsed_subcommand(tmp_path):
    args = cli_main.build_parser().parse_args(["undo", "--workspace", str(tmp_path)])
    assert args.command == "undo"
    assert args.local_workspace == str(tmp_path)


# --- R-2: completion evidence gate is advisory ----------------------------


def test_proof_gate_is_advisory_unless_strict(monkeypatch):
    from jarvis_cli import proof_runtime

    monkeypatch.delenv("JARVIS_PROOF_GATE", raising=False)
    assert proof_runtime._proof_gate_is_strict() is False
    monkeypatch.setenv("JARVIS_PROOF_GATE", "strict")
    assert proof_runtime._proof_gate_is_strict() is True


def test_tests_are_only_required_when_the_task_asks_for_them():
    from jarvis_cli.proof_runtime import _task_requires_tests

    assert _task_requires_tests("Add a subtract function") is False
    assert _task_requires_tests("Add a subtract function and tests") is True
    assert _task_requires_tests("Fix the build; verify with pytest") is True


# --- patch guard: new root files allowed, secrets/Git rejected -------------


def test_patch_guard_allows_new_files_but_not_protected_paths(tmp_path):
    from jarvis_cli.patch_guard_v07 import PatchPlan, PatchTarget, _allowed

    plan = PatchPlan(
        goal="say hello",
        category="code",
        targets=(PatchTarget("src/app.py"),),
        allow_new_files=True,
    )
    discovered: set[str] = set()

    assert _allowed("hello.txt", plan, discovered, tmp_path) is True
    assert _allowed("Makefile", plan, discovered, tmp_path) is True
    for blocked in (".env", ".env.local", ".git/config", ".jarvis/hooks.toml"):
        assert _allowed(blocked, plan, discovered, tmp_path) is False
    assert _allowed("../escape.txt", plan, discovered, tmp_path) is False


# --- CLI-18: search_text cannot smuggle ripgrep options -------------------


def test_search_text_terminates_option_parsing(tmp_path, monkeypatch):
    from jarvis_cli.local_agent import LocalConfig, LocalTools

    config = LocalConfig(
        provider="openai",
        model="scripted",
        api_key="secret",
        base_url="https://model.test/v1",
        workspace=tmp_path,
    )
    tools = LocalTools(config)
    captured: list[list[str]] = []
    monkeypatch.setattr(
        tools, "_command", lambda argv, **kw: captured.append(argv) or ""
    )

    tools.execute("search_text", {"pattern": "--pre=touch /tmp/pwned", "path": "."})

    argv = captured[0]
    assert "--" in argv
    pattern_index = argv.index("--pre=touch /tmp/pwned")
    assert argv.index("--") < pattern_index


# --- sessions: persistence, footer, permissions, read-only ----------------

EVIDENCE_FOOTER = '\n\nEfficiency/evidence: {"tests_passed": 1}'


def test_failed_runs_are_not_persisted_as_assistant_turns(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    session = store.create(workspace=str(tmp_path), task="t", model="scripted")

    store.finish(session.id, result="APIError: model exploded", status="failed")

    transcript = store.transcript(session.id)
    assert [m for m in transcript if m["role"] == "assistant"] == []
    assert store.get(session.id).status == "failed"


def test_evidence_footer_is_stripped_from_the_transcript(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    session = store.create(workspace=str(tmp_path), task="t", model="scripted")

    store.finish(session.id, result="Added hello()" + EVIDENCE_FOOTER)

    transcript = store.transcript(session.id)
    assert transcript[-1] == {"role": "assistant", "content": "Added hello()"}


def test_session_database_is_private(tmp_path):
    store = SessionStore(tmp_path / "state" / "jarvis" / "sessions.sqlite3")
    store.create(workspace=str(tmp_path), task="t", model="scripted")

    mode = stat.S_IMODE(store.path.stat().st_mode)
    assert mode & 0o077 == 0
    assert stat.S_IMODE(store.path.parent.stat().st_mode) & 0o077 == 0


def test_resume_keeps_the_recorded_read_only_mode(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    session = store.create(
        workspace=str(tmp_path),
        task="t",
        model="scripted",
        metadata={"write": False},
    )
    forked = store.fork(session.id)

    assert store.session_metadata(session.id) == {"write": False}
    assert store.session_metadata(forked.id) == {"write": False}

    args = cli_main.build_parser().parse_args(["session-resume", session.id])
    assert args.write is None
    args = cli_main.build_parser().parse_args(["session-resume", session.id, "--write"])
    assert args.write is True
    args = cli_main.build_parser().parse_args(
        ["session-resume", session.id, "--read-only"]
    )
    assert args.write is False


# --- undo stack works without Git ----------------------------------------


def test_non_git_workspace_gets_a_durable_undo_stack(tmp_path, monkeypatch):
    from jarvis_cli import local_agent

    stack = local_agent._workspace_patch_stack(tmp_path)
    assert stack == tmp_path / ".jarvis" / "patches"
    stack.mkdir(parents=True)
    (stack / "001.patch").write_text("--- a/x\n+++ b/x\n", encoding="utf-8")

    reversed_patches: list[str] = []
    monkeypatch.setattr(
        local_agent,
        "_reverse_patch",
        lambda root, patch, **kw: reversed_patches.append(patch),
    )

    message = local_agent.undo_last_patch(tmp_path)

    assert "reversed" in message
    assert reversed_patches == ["--- a/x\n+++ b/x\n"]
    assert list(stack.glob("*.patch")) == []


def test_apply_patch_records_undo_even_outside_git(tmp_path, monkeypatch):
    from jarvis_cli import local_agent

    config = local_agent.LocalConfig(
        provider="openai",
        model="scripted",
        api_key="secret",
        base_url="https://model.test/v1",
        workspace=tmp_path,
        accept_edits=True,
    )
    tools = local_agent.LocalTools(config)
    stack = tmp_path / ".jarvis" / "patches"
    monkeypatch.setattr(local_agent, "_workspace_patch_stack", lambda root: stack)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "", ""),
    )

    result = tools._apply_patch("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")

    assert "Patch applied" in result
    assert len(list(stack.glob("*.patch"))) == 1


# --- sandbox: allowlist is unenforceable, so say so -----------------------


def test_sandbox_allowlist_fails_loudly_instead_of_denying_everything(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JARVIS_NETWORK", "allowlist")
    monkeypatch.delenv("JARVIS_SANDBOX", raising=False)

    with pytest.raises(RuntimeError, match="host allowlist"):
        sandbox_command(["echo", "hi"], tmp_path)


# --- MCP Streamable HTTP: Accept/SSE, protocol version, DELETE ------------


class _Response:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self._body = body
        self.headers = headers

    def read(self, size=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Server:
    def __init__(self, handler):
        self.handler = handler
        self.requests: list = []
        self._opener = self

    def open(self, request, timeout=None):
        self.requests.append(request)
        body, headers = self.handler(self, request)
        return _Response(body, headers)


def _header(request, name: str) -> str:
    for key, value in request.headers.items():
        if key.casefold() == name.casefold():
            return value
    return ""


def _sse(payload: dict) -> bytes:
    return b"event: message\ndata: " + json.dumps(payload).encode() + b"\n\n"


def test_http_mcp_client_negotiates_sse_and_cleans_up_session():
    from jarvis_cli.mcp import HTTPMCPClient, MCP_PROTOCOL_VERSION

    def handler(server, request):
        if request.get_method() == "DELETE":
            return b"", {"Content-Type": "application/json"}
        payload = json.loads(request.data.decode("utf-8"))
        method = payload.get("method")
        if method == "initialize":
            return (
                _sse(
                    {
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {
                            "protocolVersion": MCP_PROTOCOL_VERSION,
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "fake", "version": "1"},
                        },
                    }
                ),
                {"Content-Type": "text/event-stream", "Mcp-Session-Id": "sess-7"},
            )
        if method == "notifications/initialized":
            return b"", {"Content-Type": "application/json"}
        if method == "tools/list":
            return (
                _sse(
                    {
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {"tools": [{"name": "ping"}]},
                    }
                ),
                {"Content-Type": "text/event-stream"},
            )
        raise AssertionError(f"unexpected method {method}")

    server = _Server(handler)
    client = HTTPMCPClient("https://mcp.example/mcp")
    client._opener = server

    assert client.list_tools() == [{"name": "ping"}]
    initialize, notification, tools_list = server.requests
    assert "text/event-stream" in _header(initialize, "Accept")
    assert _header(initialize, "MCP-Protocol-Version") == ""
    assert _header(tools_list, "MCP-Protocol-Version") == MCP_PROTOCOL_VERSION
    assert _header(tools_list, "Mcp-Session-Id") == "sess-7"
    assert _header(notification, "Mcp-Session-Id") == "sess-7"

    client.close()
    assert server.requests[-1].get_method() == "DELETE"
    assert _header(server.requests[-1], "Mcp-Session-Id") == "sess-7"
    assert client.health()["session"] is False
