# Changelog

## 0.12.7

### World-class hardening (P0.7)

- **Project `.env` is no longer auto-loaded before workspace trust (R-1)**:
  only the global files (`~/.jarvis/.env`, `$JARVIS_GLOBAL_ENV`) load at
  import; a repository's `.env` is parsed after the trust decision and only
  for a trusted workspace. `JARVIS_TRUST_WORKSPACE`, `JARVIS_SANDBOX`,
  `JARVIS_NETWORK`, `JARVIS_GLOBAL_ENV`, `INFERENCE_BASE_URL` and
  `INFERENCE_API_KEY` are always ignored from a project file, and `.env`
  participates in the trust digest (`TRUST_VERSION` 5), so committing it
  invalidates an existing grant.
- **Completion evidence gate is advisory by default (R-2)**: a run that makes
  no tool call no longer fails with "Completion evidence gate failed" and
  loses the model's answer; missing evidence is recorded as
  `completed_with_warnings`. Test proofs are only required when the task asks
  for tests/verification. `JARVIS_PROOF_GATE=strict` restores hard failure.
- **`jarvis undo` works**: the `undo` subcommand is now parsed (it was only
  documented), and non-Git workspaces keep a durable undo stack under
  `.jarvis/patches` instead of receiving patches with a false "undo is
  available" message.
- **Patch guard accepts legitimate new files**: creation requests may add new
  files anywhere inside the workspace (root `Makefile`/`hello.txt`, ...);
  `.git/`, `.jarvis/` and `.env*` remain protected.
- **`search_text` option injection (CLI-18)**: `rg` is invoked with `--`
  before the model-supplied pattern, so a pattern such as `--pre=…` is
  searched literally instead of executed.
- **Session transcripts**: failed runs no longer persist their error text as
  an assistant turn, the machine-readable `Efficiency/evidence` footer is
  stripped before it is stored, and the database (plus WAL/SHM) is created
  `0600` in a `0700` state directory.
- **`session-resume` preserves the edit mode**: read-only sessions stay
  read-only unless `--write` is passed, and `--read-only` downgrades a
  writable session. `session-fork` inherits the mode.
- **`session-resume` Ctrl-C** exits 130 without a traceback, matching `local`.
- **Sandbox `allowlist` fails loudly**: the OS sandbox cannot filter hosts, so
  the mode is rejected with an explanatory error instead of silently behaving
  like `deny`.
- **MCP Streamable HTTP**: requests advertise
  `Accept: application/json, text/event-stream`, parse SSE responses, send the
  negotiated `MCP-Protocol-Version`, and `close()` deletes the server-side
  session.
- **Numeric env defaults**: an invalid `JARVIS_MAX_STEPS`/`JARVIS_TIMEOUT`
  reports a clear error instead of a traceback.

## Unreleased

### Patch release 0.12.6

- **Python toolcache shared library discovery**: `LD_LIBRARY_PATH` now auto-discovered from GitHub Actions Python toolcache (`$TOOLCACHE/3.10.*/x64/lib`, `$TOOLCACHE/3.12.*/x64/lib`, `$TOOLCACHE/3.13.*/x64/lib`), replacing the need for `apt-get install libpythonX-dev` on self-hosted runners
- **Python runtime verification**: `libpythonX.so.1.0` existence checked before running Python; `LD_LIBRARY_PATH` set explicitly to verify subprocesses can find shared libraries
- **Workflow cleanup**: Removed redundant `"Install Python development shared libraries"` apt-get step and duplicate `"Configure Python toolcache shared libraries"` step from `.github/workflows/validate.yml`
- **Black formatting**: Applied formatting to test files for consistent code style

### World-class hardening (P0.6)

- **MCP handshake (CLI-14)**: `HTTPMCPClient` now performs the real MCP
  `initialize` handshake (protocol revision `2025-06-18`, clientInfo carrying
  the actual jarvis version), records the negotiated `protocolVersion`,
  serverInfo and capabilities, validates and tracks the `Mcp-Session-Id`
  response header (bounded, printable-ASCII), and sends it on every later
  request — real Streamable-HTTP servers rejected the old session-less
  client. The id-less `notifications/initialized` notification is sent after
  the handshake. stdio `initialize` validates the result object and records
  the negotiated protocol version instead of blindly proceeding. HTTP
  permission/approval enforcement is unchanged. HTTP error responses now
  surface the server's bounded JSON-RPC error message.
- **SIGTERM durability (CLI-15)**: `jarvis local` and `session-resume` now
  install the SIGTERM/SIGHUP → KeyboardInterrupt conversion. A terminated run
  writes its trace and marks the session `failed` instead of leaving a zombie
  `running` session behind, and exits with the script-friendly code 130.
