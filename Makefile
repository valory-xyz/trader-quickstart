.PHONY: run_no_staking_tests

run_no_staking_tests:
	pytest -v tests/test_run_service.py -s --log-cli-level=INFO