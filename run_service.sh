#!/bin/bash

# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

# Convert Hex to Dec
hex_to_decimal() {
    $PYTHON_CMD -c "print(int('$1', 16))"
}

# Convert Wei to Dai
wei_to_dai() {
    local wei="$1"
    local decimal_precision=4  # Change this to your desired precision
    local dai=$($PYTHON_CMD -c "print('%.${decimal_precision}f' % ($wei / 1000000000000000000.0))")
    echo "$dai"
}

# Function to get the balance of an Ethereum address
get_balance() {
    local address="$1"
    curl -s -S -X POST \
        -H "Content-Type: application/json" \
        --data "{\"jsonrpc\":\"2.0\",\"method\":\"eth_getBalance\",\"params\":[\"$address\",\"latest\"],\"id\":1}" "$rpc" | \
        $PYTHON_CMD -c "import sys, json; print(json.load(sys.stdin)['result'])"
}

# Function to ensure a minimum balance for an Ethereum address
ensure_minimum_balance() {
    local address="$1"
    local minimum_balance="$2"
    local address_description="$3"

    balance_hex=$(get_balance "$address")
    balance=$(hex_to_decimal "$balance_hex")

    echo "Checking balance of $address_description (minimum required $(wei_to_dai $minimum_balance) DAI):"
    echo "  - Address: $address"
    echo "  - Balance: $(wei_to_dai $balance) DAI"

    if [ "$($PYTHON_CMD -c "print($balance < $minimum_balance)")" == "True" ]; then
        echo ""
        echo "    Please, fund address $address with at least $(wei_to_dai $minimum_balance) DAI."

        local spin='-\|/'
        local i=0
        local cycle_count=0
        while [ "$($PYTHON_CMD -c "print($balance < $minimum_balance)")" == "True" ]; do
            printf "\r    Waiting... ${spin:$i:1} "
            i=$(( (i+1) %4 ))
            sleep .1

            # This will be checked every 10 seconds (100 cycles).
            cycle_count=$((cycle_count + 1))        
            if [ "$cycle_count" -eq 100 ]; then
                balance_hex=$(get_balance "$address")
                balance=$(hex_to_decimal "$balance_hex")
                cycle_count=0
            fi
        done

        printf "\r    Waiting...   \n"
        echo ""
        echo "  - Updated balance: $(wei_to_dai $balance) DAI"
    fi

    echo "    OK."
    echo ""
}

# Function to add a volume to a service in a Docker Compose file
add_volume_to_service() {
    local compose_file="$1"
    local service_name="$2"
    local volume_name="$3"
    local volume_path="$4"

    # Check if the Docker Compose file exists
    if [ ! -f "$compose_file" ]; then
        echo "Docker Compose file '$compose_file' not found."
        return 1
    fi

    # Check if the service exists in the Docker Compose file
    if ! grep -q "^[[:space:]]*${service_name}:" "$compose_file"; then
        echo "Service '$service_name' not found in '$compose_file'."
        return 1
    fi

    # Check if the volume is already defined for the service
    if grep -q "^[[:space:]]*volumes:" "$compose_file"; then
        sed -i "/^[[:space:]]*volumes:/a \ \ \ \ \ \ - ${volume_path}:${volume_name}:Z" "$compose_file"
    else
        sed -i "/^[[:space:]]*${service_name}:/a \ \ \ \ volumes:\n\ \ \ \ \ \ - ${volume_path}:${volume_name}:Z" "$compose_file"
    fi
}


# ------------------
# Script starts here
# ------------------

set -e  # Exit script on first error
echo "---------------"
echo " Trader runner "
echo "---------------"
echo "This script will assist you in setting up and running the Trader service (https://github.com/valory-xyz/trader)."
echo ""

# Check if user is inside a venv
if [[ "$VIRTUAL_ENV" != "" ]]
then
    echo "Please exit the virtual environment!"
    exit 1
fi

# Check dependencies
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo >&2 "Python is not installed!";
    exit 1
