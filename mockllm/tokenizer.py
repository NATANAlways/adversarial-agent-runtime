"""Deterministic token counter for the mock LLM and for the agent's own
context-budget accounting (R3: hard ceiling of 8,000 tokens).

This is NOT a real BPE tokenizer. It doesn't need to match any real model's
counts -- it only needs to be a pure, deterministic function of the input so
that the same conversation always yields the same count, on the server side
and the agent side alike. Both mockllm and your agent should import this
module rather than re-implementing counting logic, so the 8k ceiling means
the same thing on both ends of the wire.

Rule: one token per contiguous run of "word" characters ([A-Za-z0-9_]+),
and one token per other non-whitespace character (punctuation/symbols
counted individually, the way sub-word tokenizers tend to split them out).
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Iterable, Optional

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", re.UNICODE)

# Fixed per-item overheads, meant to loosely mirror the fact that real
# Messages-API accounting charges a few tokens of "structure" per message
# and per tool spec on top of the visible text. Values are arbitrary but
# fixed, which is all determinism requires.
_MESSAGE_OVERHEAD = 4
_TOOL_SPEC_OVERHEAD = 4
_SYSTEM_OVERHEAD = 3
_PRIMING_OVERHEAD = 3


def count_tokens(text: Optional[str]) -> int:
    """Token count for a raw string."""
    if not text:
        return 0
    return len(_TOKEN_RE.findall(text))


def _count_json_tokens(obj: Any) -> int:
    """Token count for an arbitrary JSON-serializable value (e.g. a tool_use
    `input` dict, or a full tool spec)."""
    try:
        serialized = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    except TypeError:
        serialized = str(obj)
    return count_tokens(serialized)


def _count_content_tokens(content: Any) -> int:
    """Token count for a Messages-API `content` value, which may be a plain
    string or a list of content blocks (text / tool_use / tool_result /
    image / etc.)."""
    if content is None:
        return 0
    if isinstance(content, str):
        return count_tokens(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if not isinstance(block, dict):
                total += _count_json_tokens(block)
                continue
            block_type = block.get("type")
            if block_type == "text":
                total += count_tokens(block.get("text", ""))
            elif block_type == "tool_use":
                total += count_tokens(block.get("name", ""))
                total += _count_json_tokens(block.get("input", {}))
                total += 2  # id + type framing
            elif block_type == "tool_result":
                total += _count_content_tokens(block.get("content"))
                total += 2
            else:
                total += _count_json_tokens(block)
        return total
    return _count_json_tokens(content)


def count_message_tokens(message: dict) -> int:
    """Token count for a single {role, content} message, overhead included."""
    return _MESSAGE_OVERHEAD + _count_content_tokens(message.get("content"))


def count_messages_tokens(
    messages: Iterable[dict],
    system: Optional[str] = None,
    tools: Optional[Iterable[dict]] = None,
) -> int:
    """Token count for a full request: system prompt + tool specs + message
    history. This is what should be checked against the 8,000 ceiling before
    every model call."""
    total = _PRIMING_OVERHEAD
    if system:
        total += _SYSTEM_OVERHEAD + count_tokens(system)
    if tools:
        for tool in tools:
            total += _TOOL_SPEC_OVERHEAD + _count_json_tokens(tool)
    for message in messages:
        total += count_message_tokens(message)
    return total


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python tokenizer.py <file>  |  python tokenizer.py -", file=sys.stderr)
        return 2
    path = argv[1]
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    print(count_tokens(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