- **Patch approval shows the diff (CLI-12)**: the approval prompt now embeds
  the exact patch that would be applied (bounded at 8,000 characters with an
  explicit truncation marker) — approving is no longer blind.
- **Undo patch stack (CLI-12)**: every applied patch is kept under
  `git rev-parse --git-path jarvis-patches` as a numbered stack (`001.patch`,
  newest index last). `jarvis undo` reverses and pops the newest patch and
  reports how many earlier patches remain undoable; a follow-up `jarvis undo`
  walks further back. Legacy workspaces holding a single `jarvis-last.patch`
  still undo once (backward compatible), and the unsafe-undo guard is
  unchanged.
- **Identity-scoped dedupe (CLI-18)**: tool-result dedupe (evidence and
  efficiency layers) now keys its digest on the tool call identity (tool name
  + arguments) as well as the result text, so two `read_file` calls on
  different same-content files are no longer collapsed — the second path is
  no longer hidden from the model.
- **Routing cleanup (CLI-19)**: the removed AI Stack run-management words
  (`run`, `list`, `show`, `resume`, `approve`, `discard`, `cancel`,
  `projects`, `workspaces`, `doctor`) were dropped from `CLI_COMMANDS` and
  their dead subparsers and error block deleted; a bare task starting with one
  of those words now routes to the local agent instead of dying with the
  misleading "AI Stack remote commands have been removed" error. The unused
  top-level `--continue` flag is gone, and `local` regained the
  `--write/--allow-edits` and `--detach` flags (with `argparse.SUPPRESS`
  defaults so subparser defaults cannot clobber top-level values).
- Fixed a flaky `test_resolve_local_config_requires_endpoint_and_key` that
  leaked `INFERENCE_BASE_URL`/`INFERENCE_API_KEY` from ambient env.
- New test battery `tests/test_p06_world_class.py`: 13 tests including a
  scripted Streamable-HTTP server double, a real stdio MCP server, real
  SIGTERM delivery, and git-backed patch-stack undo tests.

## 0.12.5

### Agent loop hardening

- `jarvis local` / `session-resume` runs now honor a run-scoped wall-clock
  deadline (`JARVIS_RUN_TIMEOUT_SECONDS`, default 3600, `0` disables). When it
  expires between steps the run stops with a deterministic status summary
  (completed tool sequence, applied patches, undo advice) instead of continuing
  for hours. `--timeout` / `JARVIS_TIMEOUT` continue to bound a single model
  call only — the README now spells out that distinction.
- The previously undocumented 100-step hard cap on `--max-steps` is documented
  and env-overridable via `JARVIS_MAX_STEPS_CAP` (minimum 1).
- `session-resume` refuses sessions still marked `running` (they belong to a
  live or SIGKILLed process; silently resuming them would duplicate the run
  and interleave two writers into one transcript). Re-run with the new
  `--force` flag to resume anyway. Session id prefix shorthand now requires an
  unambiguous match: exact id first, and an ambiguous prefix raises an error
  listing the matching sessions instead of silently resuming the most recent
  one.

## 0.12.4

### Platform runtime & secrets (security)

- The platform runtime (permission/proof stack, MCP approval enforcement,
  secret-scrubbed subprocess environment, telemetry) now installs for every
  code-path that reaches the agent loop: bare task invocations
  (`jarvis "task"`) and `session-resume` included — previously it was gated on
  the literal `local`/`plan`/`tui` spelling of `argv[0]`.
- The base `LocalTools` command runner now runs every agent subprocess under
  the credential-scrubbed environment (`sanitized_subprocess_env()`), so model
  or provider secrets such as `INFERENCE_API_KEY` never leak into child
  processes even without the platform runtime override.
- Project sandbox policy (`.jarvis/sandbox.toml`) is now trust-gated executable
  configuration and part of the workspace trust digest (trust registry v4): a
  hostile repository can no longer disable OS isolation by committing a
  `sandbox.toml` with `mode="off"`, and committing one invalidates an existing
  trust grant. `JARVIS_SANDBOX` / `JARVIS_NETWORK` remain operator controls.

### Agent loop correctness

- `run_command` / `apply_patch` idempotency is now scoped to the loop step:
  a later legitimate replay (running pytest again after fixing tests with the
  same argv) executes fresh instead of returning the stale first result,
  while same-step crash replays still dedupe.
- Interrupted runs (including `KeyboardInterrupt` mid-tool) backfill explicit
  synthetic tool results before the transcript is checkpointed, so sessions
  can no longer end with dangling `tool_calls` that made `session-resume`
  fail with HTTP 400 forever.