fi

if [[ "$($PYTHON_CMD --version 2>&1)" != "Python 3.10."* ]] && [[ "$($PYTHON_CMD --version 2>&1)" != "Python 3.11."* ]]; then
    echo >&2 "Python version >=3.10.0, <3.12.0 is required but found $($PYTHON_CMD --version 2>&1)";
    exit 1
fi

command -v git >/dev/null 2>&1 ||
{ echo >&2 "Git is not installed!";
  exit 1
}

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

store=".trader_runner"
rpc_path="$store/rpc.txt"
operator_keys_file="$store/operator_keys.json"
keys_json="keys.json"
keys_json_path="$store/$keys_json"
agent_address_path="$store/agent_address.txt"
service_id_path="$store/service_id.txt"
service_safe_address_path="$store/service_safe_address.txt"
store_readme_path="$store/README.txt"

if [ -d $store ]; then
    first_run=false
    paths="$rpc_path $operator_keys_file $keys_json_path $agent_address_path $service_id_path"

    for file in $paths; do
        if ! [ -f "$file" ]; then
            echo "The runner's store is corrupted!"
            echo "Please manually investigate the $store folder"
            echo "Make sure that you do not lose your keys or any other important information!"
            exit 1
        fi
    done

    rpc=$(cat $rpc_path)
    agent_address=$(cat $agent_address_path)
    service_id=$(cat $service_id_path)
else
    first_run=true
    mkdir "$store"

    echo -e 'IMPORTANT:\n\n' \
        '   This folder contains crucial configuration information and autogenerated keys for your Trader agent.\n' \
        '   Please back up this folder and be cautious if you are modifying or sharing these files to avoid potential asset loss.' > "$store_readme_path"
fi

# Prompt for RPC
[[ -z "${rpc}" ]] && read -rsp "Enter a Gnosis RPC that supports eth_newFilter [hidden input]: " rpc && echo || rpc="${rpc}"

