# DECISIONS.md

## Scope and triage

Given the 6-hour cap and my own learning curve on servers/SQLite/subprocess,
I deliberately prioritised the two heaviest graded items — R2 (exactly-once
side effects) and R4 (injection resistance) — and built outward from a
working S1 loop. I chose depth on a few requirements I fully understand over
shallow coverage of all twelve scenarios I couldn't explain in a live round.

## Architecture

The runtime is split into small, single-responsibility modules:

- `agent/client.py` — the only code that talks HTTP to mockllm.
- `agent/loop.py` — the ask -> act -> report loop, step ceiling, and
  no-progress detection.
- `agent/tools.py` — the five tools plus a `run_tool` dispatcher.
- `agent/email_tool.py` — send_email with an idempotency key.
- `agent/event_log.py` — an append-only SQLite event log + resume helpers.

**Key decision: structural safety over pattern-matching.** All three trust
boundaries use the same shape — an allow-list checked before the action, not
a blocklist of "bad" inputs. File tools resolve the path with `.resolve()`
and verify it stays inside `workspace/`; `http_get` checks the host against an
allow-list; `send_email` checks the recipient against an approved set. This
is why S7's injection fails structurally: the model can ask to email an
attacker, but the recipient simply isn't approved, regardless of what any
file said.

**Rejected alternative:** scanning tool results for suspicious phrases
("ignore previous instructions") to detect injection. I rejected this because
it's evadable — any attacker who rewords the payload defeats it. An allow-list
around the irreversible tool doesn't care what the payload says.

## Exactly-once (R2)

send_email derives a SHA256 idempotency key from (to, subject, body). Before
inserting, it checks the key in SQLite; if present, it SKIPS. Combined with
the append-only event log and `resume`, a re-run after a crash replays
completed tools and any repeated email is skipped. Verified with a crash
simulation (test_crash.py): 1 SENT + 2 SKIPPED after simulated crashes ->
count == 1.

**Rejected alternative:** tracking send state purely in memory. Rejected
because memory is lost on `kill -9`; only a committed SQLite row survives.

## Three places it's still unsafe

1. **Crash mid-INSERT is unverified.** I simulate crashes by re-calling
   functions, not by killing a process mid-write. SQLite's commit atomicity
   plus the idempotency key *should* cover a real `kill -9`, but I have not
   proven it under the real chaos harness.
2. **No context budget enforcement (R3).** A large or growing response (S8)
   can blow past the 8k token ceiling; I do not compact or trim. A long run
   could fail the budget.
3. **Partial network failures unhandled (S5, S12).** I use `requests`, which
   can silently mishandle a connection reset mid-body. I did not build the
   incomplete-read detection those scenarios need.

## Compaction (not implemented — what I would do)

I did not implement compaction. If I had, I would keep the original task and
the most recent N turns verbatim, and summarise older tool results into a
short running note, preserving any fact explicitly marked important (e.g. the
turn-3 fact needed at turn 40 would be pinned rather than summarised away).

**Defended against one alternative:** a pure sliding window (drop oldest
turns). I'd reject that alone, because it silently loses early facts the
long-horizon recall task depends on — a summary-plus-pinned-facts approach
keeps them.

## With two more weeks

- Real `kill -9` chaos harness + email pending/sent state machine.
- Retry/backoff for S5/S6 using stdlib `http.client` for precise
  incomplete-read detection.
- Context compaction with pinned facts (R3).
- JSONL trace + `replay` command (R6).
- Handlers for S9, S10, S11, S12.

## Known deferred items

- Real process-kill test (relied on simulation + idempotency).
- S2, S5, S6, S8, S9, S10, S11, S12 not fully handled.
- Email-specific event logging (pending/sent) — exactly-once currently rests
  on the idempotency key alone.