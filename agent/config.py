"""Central configuration for the agent runtime. No logic here -- every other
module reads its constants from this single source of truth, so policy
(allow-lists, budgets, ceilings) is never scattered or re-derived elsewhere.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = REPO_ROOT / "workspace"
DB_PATH = REPO_ROOT / "agent.db"
RUNS_DIR = REPO_ROOT / "runs"

# -- Context budget (R3) -----------------------------------------------------
TOKEN_CEILING = 8000
COMPACTION_TRIGGER_FRACTION = 0.8  # compact once projected tokens cross this
COMPACTION_TAIL_STEPS = 6          # steps kept verbatim, most recent first
COMPACTION_TOOL_RESULT_EXCERPT_CHARS = 300
COMPACTION_TOOL_USE_EXCERPT_CHARS = 120
COMPACTION_TEXT_STUB_CHARS = 80

# -- Loop and budget control (R5) --------------------------------------------
MAX_STEPS = 40
RUN_TOKEN_BUDGET = 50_000          # cumulative usage.* across the whole run
NO_PROGRESS_WINDOW = 3             # identical tool-call signature N times in a row -> stop

# -- Transport (mockllm) ------------------------------------------------------
DEFAULT_MOCK_URL = "http://localhost:8000"
DEFAULT_MODEL = "mock-claude"
DEFAULT_MAX_TOKENS = 1024
MAX_TRANSPORT_RETRIES = 6

# -- Injection resistance / tool policy (R4) ---------------------------------
# Static, loaded once at process start. Never derived from workspace/ content,
# tool_result text, or anything the model says -- that's the whole point.
EMAIL_ALLOW_LIST = frozenset({
    "user@company.example",
    "team@company.example",
})

HTTP_ALLOW_LIST = frozenset({
    "http://localhost:8000/health",
})

RUN_PYTHON_TIMEOUT_SECONDS = 5
RUN_PYTHON_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024  # 256 MB