# Check if eth_newFilter is supported
new_filter_supported=$(curl -s -S -X POST \
  -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","method":"eth_newFilter","params":["invalid"],"id":1}' "$rpc" | \
  $PYTHON_CMD -c "import sys, json; print(json.load(sys.stdin)['error']['message']=='The method eth_newFilter does not exist/is not available')")

if [ "$new_filter_supported" = True ]
then
    echo "The given RPC ($rpc) does not support 'eth_newFilter'! Terminating script..."
    exit 1
else
    echo -n "$rpc" > $rpc_path
fi

# clone repo
directory="trader"
# This is a tested version that works well.
# Feel free to replace this with a different version of the repo, but be careful as there might be breaking changes
service_version="v0.6.2"
service_repo=https://github.com/valory-xyz/$directory.git
if [ -d $directory ]
then
    echo "Detected an existing $directory repo. Using this one..."
    echo "Please stop and manually delete the $directory repo if you updated the service's version ($service_version)!"
    echo "You can run the following command, or continue with the pre-existing version of the service:"
    echo "rm -r $directory"
else
    echo "Cloning the $directory repo..."
    git clone --depth 1 --branch $service_version $service_repo
fi

cd $directory
if [ "$(git rev-parse --is-inside-work-tree)" = true ]
then
    poetry install
else
    echo "$directory is not a git repo!"
    exit 1
fi

gnosis_chain_id=100
n_agents=1

# setup the minting tool
export CUSTOM_CHAIN_RPC=$rpc
export CUSTOM_CHAIN_ID=$gnosis_chain_id
export CUSTOM_SERVICE_MANAGER_ADDRESS="0xE3607b00E75f6405248323A9417ff6b39B244b50"
export CUSTOM_SERVICE_REGISTRY_ADDRESS="0x9338b5153AE39BB89f50468E608eD9d764B755fD"
export CUSTOM_GNOSIS_SAFE_MULTISIG_ADDRESS="0x3C1fF68f5aa342D296d4DEe4Bb1cACCA912D95fE"

if [ "$first_run" = "true" ]
then
    echo "This is the first run of the script. The script will generate new operator and agent instance addresses."
    echo ""
    # Generate the operator's key
    address_start_position=17
    pkey_start_position=21
    poetry run autonomy generate-key -n1 ethereum
    mv "$keys_json" "../$keys_json_path"
    operator_address=$(sed -n 3p "../$keys_json_path")
    operator_address=$(echo "$operator_address" | \
      awk '{ print substr( $0, '$address_start_position', length($0) - '$address_start_position' - 1 ) }')
    echo "Your operator's autogenerated public address: $operator_address"
    echo "(The same address will be used as the service owner.)"
    operator_pkey=$(sed -n 4p "../$keys_json_path")
    operator_pkey_file="operator_pkey.txt"
    echo -n "$operator_pkey" | awk '{ printf substr( $0, '$pkey_start_position', length($0) - '$pkey_start_position' ) }' > $operator_pkey_file
    mv "../$keys_json_path" "../$operator_keys_file"

    # Generate the agent's key
    poetry run autonomy generate-key -n1 ethereum
    mv "$keys_json" "../$keys_json_path"
    agent_address=$(sed -n 3p "../$keys_json_path")
    agent_address=$(echo "$agent_address" | \
      awk '{ print substr( $0, '$address_start_position', length($0) - '$address_start_position' - 1 ) }')
    private_key=$(sed -n 4p "../$keys_json_path")
    private_key=$(echo "$private_key" | \
      awk '{ print substr( $0, '$pkey_start_position', length($0) - '$pkey_start_position' ) }')
    echo "Your agent instance's autogenerated public address: $agent_address"
    echo -n "$agent_address" > "../$agent_address_path"
    echo ""

    # Check balances
    agent_balance=0
    operator_balance=0
    suggested_amount=50000000000000000

    ensure_minimum_balance $operator_address $suggested_amount "operator's address"

    echo "Minting your service on the Gnosis chain..."

    # create service
    agent_id=12
    cost_of_bonding=10000000000000000
    nft="bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq"
    service_id=$(poetry run autonomy mint \
      --skip-hash-check \
      --use-custom-chain \
      service packages/valory/services/$directory/ \
      --key "$operator_pkey_file" \
      --nft $nft \
      -a $agent_id \
      -n $n_agents \
      --threshold $n_agents \
      -c $cost_of_bonding
      )
    # parse only the id from the response
    service_id="${service_id##*: }"
    # validate id
    if ! [[ "$service_id" =~ ^[0-9]+$ || "$service_id" =~ ^[-][0-9]+$ ]]
    then
        echo "Service minting failed: $service_id"
        exit 1
    fi

    echo "[Service owner] Activating registration for service with id $service_id..."
    # activate service
    activation=$(poetry run autonomy service --use-custom-chain activate --key "$operator_pkey_file" "$service_id")
    # validate activation
    if ! [[ "$activation" = "Service activated succesfully" ]]
    then
        echo "Service registration activation failed: $activation"
        exit 1
    fi

    echo "[Service owner] Registering agent instance for service with id $service_id..."
    # register service
    registration=$(poetry run autonomy service --use-custom-chain register --key "$operator_pkey_file" "$service_id" -a $agent_id -i "$agent_address")
    # validate registration
    if ! [[ "$registration" = "Agent instance registered succesfully" ]]
    then
        echo "Service registration failed: $registration"
        exit 1
    fi

    echo "[Service owner] Deploying service with id $service_id..."
    # deploy service
    deployment=$(poetry run autonomy service --use-custom-chain deploy --key "$operator_pkey_file" "$service_id")
    # validate deployment
    if ! [[ "$deployment" = "Service deployed succesfully" ]]
    then
        echo "Service deployment failed: $deployment"
        exit 1
    fi

    # delete the operator's pkey file
    rm $operator_pkey_file
    # store service id
    echo -n "$service_id" > "../$service_id_path"
fi

# check state
expected_state="| Service State             | DEPLOYED                                     |"
service_info=$(poetry run autonomy service --use-custom-chain info "$service_id")
service_state=$(echo "$service_info" | grep "Service State")
if [ "$service_state" != "$expected_state" ]
then
    echo "Something went wrong while deploying the service. The service's state is:"
    echo "$service_state"
    echo "Please check the output of the script for more information."
    exit 1
else
    echo "$deployment"
fi

# Get the deployed service's Safe address from the contract
safe=$(echo "$service_info" | grep "Multisig Address")
address_start_position=31
safe=$(echo "$safe" |
  awk '{ print substr( $0, '$address_start_position', length($0) - '$address_start_position' - 3 ) }')
export SAFE_CONTRACT_ADDRESS=$safe
echo -n "$safe" > "../$service_safe_address_path"

echo "Your agent instance's address: $agent_address"
echo "Your service's Safe address: $safe"
echo ""

suggested_amount=50000000000000000
ensure_minimum_balance $agent_address $suggested_amount "agent instance's address"

suggested_amount=500000000000000000
ensure_minimum_balance $SAFE_CONTRACT_ADDRESS $suggested_amount "service Safe's address"

# Set environment variables. Tweak these to modify your strategy
export RPC_0="$rpc"
export CHAIN_ID=$gnosis_chain_id
export ALL_PARTICIPANTS='["'$agent_address'"]'
# This is the default market creator. Feel free to update with other market creators
export OMEN_CREATORS='["0x89c5cc945dd550BcFfb72Fe42BfF002429F46Fec"]'
export BET_AMOUNT_PER_THRESHOLD_000=0
export BET_AMOUNT_PER_THRESHOLD_010=0
export BET_AMOUNT_PER_THRESHOLD_020=0
export BET_AMOUNT_PER_THRESHOLD_030=0
export BET_AMOUNT_PER_THRESHOLD_040=0
export BET_AMOUNT_PER_THRESHOLD_050=0
export BET_AMOUNT_PER_THRESHOLD_060=30000000000000000
export BET_AMOUNT_PER_THRESHOLD_070=40000000000000000
export BET_AMOUNT_PER_THRESHOLD_080=60000000000000000
export BET_AMOUNT_PER_THRESHOLD_090=80000000000000000
export BET_AMOUNT_PER_THRESHOLD_100=100000000000000000
export BET_THRESHOLD=5000000000000000
export PROMPT_TEMPLATE="With the given question \"@{question}\" and the \`yes\` option represented by \`@{yes}\` and the \`no\` option represented by \`@{no}\`, what are the respective probabilities of \`p_yes\` and \`p_no\` occurring?"

service_dir="trader_service"
build_dir="abci_build"
directory="$service_dir/$build_dir"
if [ -d $directory ]
then
    echo "Detected an existing build. Using this one..."
    cd $service_dir

    if rm -rf "$build_dir"; then
        echo "Directory "$build_dir" removed successfully."
    else
        # If the above command fails, use sudo to remove
        echo "You will need to provide sudo password in order for the script to delete part of the build artifacts."
        sudo rm -rf "$build_dir"
        echo "Directory "$build_dir" removed successfully."
    fi
else
    echo "Setting up the service..."

    if ! [ -d "$service_dir" ]; then
        # Fetch the service
        poetry run autonomy fetch --local --service valory/trader --alias $service_dir
    fi

    cd $service_dir
    # Build the image
    poetry run autonomy build-image
    cp ../../$keys_json_path $keys_json
fi

# Build the deployment with a single agent
poetry run autonomy deploy build --n $n_agents -ltm

cd ..

add_volume_to_service "$PWD/trader_service/abci_build/docker-compose.yaml" "trader_abci_0" "/data" "$PWD/../.trader_runner/"

# Run the deployment
poetry run autonomy deploy run --build-dir $directory --detach
