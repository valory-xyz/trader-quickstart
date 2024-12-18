.PHONY: install test run_no_staking_tests

# Install project dependencies
install:
	pip install -r requirements.txt

# Run tests without staking functionality
run_no_staking_tests: install
	pytest -v tests/test_run_service.py -s --log-cli-level=INFO

# Run all commands in sequence
test: install run_no_staking_tests