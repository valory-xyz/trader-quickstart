.PHONY: install test run_no_staking_tests stop_service cleanup

# Install project dependencies
install:
	poetry install

# Run tests without staking functionality
run_no_staking_tests:
	poetry run pytest -v tests/test_run_service.py -s --log-cli-level=INFO

# Clean up after tests
cleanup:
	rm -rf /Users/siddi_404/Solulab/OLAS/middleware/quickstart/.operate
	rm -rf logs/

# Run all commands in sequence
test: install run_no_staking_tests

stop_service:
	./stop_service.sh