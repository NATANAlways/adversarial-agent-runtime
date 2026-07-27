.PHONY: setup run-mock test-mock test eval

VENV := .venv/bin

setup:
	python3 -m venv .venv
	$(VENV)/pip install -q --upgrade pip
	$(VENV)/pip install -q -r mockllm/requirements.txt

# Start the mock model server on localhost:8000.
run-mock:
	$(VENV)/python -m mockllm.server --port 8000

# mockllm's own smoke tests (proves the mock behaves as documented).
test-mock:
	$(VENV)/python -m unittest discover -s mockllm/tests -v

# TODO(Part A): once agent/ and evals/ exist, `test` and `eval` should run
# the agent's own test suite and eval harness (see the take-home spec's
# `make test` / `make eval` targets). For now there is no agent yet --
# only the mock server it will run against -- so both targets just run
# mockllm's smoke tests and say so explicitly rather than pretending.
test: test-mock
	@echo "NOTE: agent/ does not exist yet -- only mockllm's own tests ran."

eval:
	@echo "NOTE: evals/ does not exist yet -- there is no agent to evaluate."