- `provider_messages.to_openai()` performs a repair pass that closes any
  unanswered tool calls with an interruption notice, keeping persisted
  transcripts protocol-valid in all cases (including the verifier's
  `submit_verdict` early return).
- Session checkpoints are transactional: the DELETE and every INSERT share
  one transaction, so a crash can no longer truncate the transcript.
- The `.env` loader strips one matching pair of surrounding quotes and
  accepts an `export KEY=value` prefix, so a quoted `INFERENCE_API_KEY`
  no longer silently breaks authentication.
- `patch_guard` no longer launders `../` traversal via `lstrip("./")`:
  only a literal leading `./` is stripped, and absolute paths / parent
  traversal are rejected outright.
- Budget-stop reports list patched filenames recovered from `apply_patch`
  patch text ("Patches were applied to:" is no longer empty).
- `list_files` announces truncation at the 500-entry cap; `read_file`
  answers out-of-range windows with corrective guidance instead of an
  empty response.
- `model-doctor --full-agent` is documented again and implemented: one real
  agent turn runs through the complete loop when you ask for it.

### Metadata

- `jarvis-agent-core` dependency pin moves to 0.17.4 (Core reservation,
  retry-bound, and tool-call decoding fixes).
- README/ROADMAP drift corrected: documented step/token defaults (30 steps,
  48,000/24,000 tokens), version notices, and the honest per-hunk review
  status (single-patch undo is PARTIAL).

## 0.12.3

- `JARVIS_MAX_STEPS` and `JARVIS_TIMEOUT` environment variables now control the local agent's step limit and timeout defaults respectively, with hardcoded defaults of 30 steps and 180 seconds when not set.
- Support global `.env` config via `~/.jarvis/.env` and `$JARVIS_GLOBAL_ENV`.
  `jarvis local` now auto-loads environment variables from three sources in
  priority order: project-local `.env` in the current working directory,
  `~/.jarvis/.env` as a user-level fallback, and `$JARVIS_GLOBAL_ENV` as a
  custom file path. Process-environment variables always take precedence over
  all CWD/global values, allowing explicit overrides.
- All other 0.12.2 changes remain in effect.

## 0.12.2

- Lean local harness: the v0.7 heavy stack (structural task enrichment,
  dynamic multi-agent escalation, failure escalation passes) is now opt-in
  via `JARVIS_ADAPTIVE_AGENTS=true` / `JARVIS_ESCALATE_ON_FAILURE=true`.
  Small local models (qwen3 4b/8b) drowned in the enriched-task context
  and burned whole runs on failed research instead of acting; default runs
  now pass the task through lean with the minimal system prompt. Evidence
  footers are still recorded either way.
- Control Qwen3-family reasoning mode: the agent now passes an explicit `think`
  flag to the gateway (`JARVIS_THINK` env, default `false`). Thinking mode on CPU
  burned thousands of reasoning tokens per turn with no answer bit emitted; the
  default now yields immediate answers and a large effective speedup.
- Validate tool-call arguments against each tool's JSON schema before execution
  (`validate_tool_arguments`), so missing required keys or wrong value types fail
  fast with a schema-specific message into the existing recovery path instead of
  reaching the filesystem or shell mid-call.
- Token-budget exhaustion no longer crashes the run with a `BudgetExceeded`
  traceback: both the reservation and commit paths are caught and the agent ends
  with a deterministic stop summary (completed tools, patched files, and how to
  raise `JARVIS_MAX_OUTPUT_TOKENS` / `JARVIS_MAX_INPUT_TOKENS`).
- `run_command` denials are corrective instead of bare: shell wrappers
  (`sh`/`bash`/`sudo`/`eval`) point the model at `apply_patch` rather than shell
  redirection, and allowlist denials enumerate the allowed programs. Small local
  models previously looped on identical denials for entire runs.
- Rebuilt development environments result in a working out-of-the-box CLI.

## 0.11.4

- Consume the published `jarvis-agent-core==0.17.3` release, including bounded retries for explicit pre-admission inference queue rejections while preventing replay after ambiguous generation timeouts or partial streams.
- Align dependency and version assertions across packaging, CI and release documentation.


## 0.11.3

- Remove AI Stack remote command execution from the Jarvis CLI; Jarvis and AI Stack are independent consumers of jarvis-inference.
- Make `model-doctor` always test the configured inference gateway directly and require `INFERENCE_API_KEY`, never `AI_STACK_API_KEY`.
- Normalize OpenAI-compatible tool-call arguments whether gateways return JSON strings or already-decoded objects; improve malformed-call diagnostics.
- Default direct local inference to the concrete `qwen3:1.7b` model and reject external provider profiles/endpoints.
- Add regression coverage for inference-only diagnostics and tool-call normalization.

