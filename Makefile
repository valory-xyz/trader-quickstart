.PHONY: install test-install test run_no_staking_tests

# Install project dependencies for produ
install:
	poetry install --only main

# Install project dependencies for testing
test-install:
	poetry install

# Run tests without staking functionality
run_no_staking_tests:
	poetry run pytest -v tests/test_run_service.py -s --log-cli-level=INFO

# Run all commands in sequence
test: test-install run_no_staking_tests