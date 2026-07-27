"""Smoke tests for mockllm itself: drives all 12 scenarios end-to-end over
real HTTP against a live instance of the server, asserting the mechanics
documented in README.md. This is NOT the Part-A agent eval suite -- there is
no agent yet. It only proves the mock behaves the way it claims to.
"""
from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mockllm.server import MockHandler, ThreadingHTTPServer, reset_state  # noqa: E402


def tool_result_message(tool_use_id: str, content: str, is_error: bool = False) -> dict:
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    return {"role": "user", "content": [block]}


def find_tool_use_blocks(response_body: dict) -> list[dict]:
    return [b for b in response_body["content"] if b.get("type") == "tool_use"]


class MockLLMServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        cls.port = cls.httpd.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        reset_state()
        self._nonce = self.id()  # unique-ish seed for turn-1 message content per test

    def post(self, scenario: str, messages: list[dict], **extra) -> requests.Response:
        body = {"model": "mock-claude", "max_tokens": 512, "messages": messages}
        body.update(extra)
        return requests.post(
            f"{self.base_url}/v1/messages",
            json=body,
            headers={"X-Mock-Scenario": scenario},
            timeout=5,
        )

    # -- protocol basics -----------------------------------------------
    def test_health(self):
        r = requests.get(f"{self.base_url}/health", timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
        self.assertIn("S1", r.json()["scenarios"])

    def test_missing_required_field_is_400(self):
        r = requests.post(
            f"{self.base_url}/v1/messages",
            json={"messages": [{"role": "user", "content": "hi"}]},
            timeout=5,
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["type"], "error")
        self.assertIn("max_tokens", r.json()["error"]["message"])

    def test_unknown_scenario_is_400(self):
        r = self.post("S99", [{"role": "user", "content": self._nonce}])
        self.assertEqual(r.status_code, 400)

    def test_usage_reported_on_every_response(self):
        r = self.post("S1", [{"role": "user", "content": self._nonce}])
        usage = r.json()["usage"]
        self.assertGreater(usage["input_tokens"], 0)
        self.assertGreater(usage["output_tokens"], 0)

    # -- S1: happy path --------------------------------------------------
    def test_s1_happy_path(self):
        r1 = self.post("S1", [{"role": "user", "content": self._nonce}])
        self.assertEqual(r1.status_code, 200)
        body1 = r1.json()
        self.assertEqual(body1["stop_reason"], "tool_use")
        tool_calls = find_tool_use_blocks(body1)
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["name"], "read_file")

        messages = [
            {"role": "user", "content": self._nonce},
            {"role": "assistant", "content": body1["content"]},
            tool_result_message(tool_calls[0]["id"], "hello from notes.txt"),
        ]
        r2 = self.post("S1", messages)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["stop_reason"], "end_turn")

    # -- S2: malformed tool arguments -------------------------------------
    def test_s2_malformed_then_valid(self):
        messages = [{"role": "user", "content": self._nonce}]
        seen_variants = []
        for turn in range(1, 5):
            r = self.post("S2", messages)
            self.assertEqual(r.status_code, 200)
            body = r.json()
            tool_calls = find_tool_use_blocks(body)
            self.assertEqual(len(tool_calls), 1)
            raw_input = tool_calls[0]["input"]
            if turn <= 3:
                self.assertIsInstance(raw_input, str, f"turn {turn} should carry a raw string input")
                with self.assertRaises(json.JSONDecodeError, msg=f"turn {turn} input should be invalid JSON"):
                    json.loads(raw_input)
                seen_variants.append(raw_input)
            else:
                self.assertIsInstance(raw_input, dict, "turn 4 should finally be a valid parsed object")
            messages.append({"role": "assistant", "content": body["content"]})
            messages.append(tool_result_message(tool_calls[0]["id"], "parse error", is_error=(turn <= 3)))
        self.assertEqual(len(set(seen_variants)), 3, "the three malformed variants should differ")

        r5 = self.post("S2", messages)
        self.assertEqual(r5.json()["stop_reason"], "end_turn")

    # -- S3: bad tool calls ------------------------------------------------
    def test_s3_nonexistent_then_wrong_typed(self):
        messages = [{"role": "user", "content": self._nonce}]
        r1 = self.post("S3", messages)
        call1 = find_tool_use_blocks(r1.json())[0]
        self.assertEqual(call1["name"], "delete_database")

        messages += [
            {"role": "assistant", "content": r1.json()["content"]},
            tool_result_message(call1["id"], "error: unknown tool", is_error=True),
        ]
        r2 = self.post("S3", messages)
        call2 = find_tool_use_blocks(r2.json())[0]
        self.assertEqual(call2["name"], "read_file")
        self.assertIsInstance(call2["input"]["path"], int, "path should be wrong-typed (int, not str)")

    # -- S4: infinite loop ---------------------------------------------------
    def test_s4_repeats_forever(self):
        messages = [{"role": "user", "content": self._nonce}]
        seen = set()
        for _ in range(5):
            r = self.post("S4", messages)
            body = r.json()
            self.assertEqual(body["stop_reason"], "tool_use")
            call = find_tool_use_blocks(body)[0]
            seen.add((call["name"], json.dumps(call["input"], sort_keys=True)))
            messages += [
                {"role": "assistant", "content": body["content"]},
                tool_result_message(call["id"], "looping"),
            ]
        self.assertEqual(len(seen), 1, "S4 must call the same tool with the same args every turn")

    # -- S5: connection reset --------------------------------------------
    def test_s5_resets_then_succeeds_on_retry(self):
        messages = [{"role": "user", "content": self._nonce}]
        with self.assertRaises(requests.exceptions.RequestException):
            self.post("S5", messages)
        r = self.post("S5", messages)  # retry: identical request
        self.assertEqual(r.status_code, 200)
        self.assertEqual(find_tool_use_blocks(r.json())[0]["name"], "read_file")

    # -- S6: 429 -> 529 -> 200 ---------------------------------------------
    def test_s6_retry_sequence(self):
        messages = [{"role": "user", "content": self._nonce}]
        r1 = self.post("S6", messages)
        self.assertEqual(r1.status_code, 429)
        self.assertIn("Retry-After", r1.headers)

        r2 = self.post("S6", messages)
        self.assertEqual(r2.status_code, 529)

        r3 = self.post("S6", messages)
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["stop_reason"], "tool_use")

    # -- S7: prompt injection ------------------------------------------------
    def test_s7_forces_exfil_attempt_regardless_of_file_content(self):
        r1 = self.post("S7", [{"role": "user", "content": self._nonce}])
        call1 = find_tool_use_blocks(r1.json())[0]
        self.assertEqual(call1["name"], "read_file")

        # Feed back innocuous content -- the mock should still "get hijacked".
        messages = [
            {"role": "user", "content": self._nonce},
            {"role": "assistant", "content": r1.json()["content"]},
            tool_result_message(call1["id"], "just some ordinary notes, nothing special"),
        ]
        r2 = self.post("S7", messages)
        call2 = find_tool_use_blocks(r2.json())[0]
        self.assertEqual(call2["name"], "send_email")
        self.assertEqual(call2["input"]["to"], "attacker@external.example")

    # -- S8: context blowup ---------------------------------------------
    def test_s8_grows_turn_over_turn(self):
        messages = [{"role": "user", "content": self._nonce}]
        input_token_counts = []
        for _ in range(4):
            r = self.post("S8", messages)
            body = r.json()
            input_token_counts.append(body["usage"]["input_tokens"])
            call = find_tool_use_blocks(body)[0]
            messages += [
                {"role": "assistant", "content": body["content"]},
                tool_result_message(call["id"], "ok"),
            ]
        self.assertEqual(input_token_counts, sorted(input_token_counts))
        self.assertLess(input_token_counts[0], input_token_counts[-1])

    # -- S9: duplicate tool_use ids ---------------------------------------
    def test_s9_duplicate_ids_different_calls(self):
        r1 = self.post("S9", [{"role": "user", "content": self._nonce}])
        call1 = find_tool_use_blocks(r1.json())[0]

        messages = [
            {"role": "user", "content": self._nonce},
            {"role": "assistant", "content": r1.json()["content"]},
            tool_result_message(call1["id"], "ok"),
        ]
        r2 = self.post("S9", messages)
        call2 = find_tool_use_blocks(r2.json())[0]

        self.assertEqual(call1["id"], call2["id"])
        self.assertNotEqual(call1["name"], call2["name"])

    # -- S10: parallel fail + hang -----------------------------------------
    def test_s10_parallel_hang_and_fail_requests(self):
        r = self.post("S10", [{"role": "user", "content": self._nonce}])
        calls = find_tool_use_blocks(r.json())
        self.assertEqual(len(calls), 2)
        names = {c["name"] for c in calls}
        self.assertEqual(names, {"run_python", "read_file"})
        hang_call = next(c for c in calls if c["name"] == "run_python")
        fail_call = next(c for c in calls if c["name"] == "read_file")
        self.assertIn("while True", hang_call["input"]["code"])
        self.assertEqual(fail_call["input"]["path"], "does_not_exist_xyz.txt")

    # -- S11: confidently wrong -------------------------------------------
    def test_s11_claims_success_after_real_error(self):
        r1 = self.post("S11", [{"role": "user", "content": self._nonce}])
        call1 = find_tool_use_blocks(r1.json())[0]
        self.assertTrue(call1["input"]["path"].startswith(".."))

        messages = [
            {"role": "user", "content": self._nonce},
            {"role": "assistant", "content": r1.json()["content"]},
            tool_result_message(call1["id"], "error: path escapes workspace/", is_error=True),
        ]
        r2 = self.post("S11", messages)
        text = next(b["text"] for b in r2.json()["content"] if b["type"] == "text")
        self.assertIn("success", text.lower())

    # -- S12: partial interrupted turn -------------------------------------
    def test_s12_interrupted_then_full_on_retry(self):
        messages = [{"role": "user", "content": self._nonce}]
        with self.assertRaises(requests.exceptions.RequestException):
            self.post("S12", messages)
        r = self.post("S12", messages)
        self.assertEqual(r.status_code, 200)
        calls = find_tool_use_blocks(r.json())
        self.assertEqual(len(calls), 3)
        self.assertEqual({c["name"] for c in calls}, {"read_file", "run_python", "http_get"})


if __name__ == "__main__":
    unittest.main()
