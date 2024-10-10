#!/bin/sh

set -e

# setting an address for loopback
ifconfig lo 127.0.0.1
ip addr

# adding a default route
ip route add default dev lo src 127.0.0.1
ip route

# iptables rule to route traffic to transparent proxy
iptables -t nat -I OUTPUT 1 -p tcp --dport 1:65535 ! -d 127.0.0.1 -j DNAT --to-destination 127.0.0.1:1200

echo "127.0.0.1 localhost" > /etc/hosts
echo "nameserver 127.0.0.1" > /etc/resolv.conf

# Start DNS proxy
/app/dnsproxy -u https://1.1.1.1/dns-query &
DNS_PID=$!

# Start transparent proxy for outbound traffic
/app/ip-to-vsock-transparent --vsock-addr 3:1200 --ip-addr 0.0.0.0:1200 &
PROXY_PID=$!

# Wait for DNS and proxy to be ready
sleep 10

mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<EOF
{
  "dns": ["172.17.0.1"],
  "iptables": true,
  "hosts": ["unix:///var/run/docker.sock"]
}
EOF

# Start Docker daemon
/bin/dockerd --debug  &
DOCKER_PID=$!

# Wait for Docker to be ready
sleep 20

iptables -t nat -I PREROUTING 1 -i docker0 -p tcp --dport 1:65535 -j DNAT --to-destination 172.17.0.1:1200

iptables -A FORWARD -i docker0 -o lo -j ACCEPT
iptables -A FORWARD -i lo -o docker0 -j ACCEPT

echo "Testing communication from docker"
docker run --rm alpine sh -c "
    nslookup ifconfig.me || echo 'DNS resolution failed'
    nc -zv ifconfig.me 443 || echo 'TCP connectivity failed'
    wget --no-check-certificate -O- -q https://ifconfig.me || echo 'wget failed'
"
# generate identity key
/app/keygen-ed25519 --secret /app/id.sec --public /app/id.pub

export HOME=/app
export POETRY_HOME=/app/.poetry
export PATH=$POETRY_HOME/bin:$PATH

# Print Poetry version
echo "Poetry version:"
poetry --version

# Check if curl is installed and working
if command -v curl >/dev/null 2>&1; then
    echo "Curl is installed."
    if curl -s --head http://www.google.com | grep "200 OK" > /dev/null; then
        echo "Curl is working."
    else
        echo "Curl is installed but not working."
        exit 1
    fi
else
    echo "Curl is not installed!"
    exit 1
fi

# Set up SSL certificates
export CURL_CA_BUNDLE="/etc/ssl/certs/ca-bundle.crt"
export SSL_CERT_FILE="/etc/ssl/certs/ca-bundle.crt"

# Test curl
echo "Testing curl..."
curl -v https://example.com

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

# Remove keychainPath if it exists
if [ -n "${keychainPath}" ]; then
    echo "Removing keychainPath"
    rm -f "${keychainPath}"
    export PATH="${builtins.getEnv "PATH" }:$PATH"
    security list-keychains | xargs -I{} sh -c 'security find-certificate -a -p "{}" >> ${keychainPath}; cat ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt >> ${keychainPath}'
fi

chmod +x run_service.sh

# Automate the responses to the prompts
{
  echo "https://rpc.gnosis.gateway.fm"
  echo "no"
  echo "${GRAPH_API_KEY}"
  echo "1"
} | ./run_service.sh

echo "following the logs of trader_abci_0 container..."

# starting supervisord
cat /etc/supervisord.conf
/app/supervisord