#!/bin/bash

# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

# force utf mode for python, cause sometimes there are issues with local codepages
export PYTHONUTF8=1

set -e  # Exit script on first error

# Display information of the Git repository
current_branch=$(git rev-parse --abbrev-ref HEAD)
latest_commit_hash=$(git rev-parse HEAD)
echo "Current branch: $current_branch"
echo "Commit hash: $latest_commit_hash"

# Check the command-line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --build-only)
            echo "Build-only flag selected."
            export BUILD_ONLY=true
            ;;
        --attended=false)
            export ATTENDED=false
            ;;
        *) echo "Unknown parameter: $1" ;;
    esac
    shift
done

# Check if user is inside a venv
if [[ "$VIRTUAL_ENV" != "" ]]
then
    echo "Please exit the virtual environment!"
    exit 1
fi

# Check dependencies
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
    python3 scripts/check_python.py
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
    python scripts/check_python.py
else
    echo >&2 "Python is not installed!";
    exit 1
fi

command -v poetry >/dev/null 2>&1 ||
{ echo >&2 "Poetry is not installed!";
  exit 1
}

command -v docker >/dev/null 2>&1 ||
{ echo >&2 "Docker is not installed!";
  exit 1
}

docker rm -f abci0 node0 trader_abci_0 trader_tm_0 &> /dev/null ||
{ echo >&2 "Docker is not running!";
  exit 1
}

# Install dependencies and run the agent througth the middleware
poetry install --no-cache
poetry run python -m operate.cli quickstart configs/config_predict_trader.json
