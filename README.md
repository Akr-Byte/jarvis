# Jarvis CLI

[![CI](https://github.com/abdullahalrifat/jarvis/actions/workflows/validate.yml/badge.svg)](https://github.com/abdullahalrifat/jarvis/actions/workflows/validate.yml)
[![Release](https://github.com/abdullahalrifat/jarvis/releases/badge.svg)](https://github.com/abdullahalrifat/jarvis/releases)
[![PyPI](https://img.shields.io/pypi/v/jarvis-agent-cli.svg)](https://pypi.org/project/jarvis-agent-cli/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Status](https://img.shields.io/badge/status-beta-blue)](https://github.com/abdullahalrifat/jarvis/releases)

Jarvis is a distributable terminal AI coding agent. Install it from PyPI with pipx or pip, or
download a standalone executable from GitHub Releases. Cloning the repository is only required for
development.

## Table of contents

- [Overview](#overview)
- [Install](#install)
- [Quick start](#quick-start)
- [Efficient local-agent defaults](#efficient-local-agent-defaults)
- [Current contract line](#current-contract-line)
- [Connect directly to inference](#connect-directly-to-inference)
- [AI Stack boundary](#ai-stack-boundary)
- [Implemented runtime](#implemented-runtime)
- [Token-efficient runtime](#token-efficient-runtime)
- [Real workload efficiency benchmark](#real-workload-efficiency-benchmark)
- [Command surface](#command-surface)
- [Development](#development)
- [Documentation](#documentation)
- [Security](#security)
- [Contributing](#contributing)
- [Support](#support)
- [License](#license)

## Overview

Jarvis is a standalone local coding agent: the agent loop and tools run on the user's machine, and
all model requests go directly to the separately deployed `jarvis-inference` HTTP API.

The CLI is an independent sibling consumer of the provider-neutral Jarvis Core library and of the
`jarvis-inference` gateway. It does not require AI Stack, a database, a vector store, or a web UI for
ordinary local repository work.

## Install

Jarvis is distributed as a normal Python application. You do not need to clone the Git repository to
use it.

### Recommended: pipx

Python 3.10+ is required. pipx installs Jarvis into an isolated environment and exposes the `jarvis`
command globally.

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install jarvis-agent-cli
jarvis --version
```

Upgrade later with:

```bash
pipx upgrade jarvis-agent-cli
```

### Standard pip

```bash
python3 -m pip install jarvis-agent-cli
jarvis --version
```

### Standalone executable

Download the platform-specific `jarvis-*` executable from GitHub Releases. Releases provide Linux
amd64, macOS arm64 and Windows amd64 builds, plus SHA256 checksums and build provenance.

On Linux/macOS:

```bash
chmod +x ./jarvis-*
./jarvis-* --version
```

On Windows, run the `.exe` directly from PowerShell or Command Prompt.

### Development install

Only contributors working on the source tree need a repository checkout:

```bash
git clone https://github.com/abdullahalrifat/jarvis.git
cd jarvis
python3 -m pip install -e .
```

Jarvis 0.12.6 consumes `jarvis-agent-core==0.18.0` from PyPI. The dependency is pinned to the exact
Core release in `pyproject.toml`.

See [docs/install.md](docs/install.md) for the complete distribution and upgrade guide.

## Quick start

Point the CLI at a running inference gateway and run a task against a repository:

```bash
export INFERENCE_BASE_URL=http://<inference-vm-ip>:8080/v1
export INFERENCE_API_KEY=<your-inference-secret>
export JARVIS_MODEL=qwen3:1.7b

jarvis model-doctor
cd /path/to/repository
jarvis "review this repository and fix the highest-impact issue"
```

Bare tasks use the standalone local agent. The agent loop, repository tools, permission checks and
verification run on the machine where Jarvis is installed; only model requests go to the inference
gateway.

## Efficient local-agent defaults

The local agent defaults to 30 steps, a 48,000-token input budget and a 24,000-token output budget.
Limits can be pre-seeded with `JARVIS_MAX_STEPS` (overridable per run with `--max-steps`, hard-capped
at 100 unless you raise the cap with `JARVIS_MAX_STEPS_CAP`) and `JARVIS_TIMEOUT`, which bounds a
single model call (overridable per run with `--timeout`). Runs additionally honor a wall-clock
deadline via `JARVIS_RUN_TIMEOUT_SECONDS` (default 3600; `0` disables it): when it expires between
steps the run stops with a deterministic status summary instead of continuing for hours. Adaptive
multi-agent execution is off by default to avoid speculative extra model calls; enable it with
`JARVIS_ADAPTIVE_AGENTS=true` or explicitly pass `--multi-agent` / `JARVIS_MULTI_AGENT=true` for tasks
that benefit from parallel analysis. Override token ceilings with `JARVIS_MAX_INPUT_TOKENS` and
`JARVIS_MAX_OUTPUT_TOKENS` when a task demonstrably needs more context. Adaptive mode also switches
on the v0.7 structural task-enrichment stack, and `JARVIS_ESCALATE_ON_FAILURE=true` enables repair
passes after a failed first attempt. On small local models keep both off: lean prompts reliably
outperform the enriched multi-step stack.

Qwen3-family models always claim a reasoning capability, but reasoning mode on CPU burns thousands of
tokens per turn before any answer appears. Jarvis therefore always requests `think: false` from the
gateway unless `JARVIS_THINK=true` is set. Enable it only for tasks where slower, deliberate reasoning
is worth the wall-clock cost.

## Current contract line

Jarvis **0.12.6** consumes the provider-neutral Jarvis Core **0.18.0** contracts. All model requests
use the direct inference API; the CLI has no AI Stack remote execution mode.

Jarvis Core 0.18.0 is published as an immutable PyPI release; the CLI pins that exact release so
Jarvis and Core can evolve independently.

Jarvis is a standalone local coding agent. The agent loop and tools run on the user's machine, and all
model requests go directly to the separately deployed `jarvis-inference` HTTP API. The Jarvis CLI does
not call AI Stack and exposes no AI Stack remote execution mode. AI Stack is an independent sibling
application that may also consume the same inference API.

## Connect directly to inference

Configure Jarvis to use the dedicated inference gateway. No AI Stack, database, vector store, or web
UI is required for local repository work.

```bash
export INFERENCE_BASE_URL=http://<inference-vm-ip>:8080/v1
export INFERENCE_API_KEY=<your-inference-secret>
export JARVIS_MODEL=qwen3:1.7b

jarvis model-doctor
cd /path/to/repository
jarvis "review this repository and fix the highest-impact issue"
```

Bare tasks use the standalone local agent. The agent loop, repository tools, permission checks and
verification run on the machine where Jarvis is installed; only model requests go to the inference
gateway.

## AI Stack boundary

Jarvis does not expose AI Stack remote commands and never requires `AI_STACK_BASE_URL` or
`AI_STACK_API_KEY`. Use Jarvis for local repository work; deploy AI Stack independently when you need
its own durable Runs API, queues, retrieval, integrations or UI. Both applications call
`jarvis-inference` directly. See [docs/architecture.md](docs/architecture.md) for ownership boundaries.

## Implemented runtime

The runtime includes bounded repository/Git tools, allowlisted command execution, sandbox/network
policy, sessions/checkpoints, proof records, multimodal context, hierarchical instructions/memory,
Skills/Hooks, deny-by-default MCP, repository/LSP intelligence, worktrees, plan mode, adaptive
context, failure memory, multi-agent execution, heterogeneous routing, browser verification, background
jobs/cron and observability.

## Token-efficient runtime

Core 0.18.0 provides provider-neutral primitives for bounded context construction, token/cost
estimation, route budgets, adaptive routing and empirical route calibration. Jarvis keeps inference
execution policy in the CLI, while shared efficiency and calibration contracts remain provider-neutral
in Core.

Context construction can prioritize required task state, recent tool evidence and relevant files under
an explicit budget. Route decisions can account for estimated token cost, latency, risk and measured
task outcomes.

## Real workload efficiency benchmark

Jarvis owns local runtime observations, task-level workload definitions and quality evaluation. AI
Stack owns telemetry and calibration for server-side Runs. Both adapt their own measured outcomes to
the provider-neutral `jarvis-core` observation/calibration contract.

Use the corpus to compare local-only and automatic routes using success, quality, incorrect
completions, tool failures, latency, input/output/cache tokens and estimated cost. Runtime evidence
should only influence automatic routing after the Core minimum-sample and quality-floor safeguards are
satisfied.

## Command surface

Representative commands:

| Command | Purpose |
| --- | --- |
| `jarvis --version` | Print the CLI version. |
| `jarvis "task"` | Run a bare task with the standalone local agent. |
| `jarvis local` | Start the local agent REPL (`--write`, `--allow-edits`, `--detach` supported). |
| `jarvis session-resume <id>` | Resume a searchable local session (with `--force` for SIGKILLed runs). |
| `jarvis undo` | Undo the most recent applied patch (numbered patch stack). |
| `jarvis doctor` | Diagnose environment, git, `rg`, workspace writability, MCP and sandbox health. |
| `jarvis model-doctor` | Check inference gateway connectivity and model availability. |
| `jarvis run "task"` | Start a durable remote Run via AI Stack. |
| `jarvis cloud "task"` | Cloud execution path via AI Stack. |
| `jarvis bench` | Real-workload and efficiency benchmark entry points. |

Run `jarvis --help` for the full surface.

## Documentation

- [Real workload efficiency benchmark](docs/real-workload-efficiency.md)
- [Operations](docs/operations.md)
- [Models and routing](docs/models.md)
- [MCP](docs/mcp.md)
- [Web search](docs/web-search.md)
- [v0.8 autonomous runtime](docs/v0.8-autonomous-runtime.md)
- [World-class readiness](docs/world-class-readiness.md)

## Development

```bash
python -m pip install -e . -r requirements.txt
black --check --diff src tests
ruff check src tests --select E9,F63,F7,F82
pytest -q --cov=. --cov-report=term-missing --cov-fail-under=70
python -m build
```

### Production request path

Normal bare-task usage is **Jarvis CLI -> jarvis-inference -> model backend**. AI Stack is an optional
consumer of the same inference contract.

## Security

Jarvis runs local commands inside a fail-closed OS sandbox with network policy, deny-by-default MCP
tool approval, and secret-minimized agent subprocess environments. Repository content and tool
output are treated as untrusted evidence.

Please report suspected vulnerabilities privately through GitHub's **Report a vulnerability** flow
rather than opening a public issue.

## Contributing

Contributions are welcome: bug reports, documentation, tests and code. Before opening a change:

1. Search existing issues and pull requests.
2. Open an issue for large API or behavioral changes.
3. Keep the local-agent security stack intact (sandbox policy, approvals, proof records, redaction).

Before submitting a pull request, run the [development](#development) checks above plus the full test
suite.

## Support

Use GitHub Discussions for questions and design discussion, and GitHub Issues for reproducible bugs
and focused feature requests.

## License

Jarvis CLI is released under the [MIT License](LICENSE).
