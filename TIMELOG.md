## Part A (6-hour cap starts here)

| Date | Task | Duration | Notes |
|---|---|---|---|
| 2026-07-27, ~22:10-22:30 IST | Scaffolded mockllm/ with heavy AI assistance: server.py, tokenizer.py, 12 scenarios, README, smoke tests. NOTE: AI-generated; still working through understanding it line-by-line before relying on it. | ~20 min |
| 2026-07-29 IST | Built agent/client.py — HTTP client to mockllm (POST /v1/messages, X-Mock-Scenario header, model/max_tokens/messages body) | ~20 min | Used requests (simple, understood) rather than http.client for now |
| 2026-07-29 IST | Built agent/loop.py — core ask->act->report loop, MAX_STEPS ceiling, tool_use detection, feeds tool_result back into conversation. Tools stubbed for now | ~20 min | Verified against S1 happy path end-to-end |
| 2026-07-29 IST | Built agent/tools.py — read_file + write_file confined to workspace/ with _safe_path() (.resolve() + is_relative_to path-traversal defense). Verified reads, writes, and ../ escape refusal | ~10|
| 2026-07-29 IST | Built agent/email_tool.py — send_email with SHA256 idempotency key + SQLite dedup (SENT once, subsequent identical sends SKIPPED). Learned SQLite basics (connect/commit/persistence) first | ~10 min |
| 2026-07-29 IST | Wired real tools into loop via run_tool dispatcher (read/write/http_get/send_email); unknown-tool + bad-arg defenses (S2/S3). Verified end-to-end on S1 with real file content | ~10 min |
| 2026-07-29 IST | No-progress detection (R5): track tool+args signature across steps, halt on repeat before MAX_STEPS. Tested on S4 (halts in ~3 steps) | ~15 min |
| 2026-07-29 IST | run_python tool: model code in isolated subprocess with 5s timeout; wired into dispatcher. Learned subprocess basics. Tested normal code + infinite-loop timeout | ~15 min |
| 2026-07-29 IST | Injection resistance (R4): recipient allow-list on send_email. Reproduced S7 exfil (SENT -> failure), added APPROVED_RECIPIENTS boundary, re-tested (REFUSED). Structural, not pattern-matching | ~15 min |
| 2026-07-30 IST | Event log (R2/R6): append-only SQLite log, commit-per-event, get_completed_tools() + run_exists(). Learned SQLite persistence via standalone test first | ~20 min |
| 2026-07-30 IST | Resume (R2): logged every step in loop; resume_agent() rebuilds conversation from completed tools, continues same run_id. Tested resume on prior run | ~25 min |
| 2026-07-30 IST | Crash test (R2, grading #1): test_crash.py simulates crash+resume, asserts send_email exactly once (1 SENT + 2 SKIPPED). Real kill -9 harness deferred | ~15 min |
| 2026-07-30 IST | Eval suite (R7): 14 cases (5 adversarial, 2 known-gap). Debugged 2 false-negative checks (string-match brittleness: 'OK' vs 'Ok', 'timed out' vs 'timeout') | ~20 min |
| 2026-07-30 IST | DECISIONS.md draft (R8): architecture, structural-safety rationale, 3 unsafe places, compaction plan, deferred items | ~15 min |