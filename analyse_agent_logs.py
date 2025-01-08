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
        "--agent",
        default="aea_0",
        help="The agent name to analyze (default: 'aea_0')."
    )
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Reset the database before running analysis."
    )
    parser.add_argument(
        "--from-dir",
        help="Path to the logs directory (if not provided, will auto-detect)."
    )
    return parser.parse_args()


def find_build_directory(service_dir):
    """Find the appropriate build directory within the service directory."""
    try:
        build_dirs = [
            d for d in os.listdir(service_dir)
            if d.startswith("abci_build_") and os.path.isdir(os.path.join(service_dir, d))
        ]
        return os.path.join(service_dir, build_dirs[0]) if build_dirs else os.path.join(service_dir, "abci_build")
    except FileNotFoundError:
        print(f"Service directory '{service_dir}' not found")
        sys.exit(1)


def run_analysis(logs_dir, agent, reset_db):
    """Run the log analysis command."""
    command = [
        "poetry", "run", "autonomy", "analyse", "logs",
        "--from-dir", logs_dir,
        "--agent", agent,
        "--fsm",
    ]
    if reset_db:
        command.append("--reset-db")

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
    run_analysis(logs_dir, args.agent, args.reset_db)
