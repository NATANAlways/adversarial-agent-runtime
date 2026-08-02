# Adversarial Agent Runtime — Part A

A from-scratch agent runtime that drives tool use against a deliberately hostile mock LLM (mockllm), built with only the standard library, `requests`, SQLite, and a test runner — no agent frameworks.

## Setup

    make setup

Creates a virtualenv (`.venv`) and installs dependencies (`pyyaml` for the mock server, `requests` for the agent).

## Running

Start the mock server in one terminal:

    make run-mock

Run the agent against a scenario in another:

    python -m agent.loop S1        # happy path
    python -m agent.loop S6        # 429/529 retry with backoff
    python -m agent.loop S7        # prompt injection (blocked structurally)
    python -m agent.loop S8        # context growth (compaction kicks in)
    python -m agent.loop S10       # parallel tool calls (fail + hang)

Resume a crashed run, replay one, or export its JSONL trace (no server needed):

    python -m agent.loop resume <run_id>
    python -m agent.loop replay <run_id>
    python -m agent.loop export <run_id>   # dump a JSONL trace of a run

## Testing

    make test      # mockllm smoke tests + agent tests (tools, email, crash)
    make eval      # agent eval suite: 17 cases, 7 adversarial, 2 known-gap

Run individual test files directly:

    python test_tools.py    # the five tools + safety boundaries
    python test_email.py    # send_email idempotency
    python test_crash.py    # exactly-once email across a simulated crash

## Architecture

- `agent/client.py` — the only module that talks HTTP to mockllm; owns retry/backoff.
- `agent/loop.py` — the ask -> act -> report loop: step ceiling, no-progress detection, token + cost budgets, compaction, resume, replay, and JSONL export.
- `agent/tools.py` — the five tools + a `run_tool` dispatcher.
- `agent/email_tool.py` — `send_email` with an idempotency key + recipient allow-list.
- `agent/event_log.py` — append-only SQLite event log + resume/replay/export helpers.
- `evals/run_evals.py` — the eval suite.

## What works

- **Agent loop (R1):** handles all 12 scenarios — S1 (happy path), S2 (malformed JSON, repaired), S3 (bad/unknown tool), S4 (infinite loop), S5 (connection reset, retried), S6 (429/529 retry), S7 (injection), S8 (context growth + compaction), S9 (duplicate ids), S10 (parallel fail+hang), S11 (confidently wrong), S12 (interrupted turn: reset + parallel). Never crashes on a tool error or an unreachable server.
- **Exactly-once (R2):** `send_email` uses a SHA256 idempotency key in SQLite; an append-only event log + `resume` continue a run after interruption. Verified by `test_crash.py`: 1 SENT + 2 SKIPPED -> count == 1.
- **Context budget + compaction (R3):** counts tokens each step via the mock tokenizer; compacts at 6k (keeps task + recent, summarizes middle); enforces the 8k ceiling. Verified on S8.
- **Injection resistance (R4):** three structural allow-lists — `workspace/` path confinement, `http_get` host, `send_email` recipient. S7's exfil is REFUSED regardless of file contents.
- **Loop + budget control (R5):** step ceiling, no-progress detection, token budget, simulated cost budget ($0.20 cap), graceful stop with a legible reason.
- **Observability + replay (R6):** structured SQLite event log; `resume` continues a run, `replay` reproduces the transcript (no server, no tool re-execution), `export` dumps a JSONL trace.
- **Evals (R7):** 17 cases (7 adversarial, 2 intentionally failing known gaps).

## What does NOT work (honest gaps)

- **Connection-reset retry re-issues the whole request.** If a tool already ran server-side before the reset, retrying re-calls it; for irreversible tools only the idempotency key protects exactly-once.
- **Real `kill -9` durability is unverified.** Exactly-once is proven via a crash *simulation*, not a real process kill mid-INSERT.
- **Compaction is generic, not fact-preserving.** The long-horizon recall task (turn-3 fact needed at turn-40) would not reliably pass; pinning facts is the next step.
- **`run_python` lacks a memory cap and network isolation** (subprocess + 5s timeout only).
- **Failed-tool detection is string-based** ("ERROR"/"REFUSED", case-insensitive) — brittle; a structured `{"ok": False}` return would be better.

See `DECISIONS.md` for architecture rationale and the places the system is still unsafe. See `TIMELOG.md` for where the time went.

## Note on mockllm

The mock server under `mockllm/` was scaffolded with heavy AI assistance.