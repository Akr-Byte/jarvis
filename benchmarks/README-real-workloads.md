# Real workload benchmark corpus

This benchmark corpus evaluates the Jarvis local agent and routing behavior against realistic,
repository-scale work rather than synthetic fixtures alone.

## Scope

The v0.9 real-workload corpus covers:

- **CI triage** — diagnose failing CI jobs and propose the smallest safe fix.
- **Provider architecture** — review provider routing architecture and identify unnecessary cloud
  inference.
- **Release readiness** — review release readiness, version alignment, packaging and CI evidence.
- **PR review** — review a pull request for correctness, regressions, tests and documentation.
- **Documentation alignment** — align README, changelog and package documentation with the current
  implementation.
- **Efficiency** — measure token, latency and cost behavior of local routes.

Earlier corpora add deeper coverage of repository understanding, bug fixing, adversarial inputs and
pinned real repositories (see the JSON files in this directory).

## What is compared

Use the corpus to compare:

- **local-only** — the standalone Jarvis local agent route;
- **automatic** — the adaptive / expert-routed route enabled by configuration;
- **cloud-first** — explicit stronger-model routing where permitted.

Metrics collected per case include success, quality, incorrect completions, tool failures, latency,
input/output/cache tokens and estimated cost.

## Evidence rules

Runtime evidence should only influence automatic routing after the Core minimum-sample and quality-floor
safeguards are satisfied. Retained evidence is required before any routing decision is treated as
measured rather than assumed.

## Layout

- `v0.5-core.json` — core repository-understanding and small bug-fix cases.
- `v0.7-adversarial.json` — adversarial cases (hallucinated files/APIs, untrusted inputs).
- `v0.8.2-adversarial-security.json` — prompt-injection and secret-canary regression corpus.
- `v0.8.2-real-repositories.json` — pinned real-repository cases with exact revisions and verification
  commands.
- `v0.9-real-workloads.json` — the current real-workload category set.

## Running

Load a corpus file, run the listed task against a pinned checkout (for real-repository cases), and
evaluate results against the expected/forbidden content and verification commands.

See the Jarvis documentation entry point [Real workload efficiency benchmark](../docs/real-workload-efficiency.md)
for the full workflow.
