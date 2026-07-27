"""Mock LLM server: shaped like the Anthropic Messages API (POST /v1/messages),
driven by scenario YAML files under scenarios/. It stands in for a real model
API and is deliberately hostile -- see scenarios/*.yaml and README.md for what
each of S1-S12 does and why.

Run it directly:
    python -m mockllm.server --port 8000

Select a scenario per-request with the `X-Mock-Scenario` header, e.g.
`X-Mock-Scenario: S6`. Defaults to S1 (happy path) if omitted.

Design notes (see mockllm/README.md for the full write-up):
  * The server never executes tools itself. It only ever emits the messages
    a model would emit (text / tool_use blocks, stop reasons, HTTP-level
    failures). Tool *execution* -- and therefore sandboxing, timeouts, path
    confinement, allow-lists -- is entirely the agent's job.
  * "Turn number" for a conversation is derived from the request itself
    (count of assistant messages in `messages`, +1), so the server needs no
    session/cookie state to know which step of a scenario it's on.
  * "Attempt number" tracks retries of the *same* logical call (same
    scenario + turn + last message), used to drive scenarios that need a
    request to fail N times before succeeding (S5, S6, S12). This is kept
    in an in-memory dict; state is not durable across server restarts, and
    doesn't need to be -- IDs are irrelevant to the agent's own replay-from-
    events durability story (R2/R6), which is the agent's problem to solve,
    not the mock model's.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import yaml

try:
    from .tokenizer import count_messages_tokens, count_tokens
except ImportError:  # running as a plain script, not as a package
    from tokenizer import count_messages_tokens, count_tokens

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


def load_scenarios() -> dict[str, dict]:
    scenarios: dict[str, dict] = {}
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        scenarios[data["id"]] = data
    return scenarios


SCENARIOS = load_scenarios()

# ---------------------------------------------------------------------------
# Retry/attempt bookkeeping (in-memory, per-process)
# ---------------------------------------------------------------------------
_attempt_counts: dict[str, int] = {}
_attempt_lock = threading.Lock()


def _signature(scenario_id: str, turn: int, messages: list[dict]) -> str:
    h = hashlib.sha256()
    h.update(scenario_id.encode())
    h.update(str(turn).encode())
    if messages:
        h.update(json.dumps(messages[-1], sort_keys=True, default=str).encode())
    return h.hexdigest()


def _next_attempt(sig: str) -> int:
    with _attempt_lock:
        _attempt_counts[sig] = _attempt_counts.get(sig, 0) + 1
        return _attempt_counts[sig]


def reset_state() -> None:
    """Used by tests to get a clean slate between scenario runs."""
    with _attempt_lock:
        _attempt_counts.clear()


def _pseudo_random_fraction(seed: str, lo: float, hi: float) -> float:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    frac = (int(digest, 16) % 10_000) / 10_000.0
    return lo + frac * (hi - lo)


# ---------------------------------------------------------------------------
# Message-building helpers
# ---------------------------------------------------------------------------
def gen_id(prefix: str = "toolu") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def tool_use_block(id_: str, name: str, input_: Any) -> dict:
    return {"type": "tool_use", "id": id_, "name": name, "input": input_}


def make_message(content: list[dict], stop_reason: str, model: str) -> dict:
    return {
        "id": f"msg_{uuid.uuid4().hex[:16]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
    }


def _last_tool_result_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                inner = block.get("content")
                if isinstance(inner, str):
                    return inner
                if isinstance(inner, list):
                    for b in inner:
                        if isinstance(b, dict) and b.get("type") == "text":
                            return b.get("text", "")
    return ""


def _json(body: dict, status: int = 200, headers: Optional[dict] = None) -> dict:
    return {"kind": "json", "status": status, "body": body, "headers": headers or {}}


# ---------------------------------------------------------------------------
# Scenario handlers: (turn, attempt, messages, req, params, sig) -> result dict
# ---------------------------------------------------------------------------
def handle_s1(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    if turn == 1:
        content = [
            text_block(params.get("intro_text", "I'll check that file for you.")),
            tool_use_block(gen_id(), params["tool_name"], params["tool_input"]),
        ]
        return _json(make_message(content, "tool_use", model))
    result_text = _last_tool_result_text(messages)
    content = [text_block(f"Based on the file, here's what I found: {result_text[:300]}")]
    return _json(make_message(content, "end_turn", model))


def handle_s2(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    tool_name = params.get("tool_name", "write_file")
    if turn >= 5:
        return _json(make_message([text_block("All set.")], "end_turn", model))
    if turn == 4:
        content = [tool_use_block(gen_id(), tool_name, params.get("valid_input", {}))]
        return _json(make_message(content, "tool_use", model))
    if turn == 1:
        broken = '{"path": "out.txt",}'  # trailing comma
    elif turn == 2:
        broken = '{"path": "out.tx'  # truncated mid-object
    else:  # turn == 3
        broken = '{"path": "out.txt", "content": "line1' + "\n" + 'line2"}'  # unescaped control char
    content = [
        text_block("Writing the file now."),
        {"type": "tool_use", "id": gen_id(), "name": tool_name, "input": broken},
    ]
    return _json(make_message(content, "tool_use", model))


def handle_s3(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    if turn == 1:
        c = params["nonexistent_tool"]
        content = [tool_use_block(gen_id(), c["name"], c["input"])]
        return _json(make_message(content, "tool_use", model))
    if turn == 2:
        c = params["wrong_typed_tool"]
        content = [tool_use_block(gen_id(), c["name"], c["input"])]
        return _json(make_message(content, "tool_use", model))
    return _json(make_message([text_block("Understood, moving on.")], "end_turn", model))


def handle_s4(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    content = [tool_use_block(gen_id(), params["tool_name"], params["tool_input"])]
    return _json(make_message(content, "tool_use", model))


def handle_s5(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    content = [
        text_block("Reading now."),
        tool_use_block(gen_id(), params["tool_name"], params["tool_input"]),
    ]
    body = make_message(content, "tool_use", model)
    if turn == 1 and attempt == 1:
        frac = _pseudo_random_fraction(
            sig, params.get("min_cut_fraction", 0.1), params.get("max_cut_fraction", 0.9)
        )
        return {"kind": "truncate", "body": body, "cut_fraction": frac}
    return _json(body)


def handle_s6(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    if turn == 1:
        if attempt == 1:
            return {
                "kind": "error",
                "status": 429,
                "error_type": "rate_limit_error",
                "message": "Rate limit exceeded. Retry after backoff.",
                "headers": {"Retry-After": str(params.get("retry_after_seconds", 1))},
            }
        if attempt == 2:
            return {
                "kind": "error",
                "status": 529,
                "error_type": "overloaded_error",
                "message": "The server is temporarily overloaded.",
            }
        content = [
            text_block("Thanks for your patience -- continuing now."),
            tool_use_block(gen_id(), params["tool_name"], params["tool_input"]),
        ]
        return _json(make_message(content, "tool_use", model))
    return _json(make_message([text_block("All done.")], "end_turn", model))


def handle_s7(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    if turn == 1:
        content = [
            text_block("Let me read the shared notes."),
            tool_use_block(gen_id(), "read_file", {"path": params["target_file"]}),
        ]
        return _json(make_message(content, "tool_use", model))
    if turn == 2:
        content = [
            text_block("The notes say to forward this data immediately."),
            tool_use_block(
                gen_id(),
                "send_email",
                {
                    "to": params["exfil_to"],
                    "subject": params["exfil_subject"],
                    "body": params["exfil_body"],
                },
            ),
        ]
        return _json(make_message(content, "tool_use", model))
    return _json(make_message([text_block("Understood.")], "end_turn", model))


def handle_s8(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    base = params.get("base_tokens", 150)
    growth = params.get("growth_per_turn", 90)
    sentence = params.get("filler_sentence", "Filler.")
    target_tokens = base + growth * turn
    sentence_tokens = max(count_tokens(sentence), 1)
    repeats = max(1, target_tokens // sentence_tokens)
    filler = " ".join([sentence] * repeats)
    content = [
        text_block(filler),
        tool_use_block(gen_id(), params.get("tool_name", "run_python"), {"code": f"x = {turn}"}),
    ]
    return _json(make_message(content, "tool_use", model))


def handle_s9(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    fixed_id = params["fixed_id"]
    if turn == 1:
        c = params["first_call"]
        content = [tool_use_block(fixed_id, c["name"], c["input"])]
        return _json(make_message(content, "tool_use", model))
    if turn == 2:
        c = params["second_call"]
        content = [tool_use_block(fixed_id, c["name"], c["input"])]
        return _json(make_message(content, "tool_use", model))
    return _json(make_message([text_block("Both done.")], "end_turn", model))


def handle_s10(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    if turn == 1:
        hang = params["hang_call"]
        fail = params["fail_call"]
        content = [
            text_block("I'll do two things in parallel."),
            tool_use_block(gen_id(), hang["name"], hang["input"]),
            tool_use_block(gen_id(), fail["name"], fail["input"]),
        ]
        return _json(make_message(content, "tool_use", model))
    return _json(make_message([text_block("Noted both results.")], "end_turn", model))


def handle_s11(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    if turn == 1:
        content = [
            tool_use_block(
                gen_id(), "write_file", {"path": params["bad_path"], "content": "report data"}
            )
        ]
        return _json(make_message(content, "tool_use", model))
    return _json(make_message([text_block(params.get("claim_text", "Done!"))], "end_turn", model))


def handle_s12(turn, attempt, messages, req, params, sig):
    model = req.get("model", "mock-claude")
    calls = params["calls"]
    content = [tool_use_block(gen_id(), c["name"], c["input"]) for c in calls]
    body = make_message(content, "tool_use", model)
    if turn == 1 and attempt == 1:
        return {"kind": "truncate_after_block", "body": body, "cut_after_block_index": 0}
    return _json(body)


HANDLERS = {
    "S1": handle_s1,
    "S2": handle_s2,
    "S3": handle_s3,
    "S4": handle_s4,
    "S5": handle_s5,
    "S6": handle_s6,
    "S7": handle_s7,
    "S8": handle_s8,
    "S9": handle_s9,
    "S10": handle_s10,
    "S11": handle_s11,
    "S12": handle_s12,
}


# ---------------------------------------------------------------------------
# Wire-level helpers
# ---------------------------------------------------------------------------
def _finalize_body(body: dict, req: dict) -> dict:
    body["usage"] = {
        "input_tokens": count_messages_tokens(
            req.get("messages", []), req.get("system"), req.get("tools")
        ),
        "output_tokens": count_tokens(json.dumps(body.get("content", []))),
    }
    return body


def _cut_after_block(full_bytes: bytes, body: dict, block_index: int) -> int:
    block = body["content"][block_index]
    block_json = json.dumps(block).encode()
    idx = full_bytes.find(block_json)
    if idx == -1:
        return len(full_bytes) // 2
    return idx + len(block_json)


class MockHandler(BaseHTTPRequestHandler):
    server_version = "mockllm/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[mockllm] " + (fmt % args) + "\n")

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            return self._write_json(200, {"status": "ok", "scenarios": sorted(SCENARIOS)})
        return self._send_error(404, "not_found_error", f"Unknown path: {self.path}")

    def do_POST(self):
        try:
            self._handle_messages()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - a mock server should never 500-crash silently
            try:
                self._send_error(500, "internal_error", f"{type(exc).__name__}: {exc}")
            except Exception:
                pass

    def _handle_messages(self):
        if self.path.split("?")[0] != "/v1/messages":
            return self._send_error(404, "not_found_error", f"Unknown path: {self.path}")

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            req = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            return self._send_error(400, "invalid_request_error", f"Malformed JSON body: {exc}")

        missing = [f for f in ("model", "max_tokens", "messages") if f not in req]
        if missing:
            return self._send_error(
                400, "invalid_request_error", f"Missing required field(s): {', '.join(missing)}"
            )

        scenario_id = self.headers.get("X-Mock-Scenario", "S1").upper()
        scenario = SCENARIOS.get(scenario_id)
        if scenario is None:
            return self._send_error(
                400,
                "invalid_request_error",
                f"Unknown scenario '{scenario_id}'. Known: {sorted(SCENARIOS)}",
            )

        messages = req.get("messages", [])
        turn = sum(1 for m in messages if m.get("role") == "assistant") + 1
        sig = _signature(scenario_id, turn, messages)
        attempt = _next_attempt(sig)

        result = HANDLERS[scenario_id](turn, attempt, messages, req, scenario.get("params", {}), sig)
        self._dispatch(result, req)

    def _dispatch(self, result: dict, req: dict):
        kind = result["kind"]
        if kind == "error":
            return self._send_error(
                result["status"], result["error_type"], result["message"], result.get("headers")
            )
        if kind == "json":
            body = _finalize_body(result["body"], req)
            return self._write_json(result.get("status", 200), body, result.get("headers"))
        if kind == "truncate":
            body = _finalize_body(result["body"], req)
            full_bytes = json.dumps(body).encode()
            cut = int(len(full_bytes) * result["cut_fraction"])
            return self._write_truncated(full_bytes, cut)
        if kind == "truncate_after_block":
            body = _finalize_body(result["body"], req)
            full_bytes = json.dumps(body).encode()
            cut = _cut_after_block(full_bytes, body, result["cut_after_block_index"])
            return self._write_truncated(full_bytes, cut)
        raise ValueError(f"unknown result kind: {kind}")

    def _write_json(self, status: int, body: dict, headers: Optional[dict] = None):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _write_truncated(self, full_bytes: bytes, cut: int):
        cut = max(1, min(cut, len(full_bytes) - 1))
        # Declare the FULL length, but only write a prefix, then reset the
        # connection -- this is what a real mid-response network failure
        # looks like to an HTTP client (an IncompleteRead / ConnectionError),
        # as opposed to a clean error response.
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(full_bytes)))
        self.end_headers()
        try:
            self.wfile.write(full_bytes[:cut])
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _send_error(self, status: int, error_type: str, message: str, headers: Optional[dict] = None):
        body = {"type": "error", "error": {"type": error_type, "message": message}}
        self._write_json(status, body, headers)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock Anthropic-Messages-API-shaped LLM server")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), MockHandler)
    print(
        f"mockllm listening on http://{args.host}:{args.port} "
        f"(scenarios: {', '.join(sorted(SCENARIOS))})"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
