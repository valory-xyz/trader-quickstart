import os
import subprocess
import sys
import argparse


def _parse_args():
    """Parse the script arguments."""
    parser = argparse.ArgumentParser(description="Analyse agent logs.")

    parser.add_argument(
        "--service-dir",
        default="trader_service",
        help="The service directory containing build directories (default: 'trader_service')."
    )
    parser.add_argument(
        "--from-dir",
        help="Path to the logs directory. If not provided, it is auto-detected."
    )
    parser.add_argument(
        "--agent",
        default="aea_0",
        help="The agent name to analyze (default: 'aea_0')."
    )
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Use this flag to disable resetting the log database."
    )
    parser.add_argument(
        "--start-time",
        help="Start time in `YYYY-MM-DD H:M:S,MS` format."
    )
    parser.add_argument(
        "--end-time",
        help="End time in `YYYY-MM-DD H:M:S,MS` format."
    )
    parser.add_argument(
        "--log-level",
        choices=["INFO", "DEBUG", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level."
    )
    parser.add_argument(
        "--period",
        type=int,
        help="Period ID."
    )
    parser.add_argument(
        "--round",
        help="Round name."
    )
    parser.add_argument(
        "--behaviour",
        help="Behaviour name filter."
    )
    parser.add_argument(
        "--fsm",
        action="store_true",
        help="Print only the FSM execution path."
    )
    parser.add_argument(
        "--include-regex",
        help="Regex pattern to include in the result."
    )
    parser.add_argument(
        "--exclude-regex",
        help="Regex pattern to exclude from the result."
    )

    return parser.parse_args()


def find_build_directory(service_dir):
    """Find the appropriate build directory within the service directory."""
    try:
        build_dirs = [
            d for d in os.listdir(service_dir)
            if d.startswith("abci_build_") and os.path.isdir(os.path.join(service_dir, d))
        ]
        if build_dirs:
            build_dir = os.path.join(service_dir, build_dirs[0])
            logs_dir = os.path.join(build_dir, "persistent_data", "logs")
            if os.path.exists(logs_dir) and os.listdir(logs_dir):
                return build_dir
        return os.path.join(service_dir, "abci_build")
    except FileNotFoundError:
        print(f"Service directory '{service_dir}' not found")
        sys.exit(1)


def run_analysis(logs_dir, **kwargs):
    """Run the log analysis command."""
    command = [
        "poetry", "run", "autonomy", "analyse", "logs",
        "--from-dir", logs_dir,
    ]
    if kwargs.get("agent"):
        command.extend(["--agent", kwargs.get("agent")])
    if kwargs.get("reset_db"):
        command.extend(["--reset-db"])
    if kwargs.get("start_time"):
        command.extend(["--start-time", kwargs.get("start_time")])
    if kwargs.get("end_time"):
        command.extend(["--end-time", kwargs.get("end_time")])
    if kwargs.get("log_level"):
        command.extend(["--log-level", kwargs.get("log_level")])
    if kwargs.get("period"):
        command.extend(["--period", kwargs.get("period")])
    if kwargs.get("round"):
        command.extend(["--round", kwargs.get("round")])
    if kwargs.get("behaviour"):
        command.extend(["--behaviour", kwargs.get("behaviour")])
    if kwargs.get("fsm"):
        command.extend(["--fsm"])
    if kwargs.get("include_regex"):
        command.extend(["--include-regex", kwargs.get("include_regex")])
    if kwargs.get("exclude_regex"):
        command.extend(["--exclude-regex", kwargs.get("exclude_regex")])

    try:
        subprocess.run(command, check=True)
        print("Analysis completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        sys.exit(e.returncode)
    except FileNotFoundError:
        print("Poetry or autonomy not found. Ensure they are installed and accessible.")
        sys.exit(1)


if __name__ == "__main__":
    # Parse user arguments
    args = _parse_args()

    # Determine the logs directory
    if args.from_dir:
        logs_dir = args.from_dir
        if not os.path.exists(logs_dir):
            print(f"Specified logs directory '{logs_dir}' not found.")
            sys.exit(1)
    else:
        # Auto-detect the logs directory
        build_dir = find_build_directory(args.service_dir)
        logs_dir = os.path.join(build_dir, "persistent_data", "logs")
        if not os.path.exists(logs_dir):
            print(f"Logs directory '{logs_dir}' not found.")
            sys.exit(1)

    # Run the analysis
    run_analysis(logs_dir, **vars(args))
