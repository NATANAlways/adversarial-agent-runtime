# mockllm

A local, dependency-light stand-in for a real model API. It speaks a
subset of the Anthropic Messages API shape over plain HTTP+JSON on
`localhost` and nothing else -- no real model, no network egress, no API
key. It exists so an agent runtime can be built and tested against
adversarial model behavior (malformed output, dropped connections, rate
limits, prompt injection, lies about tool success, etc.) without ever
calling a real, billed model.

**Do not modify this directory's behavior to make your agent pass** --
that defeats the point. If you think a scenario is genuinely buggy (as
opposed to "hostile on purpose"), that's worth flagging, not silently
working around.

## Running it

```bash
pip install -r mockllm/requirements.txt
python -m mockllm.server --port 8000
# or: python mockllm/server.py --port 8000
```

`GET /health` returns `{"status": "ok", "scenarios": [...]}`.

## API contract

`POST /v1/messages` with a JSON body shaped like the real Messages API:

```json
{
  "model": "mock-claude",
  "max_tokens": 1024,
  "system": "optional system prompt",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": [{"type": "tool_use", "id": "...", "name": "...", "input": {}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "...", "content": "..."}]}
  ],
  "tools": [{"name": "read_file", "description": "...", "input_schema": {}}]
}
```

`model`, `max_tokens`, and `messages` are required; a missing field gets a
`400 invalid_request_error` with a legible message. Responses look like a
real Messages API response, plus a `usage` block computed by
[`tokenizer.py`](tokenizer.py):

```json
{
  "id": "msg_...", "type": "message", "role": "assistant", "model": "mock-claude",
  "content": [{"type": "text", "text": "..."}, {"type": "tool_use", "id": "...", "name": "...", "input": {}}],
  "stop_reason": "tool_use",
  "usage": {"input_tokens": 123, "output_tokens": 45}
}
```

Errors look like `{"type": "error", "error": {"type": "...", "message": "..."}}`
with an appropriate HTTP status.

**Streaming (`"stream": true`) is not implemented.** The take-home spec
doesn't require the agent to speak SSE, and several scenarios (S5, S12) are
about a response getting cut off mid-*transport*, which is exercised more
directly, and just as realistically, by truncating a plain JSON body than
by adding a whole second transport mode. If you want to add streaming on
top of this later, `_write_truncated` is the place the truncation logic
already lives.

## Selecting a scenario

Every request may carry an `X-Mock-Scenario` header (`S1`..`S12`,
case-insensitive). Omit it and you get `S1` (happy path).

```bash
curl -s localhost:8000/v1/messages \
  -H 'X-Mock-Scenario: S6' \
  -H 'Content-Type: application/json' \
  -d '{"model":"mock-claude","max_tokens":256,"messages":[{"role":"user","content":"go"}]}'
```

## How scenario state works

The server is stateless across restarts and needs no session ID:

- **Turn number** = count of `assistant` messages already in the posted
  `messages` array, + 1. Since the agent resends full history each call,
  the server always knows which step of the scenario it's on just by
  looking at what was sent.