## 0.11.2

- Consume the published `jarvis-agent-core==0.17.2` release, including the shared fix that prevents ambiguous inference timeouts from being retried as if they were safe failures.

- Lower standalone agent defaults to 20 steps, 16,000 input tokens and 6,000 output tokens; retain environment and CLI overrides.
- Make adaptive multi-agent execution opt-in by default while preserving explicit `--multi-agent` and `JARVIS_MULTI_AGENT` overrides.
- Do not start a recovery model turn after an ambiguous inference timeout, avoiding duplicate work on the shared single-generation queue.
- Keep recovery bounded and avoid retrying ambiguous inference timeouts at the CLI layer.


## 0.11.1

- Pin the published `jarvis-agent-core==0.17.1` release, including the shared inference timeout/retry and stream-cancellation fixes.
- Align release, installation and architecture documentation with the inference HTTP contract: fail-closed authentication and no replay of ambiguous generation timeouts, without requiring a published gateway release for source-based deployment.
- Keep the CLI local-first and AI Stack optional.


## 0.11.0

- Make bare-task invocations use the standalone local agent and direct model endpoint by default.
- Keep AI Stack available through explicit `jarvis run` and `jarvis cloud` commands for durable remote execution.
- Make `jarvis model-doctor` probe the dedicated inference gateway when `INFERENCE_BASE_URL` is configured.
- Document repository ownership boundaries and the optional AI Stack integration.
- Bump the CLI to 0.11.0 and pin the shared inference transport to the published provider-neutral Jarvis Core 0.17.0 release.
- Route OpenAI-compatible chat, tool calls, and request configuration through `jarvis_core.InferenceClient`; keep the native Anthropic path separate.
- Align install, architecture, configuration, and release documentation with direct local inference and optional explicit AI Stack Runs.


## 0.10.8

- Harden `jarvis model-doctor` with layered AI Stack -> inference diagnostics.
- Add an opt-in `--full-agent` check for the complete `/chat` path while keeping the default doctor fast and isolated.
- Propagate the configured doctor timeout and validate concrete model selection through AI Stack.
- Add regression coverage for direct inference probing and URL-encoded model identifiers.


## 0.10.7

- Send an explicit `jarvis-agent-cli/<version>` User-Agent on every HTTP request so protected Cloudflare API traffic is not mistaken for Python automation.
- Keep Cloudflare Access service-token authentication and the AI Stack API boundary unchanged.

## 0.10.6

- Fix `jarvis model-doctor` to query AI Stack's `/models/available` model catalog instead of the inference-only `/v1/models` endpoint.
- Keep the Jarvis -> AI Stack -> jarvis-inference API boundary explicit.


## 0.10.5

- Send Cloudflare Access service-token credentials on AI Stack HTTPS requests when configured.
- Reject incomplete Cloudflare Access credentials instead of sending partially authenticated requests.
- Add regression coverage for Cloudflare Access authentication and prevent service-token leakage to HTTP endpoints.


## 0.10.4

- Make AI Stack the default control plane for normal bare-command and server-backed Jarvis work.
- Route normal inference through AI Stack -> jarvis-inference; keep direct model access explicitly local/diagnostic.
- Make `jarvis model-doctor` validate the end-to-end AI Stack model path and advertised concrete model ID.
- Add regression coverage for bare-command routing and the current AI Stack architecture.
- Align installation and model documentation with the production service boundary.

## 0.10.3

- Make AI Stack the primary control plane for normal Jarvis server-backed work.
- Use the dedicated inference gateway only behind AI Stack for normal operation.

## 0.10.2

- Send concrete model IDs to AI Stack instead of the removed `orchestrator` selector.
- Default the AI Stack integration to `qwen3:1.7b`, while allowing `JARVIS_MODEL` to override it.
- Align CLI tests with the concrete model-selector contract.


## 0.10.1

- Release the Cloudflare-compatible model request header fix.
- Publish the merged distributable CLI fixes as a patch release.


## 0.10.0

- Make Jarvis a first-class distributable application with PyPI and standalone executable distribution.
- Pin the CLI to the immutable Jarvis Core 0.16.1 release.
- Add release validation, clean-wheel installation, standalone binaries, SBOMs, checksums and provenance attestations.
- Publish PyPI artifacts through GitHub Actions Trusted Publishing using the existing `pypi` environment.


## 0.9.7

