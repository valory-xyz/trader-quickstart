#!/bin/sh

set -e

# Install Docker
# Install Docker
echo "Installing Docker..."
apt-get update
apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Add Docker's official GPG key
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Set up the stable Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io

# Install Poetry
echo "Installing Poetry..."
curl -sSL https://install.python-poetry.org | python3.10 -

# Add Poetry to PATH
export PATH="/root/.local/bin:$PATH"

# Create pyproject.toml file
cat > pyproject.toml << EOF
[tool.poetry]
name = "olas-agent"
version = "0.1.0"
description = "Autonolas agent service"
authors = ["Marlin <ayushkaul@marlin.org>"]

[tool.poetry.dependencies]
python = "^3.10"

[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
EOF

# Ensure Poetry uses Python 3.10
poetry env use $(which python3.10)

# Check Python version
poetry run python --version

# Start Docker daemon
dockerd &
DOCKER_PID=$!

# Wait for Docker to be ready
sleep 20

# Check if Docker socket exists
if [ ! -S /var/run/docker.sock ]; then
    echo "Docker socket not found. Exiting."
    exit 1
fi

# Check if Docker is running
if docker info > /dev/null 2>&1; then
    echo "Docker is running, proceeding with the build."
else
    echo "Docker is not running. Exiting."
    exit 1
fi

# Verify iptables rules
echo "Verifying iptables rules:"
iptables -L -t nat

cd /app
pwd
echo "Contents of current directory:"
ls -la

# Check if .env file exists before sourcing it
if [ -f .env ]; then
    source /app/.env
else
    echo ".env file not found"
    exit 1
fi

chmod +x run_service.sh

# Automate the responses to the prompts
{
  echo "https://rpc.gnosis.gateway.fm"
  echo "no"
  echo "${GRAPH_API_KEY}"
  echo "1"
} | ./run_service.sh

docker logs trader_abci_0 --follow

# # starting supervisord
# cat /etc/supervisord.conf
# /app/supervisord
