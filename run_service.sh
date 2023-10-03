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
            i=$(((i + 1) % 4))
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

# Get the address from a keys.json file
get_address() {
    local keys_json_path="$1"

    if [ ! -f "$keys_json_path" ]; then
        echo "Error: $keys_json_path does not exist."
        return 1
    fi

    local address_start_position=17
    local address=$(sed -n 3p "$keys_json_path")
    address=$(echo "$address" |
        awk '{ print substr( $0, '$address_start_position', length($0) - '$address_start_position' - 1 ) }')

    echo -n "$address"
}

# Get the private key from a keys.json file
get_private_key() {
    local keys_json_path="$1"

    if [ ! -f "$keys_json_path" ]; then
        echo "Error: $keys_json_path does not exist."
        return 1
    fi

    local private_key_start_position=21
    local private_key=$(sed -n 4p "$keys_json_path")
    private_key=$(echo -n "$private_key" |
        awk '{ printf substr( $0, '$private_key_start_position', length($0) - '$private_key_start_position' ) }')

    echo -n "$private_key"
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

# Function to retrieve on-chain service state (requires env variables set to use --use-custom-chain)
get_on_chain_service_state() {
    local service_id="$1"
    local service_info=$(poetry run autonomy service --use-custom-chain info "$service_id")
    local state="$(echo "$service_info" | awk '/Service State/ {sub(/\|[ \t]*Service State[ \t]*\|[ \t]*/, ""); sub(/[ \t]*\|[ \t]*/, ""); print}')"
    echo "$state"
}


# ------------------
# Script starts here
# ------------------

set -e  # Exit script on first error
echo ""
echo "---------------"
echo " Trader runner "
echo "---------------"
echo ""
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
service_version="v0.6.6"
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
    poetry run autonomy packages sync
else
    echo "$directory is not a git repo!"
    exit 1
fi

echo ""
echo "-----------------------------------------"
echo "Checking Autonolas Protocol service state"
echo "-----------------------------------------"

gnosis_chain_id=100
n_agents=1

# setup the minting tool
export CUSTOM_CHAIN_RPC=$rpc
export CUSTOM_CHAIN_ID=$gnosis_chain_id
export CUSTOM_SERVICE_MANAGER_ADDRESS="0xE3607b00E75f6405248323A9417ff6b39B244b50"
export CUSTOM_SERVICE_REGISTRY_ADDRESS="0x9338b5153AE39BB89f50468E608eD9d764B755fD"
export CUSTOM_GNOSIS_SAFE_MULTISIG_ADDRESS="0x3C1fF68f5aa342D296d4DEe4Bb1cACCA912D95fE"
export CUSTOM_GNOSIS_SAFE_PROXY_FACTORY_ADDRESS="0x3C1fF68f5aa342D296d4DEe4Bb1cACCA912D95fE"
export CUSTOM_GNOSIS_SAFE_SAME_ADDRESS_MULTISIG_ADDRESS="0x3d77596beb0f130a4415df3D2D8232B3d3D31e44"
export CUSTOM_MULTISEND_ADDRESS="0x40A2aCCbd92BCA938b02010E17A5b8929b49130D"
export AGENT_ID=12

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
    suggested_amount=50000000000000000
    ensure_minimum_balance "$operator_address" $suggested_amount "operator's address"

    echo "Minting your service on the Gnosis chain..."

    # create service
    cost_of_bonding=10000000000000000
    nft="bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq"
    service_id=$(poetry run autonomy mint \
      --skip-hash-check \
      --use-custom-chain \
      service packages/valory/services/$directory/ \
      --key "$operator_pkey_file" \
      --nft $nft \
      -a $AGENT_ID \
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

    echo -n "$service_id" > "../$service_id_path"
fi

# generate private key files in the format required by the CLI tool
agent_pkey_file="agent_pkey.txt"
agent_pkey=$(get_private_key "../$keys_json_path")
agent_pkey="${agent_pkey#0x}"
echo -n "$agent_pkey" >"$agent_pkey_file"

operator_pkey_file="operator_pkey.txt"
operator_pkey=$(get_private_key "../$operator_keys_file")
operator_pkey="${operator_pkey#0x}"
echo -n "$operator_pkey" >"$operator_pkey_file"

# Update the on-chain service if outdated
packages="packages/packages.json"
local_service_hash="$(grep 'service' $packages | awk -F: '{print $2}' | tr -d '", ' | head -n 1)"
remote_service_hash=$(poetry run python "../scripts/service_hash.py")
operator_address=$(get_address "../$operator_keys_file")

if [ "$local_service_hash" != "$remote_service_hash" ]; then
    echo ""
    echo "Your currently minted on-chain service (id $service_id) mismatches the fetched trader service ($service_version):"
    echo "  - Local service hash ($service_version): $local_service_hash"
    echo "  - On-chain service hash (id $service_id): $remote_service_hash"
    echo ""
    echo "This is most likely caused due to an update of the trader service code."
    echo "The script will proceed now to update the on-chain service."
    echo "The operator and agent addressess need to have enough funds so that the process is not interrupted."
    echo ""

    # Check balances
    suggested_amount=50000000000000000
    ensure_minimum_balance "$operator_address" $suggested_amount "operator's address"

    suggested_amount=50000000000000000
    ensure_minimum_balance $agent_address $suggested_amount "agent instance's address"

    echo "------------------------------"
    echo "Updating on-chain service $service_id"
    echo "------------------------------"
    echo ""
    echo "PLEASE, DO NOT INTERRUPT THIS PROCESS."
    echo ""
    echo "Cancelling the on-chain service update prematurely could lead to an inconsistent state of the Safe or the on-chain service state, which may require manual intervention to resolve."
    echo ""

    if [ $(get_on_chain_service_state $service_id) == "DEPLOYED" ]; then
        # transfer the ownership of the Safe from the agent to the service owner
        # (in a live service, this should be done by sending a 0 DAI transfer to its Safe)
        service_safe_address=$(<"../$service_safe_address_path")
        echo "[Agent instance] Swapping Safe owner..."
        output=$(poetry run python "../scripts/swap_safe_owner.py" "$service_safe_address" "$agent_pkey_file" "$operator_address" "$rpc")
        if [[ $? -ne 0 ]]; then
            echo "Swapping Safe owner failed.\n$output"
            rm -f $agent_pkey_file
            rm -f $operator_pkey_file
            exit 1
        fi
        echo "$output"

        # terminate current service
        echo "[Service owner] Terminating on-chain service $service_id..."
        output=$(
            poetry run autonomy service \
                --use-custom-chain \
                terminate "$service_id" \
                --key "$operator_pkey_file"
        )
        if [[ $? -ne 0 ]]; then
            echo "Terminating service failed.\n$output"
            echo "Please, delete or rename the ./trader folder and try re-run this script again."
            rm -f $agent_pkey_file
            rm -f $operator_pkey_file
            exit 1
        fi
    fi

    # unbond current service
    if [ $(get_on_chain_service_state $service_id) == "TERMINATED_BONDED" ]; then
        echo "[Operator] Unbonding on-chain service $service_id..."
        output=$(
            poetry run autonomy service \
                --use-custom-chain \
                unbond "$service_id" \
                --key "$operator_pkey_file"
        )
        if [[ $? -ne 0 ]]; then
            echo "Unbonding service failed.\n$output"
            echo "Please, delete or rename the ./trader folder and try re-run this script again."
            rm -f $agent_pkey_file
            rm -f $operator_pkey_file
            exit 1
        fi
    fi

    # update service
    if [ $(get_on_chain_service_state $service_id) == "PRE_REGISTRATION" ]; then
        echo "[Service owner] Updating on-chain service $service_id..."
        cost_of_bonding=10000000000000000
        nft="bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq"
        output=$(
            poetry run autonomy mint \
                --skip-hash-check \
                --use-custom-chain \
                service packages/valory/services/trader/ \
                --key "$operator_pkey_file" \
                --nft $nft \
                -a $AGENT_ID \
                -n $n_agents \
                --threshold $n_agents \
                -c $cost_of_bonding \
                --update "$service_id"
        )
        if [[ $? -ne 0 ]]; then
            echo "Updating service failed.\n$output"
            echo "Please, delete or rename the ./trader folder and try re-run this script again."
            rm -f $agent_pkey_file
            rm -f $operator_pkey_file
            exit 1
        fi
    fi

    echo ""
    echo "Finished updating on-chain service $service_id."
fi

echo ""
echo "Ensuring on-chain service $service_id is in DEPLOYED state..."

if [ $(get_on_chain_service_state $service_id) != "DEPLOYED" ]; then
    suggested_amount=25000000000000000
    ensure_minimum_balance "$operator_address" $suggested_amount "operator's address"
fi

# activate service
if [ $(get_on_chain_service_state $service_id) == "PRE_REGISTRATION" ]; then
    echo "[Service owner] Activating registration for on-chain service $service_id..."
    output=$(poetry run autonomy service --use-custom-chain activate --key "$operator_pkey_file" "$service_id")
    if [[ $? -ne 0 ]]; then
        echo "Activating service failed.\n$output"
        echo "Please, delete or rename the ./trader folder and try re-run this script again."
        rm -f $agent_pkey_file
        rm -f $operator_pkey_file
        exit 1
    fi
fi

# register agent instance
if [ $(get_on_chain_service_state $service_id) == "ACTIVE_REGISTRATION" ]; then
    echo "[Operator] Registering agent instance for on-chain service $service_id..."
    output=$(poetry run autonomy service --use-custom-chain register --key "$operator_pkey_file" "$service_id" -a $AGENT_ID -i "$agent_address")
    if [[ $? -ne 0 ]]; then
        echo "Registering agent instance failed.\n$output"
        echo "Please, delete or rename the ./trader folder and try re-run this script again."
        rm -f $agent_pkey_file
        rm -f $operator_pkey_file
        exit 1
    fi
fi

# deploy on-chain service
service_state=$(get_on_chain_service_state $service_id)
if [ "$service_state" == "FINISHED_REGISTRATION" ] && [ "$first_run" = "true" ]; then
    echo "[Service owner] Deploying on-chain service $service_id..."
    output=$(poetry run autonomy service --use-custom-chain deploy "$service_id" --key "$operator_pkey_file")
    if [[ $? -ne 0 ]]; then
        echo "Deploying service failed.\n$output"
        echo "Please, delete or rename the ./trader folder and try re-run this script again."
        rm -f $agent_pkey_file
        rm -f $operator_pkey_file
        exit 1
    fi
elif [ "$service_state" == "FINISHED_REGISTRATION" ]; then
    echo "[Service owner] Deploying on-chain service $service_id..."
    output=$(poetry run autonomy service --use-custom-chain deploy "$service_id" --key "$operator_pkey_file" --reuse-multisig)
    if [[ $? -ne 0 ]]; then
        echo "Deploying service failed.\n$output"
        echo "Please, delete or rename the ./trader folder and try re-run this script again."
        rm -f $agent_pkey_file
        rm -f $operator_pkey_file
        exit 1
    fi
fi

# delete the pkey files
rm -f $agent_pkey_file
rm -f $operator_pkey_file

# check state
service_state=$(get_on_chain_service_state $service_id)
if [ "$service_state" != "DEPLOYED" ]; then
    echo "Something went wrong while deploying on-chain service. The service's state is $service_state."
    echo "Please check the output of the script and the on-chain registry for more information."
    exit 1
fi

echo ""
echo "Finished checking Autonolas Protocol service $service_id state."


echo ""
echo "------------------------------"
echo "Starting the trader service..."
echo "------------------------------"
echo ""

# Get the deployed service's Safe address from the contract
service_info=$(poetry run autonomy service --use-custom-chain info "$service_id")
safe=$(echo "$service_info" | grep "Multisig Address")
address_start_position=31
safe=$(echo "$safe" |
  awk '{ print substr( $0, '$address_start_position', length($0) - '$address_start_position' - 3 ) }')
export SAFE_CONTRACT_ADDRESS=$safe
echo -n "$safe" > "../$service_safe_address_path"

echo "Your agent instance's address: $agent_address"
echo "Your service's Safe address: $safe"
echo ""

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
export REDEEM_MARGIN_DAYS=10

service_dir="trader_service"
build_dir="abci_build"
directory="$service_dir/$build_dir"

suggested_amount=50000000000000000
ensure_minimum_balance $agent_address $suggested_amount "agent instance's address"

suggested_amount=500000000000000000
ensure_minimum_balance $SAFE_CONTRACT_ADDRESS $suggested_amount "service Safe's address"

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

# add_volume_to_service "$PWD/trader_service/abci_build/docker-compose.yaml" "trader_abci_0" "/data" "$PWD/../.trader_runner/"

# Run the deployment
poetry run autonomy deploy run --build-dir $directory --detach
