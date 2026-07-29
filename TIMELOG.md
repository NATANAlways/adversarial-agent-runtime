## Part A (6-hour cap starts here)

| Date | Task | Duration | Notes |
|---|---|---|---|
| 2026-07-27, ~22:10-22:30 IST | Scaffolded mockllm/ with heavy AI assistance: server.py, tokenizer.py, 12 scenarios, README, smoke tests. NOTE: AI-generated; still working through understanding it line-by-line before relying on it. | ~20 min |
| 2026-07-29 IST | Built agent/client.py — HTTP client to mockllm (POST /v1/messages, X-Mock-Scenario header, model/max_tokens/messages body) | ~20 min | Used requests (simple, understood) rather than http.client for now |
| 2026-07-29 IST | Built agent/loop.py — core ask->act->report loop, MAX_STEPS ceiling, tool_use detection, feeds tool_result back into conversation. Tools stubbed for now | ~20 min | Verified against S1 happy path end-to-end |