- Consume the published Jarvis Core 0.16.0 empirical calibration release.
- Add the real Jarvis workload efficiency benchmark corpus and task-level evaluation guidance.
- Align dependency, CI and clean-wheel validation with Core 0.16.0.
- Document the Jarvis -> AI Stack -> provider/model ownership boundary for empirical routing evidence.

## 0.9.6

- Consume the published Jarvis Core 0.15.0 common-brain release.
- Align dependency, CI and clean-wheel validation with Core 0.15.0.
- Document Core 0.15.0 token-efficiency primitives and their provider-neutral boundary.
- Refresh release documentation and package metadata for the 0.9.6 patch release.

## 0.9.5

- Consume the published Jarvis Core 0.14.0 execution-maturity release.
- Add nonblocking background process support with approval/allowlist controls.
- Persist execution evidence records and lifecycle observations.

## 0.9.4

- Consume the published Jarvis Core 0.13.0 common-brain release.
- Use the shared Core sandbox-requirements contract while retaining native OS sandbox enforcement in the CLI/runtime layer.
- Align release and clean-install validation with Core 0.13.0.
- Refresh release documentation and package metadata for the 0.9.4 patch release.

## 0.9.3

- Consume the published Jarvis Core 0.12.0 release.
- Use the Core provider normalization API as the canonical model-boundary vocabulary for new provider integrations.
- Align release and clean-install validation with Core 0.12.0.
- Refresh release documentation and package metadata for the 0.9.3 patch release.

## 0.9.2

- Align the CLI with the published Jarvis Core 0.11.0 provider-neutral contract line.
- Document the Core `ModelProvider`, `ModelRequest`, `ModelResponse`, `ModelUsage`, and `ToolCall` boundary while keeping concrete provider integrations in the CLI/runtime layer.

## 0.9.1

- Pin the CLI to the immutable Jarvis Core 0.9.2 release wheel.
- Apply repository-wide Black formatting and keep workspace-trust Hook tests isolated.
- Preserve independent consumers of the shared Core contracts.

## 0.8.1 audit hardening

### Correctness and release alignment

- Pin the CLI to the verified immutable Core release artifact.
- Make public Python SDK `RemoteJarvis` and `CloudWorker` resolve to the idempotent/fenced implementations while retaining explicit legacy aliases.
- Make release tag/version inspection dependency-free.
- Add release-alignment and clean-wheel regressions.

### Security and trust

- Add an explicit user-owned workspace trust registry and trust controls.
- Do not load project-local executable Hooks until the exact workspace is trusted.
- Enforce MCP approval before a configured tool call is sent.
- Harden stdio MCP lifecycle concurrency and prevent stderr-pipe deadlocks.
- Parse MCP HTTP endpoints structurally and bound responses.
- Remove credential-like variables and credential-bearing URLs from agent-run command environments by default.
- Respect `XDG_CONFIG_HOME` for user Hook configuration.

### Quality and documentation

- Add focused trust/MCP/secret-isolation regressions.
- Rebaseline the roadmap using FOUNDATION / INTEGRATED / VALIDATED / MEASURED / PRODUCTION-READY.
- Add readiness analysis covering real-repository benchmarks, red-team evaluation, chaos testing, cloud isolation, IDE/PR integration, background processes, checkpoints, live steering and enterprise controls.

## 0.8.0

- Add lease-fenced autonomous cloud workers and portable Git task execution.
- Add idempotent cloud submissions, cancellation, model/profile propagation and provider credential isolation.
- Add execution proof, deterministic allow/ask/deny permissions, autonomous dashboard, process-tree cancellation and conventional cron semantics.

## 0.7.x

- Add structural context compilation, bounded speculation, failure-driven escalation, verifier isolation, evidence-derived confidence, failure memory, impact-aware verification, semantic patch scope and tool-result deduplication.
- Harden local jobs, worktree dependency integration, LSP concurrency and portable cloud Git workspaces.

## 0.6.x

- Add agent teams, browser verification, plugins, durable jobs/schedules, telemetry/calibration, Python SDK, reviewed remote Runs and cloud-worker leases.

## 0.5.x

- Add persistent repository/LSP intelligence, plan mode, sandbox/network policy, terminal TUI, Skills and lifecycle Hooks.

## 0.4.x

- Add adaptive quality/risk analysis, heterogeneous routing, multi-agent execution, worktrees and execution-backed completion evidence.

## 0.3.x

- Add protocol-safe local session continuation, provider fallback/resilience, multimodal messages, persistent policy-controlled MCP, hierarchical instructions/memory and hardened distribution flows.

## 0.1.0

- Launch the standalone `jarvis` coding-agent CLI with guarded repository tools, open/local provider support, token budgets, context compaction, selective multi-agent verification and web/repository evidence.