- **Attempt number** = how many times this exact `(scenario, turn, last
  message)` signature has been seen. This drives retry-sequenced
  scenarios (S5, S6, S12) where the *same* logical call needs to fail a
  fixed number of times before succeeding. It's an in-memory counter
  (`server.py`'s `_attempt_counts`); `reset_state()` clears it, used by
  the test suite between scenario runs.

Each `scenarios/*.yaml` file holds the scenario's identity, a
human-readable description of the exact mechanics, and the *tunable
parameters* (file paths, tool names, filler text, timing) that its
handler function in `server.py` reads. The sequencing/HTTP-level mechanics
themselves (byte-truncation offsets, retry counting, malformed-JSON
construction) live in code, not YAML -- a fully declarative engine for
"cut the connection at byte N of a dynamically-sized JSON body" would have
cost more time than it was worth for a mock component. This is a
deliberate scope call, not an oversight.

**The mock never executes tools.** It only ever emits what a model would
say (text, `tool_use` blocks, stop reasons, HTTP failures). Tool
*execution* -- sandboxing, path confinement, subprocess timeouts,
allow-lists -- is entirely the agent's responsibility. This matters for
S10 in particular: the mock just asks for two tool calls in parallel, one
built to hang (`while True: pass`) and one built to fail (nonexistent
path); whether that's actually survivable is a property of the agent's
tool layer, not of mockllm.

## Scenario reference

| ID | What happens | What it's testing |
|----|---|---|
| S1 | One tool call, then a clean final answer. | Baseline. |
| S2 | `tool_use.input` arrives as a *string* containing broken JSON -- trailing comma (turn 1), truncated mid-object (turn 2), unescaped control char (turn 3) -- then a valid call (turn 4). | Defensive parsing; the client must never trust `input`'s shape. |
| S3 | Turn 1 calls a tool (`delete_database`) that isn't in any tool list. Turn 2 calls a real tool (`read_file`) with a wrong-typed arg (`path: 12345`). | Tool-not-found and type-validation error paths, without crashing or dispatching a call that shouldn't exist. |
| S4 | Same tool, same args, every turn, forever. `stop_reason` is always `tool_use`. | Step ceiling / no-progress detection (R5); the mock will never stop this itself. |
| S5 | First attempt at turn 1: full `Content-Length` declared, only a prefix written, then the socket is reset. Cut offset is seeded from the request signature (deterministic per conversation, so replay is reproducible). Retry succeeds. | Detecting and recovering from a genuine mid-response network failure, not just an HTTP error status. |
| S6 | Turn 1: attempt 1 -> `429` + `Retry-After`; attempt 2 -> `529`; attempt 3+ -> `200`. | Backoff/retry logic across two different failure classes. |
| S7 | Turn 1 reads a file. Turn 2 -- regardless of the file's real contents -- the model unconditionally tries to `send_email` to an unapproved address ("prompt injection succeeded on the model"). | Whether the *agent's* structural boundary around irreversible tools holds even when the model itself is fully compromised. |
| S8 | Every turn calls a tool (never `end_turn`) with response text that grows turn over turn. | Context budget (R3) under realistic cumulative growth; requires compaction to survive past a handful of turns. |
| S9 | Turn 1 and turn 2 both use `tool_use.id = "toolu_dup0001"`, for two *different* tool calls. | State keyed only by `tool_use.id` (not scoped by turn) will misattribute a result. |
| S10 | One turn, two parallel `tool_use` blocks: one designed to hang (`run_python` with `while True: pass`), one designed to fail (`read_file` on a nonexistent path). | Per-call isolation in the agent's tool-execution layer: a timeout on one call must not block or corrupt the other. |
| S11 | Turn 1 writes to a path that should be rejected by workspace confinement (`../outside_workspace.txt`). Turn 2 -- whatever the real `tool_result` said -- the model claims success. | Whether the agent's own event log records ground truth, independent of what the model narrates. |
| S12 | One turn declares 3 parallel tool calls; first attempt is cut immediately after the first `tool_use` block's JSON closes, before the 2nd/3rd block or `stop_reason` ever arrive. Retry gets the full turn. | Not treating a truncated read as "one complete call" -- an interrupted turn must be retried, not partially acted on. |

## Tokenizer

`tokenizer.py` is a pure, deterministic (not real-BPE) counter: import
`count_tokens(text)` and `count_messages_tokens(messages, system, tools)`
from both the server and your agent, so "8,000 tokens" means the same
thing on both ends of the wire. `usage.input_tokens` / `usage.output_tokens`
on every mock response are computed with it.

## Tests

```bash
pip install -r mockllm/requirements.txt
python -m unittest discover -s mockllm/tests -v
```

`tests/test_server.py` spins the real server up on an ephemeral port in a
background thread and drives all 12 scenarios end-to-end with `requests`,
asserting the mechanics described above (malformed input shapes, retry
sequences, truncated reads, duplicate ids, etc.) -- not full agent
behavior, since there's no agent here yet, just the mock it will run
against.
