## Part A (6-hour cap starts here)

| Date | Task | Duration | Notes |
|---|---|---|---|
| 2026-07-27, ~22:10-22:30 IST | Scaffolded mockllm/ with heavy AI assistance: server.py, tokenizer.py, 12 scenarios, README, smoke tests. NOTE: AI-generated; still working through understanding it line-by-line before relying on it. | ~20 min |
| 2026-07-29 IST | Built agent/client.py — HTTP client to mockllm (POST /v1/messages, X-Mock-Scenario header, model/max_tokens/messages body) | ~20 min | Used requests (simple, understood) rather than http.client for now |
| 2026-07-29 IST | Built agent/loop.py — core ask->act->report loop, MAX_STEPS ceiling, tool_use detection, feeds tool_result back into conversation. Tools stubbed for now | ~20 min | Verified against S1 happy path end-to-end |
| 2026-07-29 IST | Built agent/tools.py — read_file + write_file confined to workspace/ with _safe_path() (.resolve() + is_relative_to path-traversal defense). Verified reads, writes, and ../ escape refusal | ~10|
| 2026-07-29 IST | Built agent/email_tool.py — send_email with SHA256 idempotency key + SQLite dedup (SENT once, subsequent identical sends SKIPPED). Learned SQLite basics (connect/commit/persistence) first | ~10 min |
| 2026-07-29 IST | Wired real tools into loop via run_tool dispatcher (read/write/http_get/send_email); unknown-tool + bad-arg defenses (S2/S3). Verified end-to-end on S1 with real file content | ~10 min |