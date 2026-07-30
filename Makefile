.PHONY: setup run-mock test-mock test eval

VENV := .venv/bin

setup:
	python3 -m venv .venv
	$(VENV)/pip install -q --upgrade pip
	$(VENV)/pip install -q -r mockllm/requirements.txt
	$(VENV)/pip install -q requests

# Start the mock model server on localhost:8000.
run-mock:
	$(VENV)/python -m mockllm.server --port 8000

# mockllm's own smoke tests (proves the mock behaves as documented).
test-mock:
	$(VENV)/python -m unittest discover -s mockllm/tests -v

# Agent's own tests: tools (path confinement, allow-lists, run_python),
# email idempotency, and crash-recovery exactly-once.
test: test-mock
	$(VENV)/python test_tools.py
	$(VENV)/python test_email.py
	$(VENV)/python test_crash.py

# Agent eval suite: 14 cases (5 adversarial, 2 known-gap).
eval:
	$(VENV)/python -m evals.run_evals