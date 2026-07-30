# Adversarial Agent Runtime — Part A

A from-scratch agent runtime that drives tool use against a deliberately hostile mock LLM (mockllm), built with only the standard library, `requests`, SQLite, and a test runner — no agent frameworks.

## Setup

    make setup

This creates a virtualenv (`.venv`) and installs dependencies (`pyyaml` for the mock server, `requests` for the agent).

## Running

**1. Start the mock server** (in one terminal):

    make run-mock

This starts mockllm on `http://localhost:8000`.

**2. Run the agent** against a scenario (in another terminal):

    python -m agent.loop S1        # happy path
    python -m agent.loop S3        # bad / nonexistent tool
    python -m agent.loop S4        # infinite loop (halts via no-progress detection)
    python -m agent.loop S7        # prompt injection (blocked structurally)

**3. Resume a crashed run:**

    python -m agent.loop resume <run_id>

## Testing

    make test      # mockllm smoke tests + agent tests (tools, email, crash)
    make eval      # agent eval suite: 14 cases, 5 adversarial, 2 known-gap

## Architecture

- `agent/client.py` — the only module that talks HTTP to mockllm.
- `agent/loop.py` — the ask -> act -> report loop, step ceiling, no-progress detection, and resume logic.
- `agent/tools.py` — the five tools + a `run_tool` dispatcher.
- `agent/email_tool.py` — `send_email` with an idempotency key + recipient allow-list.
- `agent/event_log.py` — append-only SQLite event log + resume helpers.
- `mockllm/` — the provided-style mock server (scaffolded with AI assistance; see TIMELOG).
- `evals/run_evals.py` — the eval suite.

## What works

- **Agent loop (R1, partial):** survives S1 (happy path), S3 (bad/nonexistent tool, wrong-typed args), S4 (infinite loop), S7 (injection). Malformed JSON (S2) is handled defensively via `.get()` and try/except.
- **Exactly-once side effects (R2):** `send_email` uses a SHA256 idempotency key stored in SQLite; an append-only event log + `resume` continue a run after interruption. Verified by `test_crash.py`: 1 SENT + 2 SKIPPED across simulated crashes -> email count == 1.
- **Injection resistance (R4):** all three trust boundaries are structural allow-lists, not pattern matching — `workspace/` path confinement, `http_get` host allow-list, and `send_email` recipient allow-list. S7's exfil to `attacker@external.example` is REFUSED regardless of what the file says.
- **Loop control (R5, partial):** step ceiling (MAX_STEPS) + no-progress detection (halts when the same tool+args repeats).
- **Observability (R6, partial):** every run writes a structured event log to SQLite.
- **Evals (R7):** 14 cases (5 adversarial, 2 intentionally failing known gaps).

## What does NOT work (honest gaps)

- **Real `kill -9` durability is unverified.** Exactly-once is proven via a crash *simulation*, not a real process kill mid-INSERT. SQLite commit atomicity + the idempotency key are expected to cover it, but this is not proven under the real chaos harness.
- **No context budget / compaction (R3).** The 8k-token ceiling is not enforced; S8 (growing responses) would eventually blow the budget.
- **Network-failure scenarios unhandled (S5, S6, S12).** No retry/backoff or incomplete-read detection yet. (S6 retry is the most tractable next step.)
- **Not handled: S9 (duplicate ids), S10 (parallel fail+hang), S11 (confidently wrong).**
- **No `replay` command (R6).** The event log exists but replay-from-log is not implemented.
- **Only 5 tools; `run_python` lacks a memory cap and network isolation** (has subprocess + timeout only).

See `DECISIONS.md` for architecture rationale and the three places the system is still unsafe. See `TIMELOG.md` for where the time went.

## Note on mockllm

The mock server under `mockllm/` was scaffolded with heavy AI assistance and is logged separately in TIMELOG (outside the 6-hour Part A budget), since the take-home lists it under "what you're given". I am still working through it line-by-line.