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

echo ""
echo "-------------------------"
echo "Fix broken service update"
echo "-------------------------"
echo ""
echo "This script fixes an interrupted on-chain service update by an Open Autonomy version <0.12.1.post4"
echo ""

echo "WARNING: This script (fix_interrupted_service_update.sh) is deprecated."
echo "Please use the latest version of ./run_script.sh, which addresses the issues fixed in this script."
read -p "Do you want to continue? (y/n): " choice

if [[ $choice == "y" || $choice == "Y" ]]; then
    echo "Continuing with the script..."
else
    echo "Exiting the script."
    exit 1
fi

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


# check state
expected_state="| Service State             | DEPLOYED                                     |"
service_info=$(cd trader; poetry run autonomy service --use-custom-chain info "$service_id")
service_state=$(echo "$service_info" | grep "Service State")
if [ "$service_state" == "$expected_state" ]
then
    echo "Service $service_id is already in DEPLOYED sate. No action has been done."
    exit 0
fi


echo "Renaming /trader folder..."
count=$(ls -d ./trader.old* 2>/dev/null | wc -l)
new_number=$((count + 1))

if [ -d "./trader" ]; then
    mv "./trader" "./trader.old.$new_number"
    echo "The /trader folder has been renamed to /trader.old.$new_number"
else
    echo "The ./trader folder does not exist."
fi

# clone repo
directory="trader"
# This is a tested version that works well.
# Feel free to replace this with a different version of the repo, but be careful as there might be breaking changes
service_version="v0.7.0"
service_repo=https://github.com/valory-xyz/$directory.git
echo "Cloning the $directory repo..."
git clone --depth 1 --branch $service_version $service_repo


cd $directory
if [ "$(git rev-parse --is-inside-work-tree)" = true ]
then
    poetry install
    poetry run autonomy packages sync
else
    echo "$directory is not a git repo!"
    exit 1
fi

# check state
expected_state="| Service State             | DEPLOYED                                     |"
service_info=$(poetry run autonomy service --use-custom-chain info "$service_id")
service_state=$(echo "$service_info" | grep "Service State")
if [ "$service_state" == "$expected_state" ]
then
    echo "Service $service_id is already in DEPLOYED sate. No action has been done."
    exit 0
fi


# Check balances
agent_address=$(get_address "../$keys_json_path")
operator_address=$(get_address "../$operator_keys_file")

suggested_amount=50000000000000000
ensure_minimum_balance "$operator_address" $suggested_amount "operator's address"

suggested_amount=50000000000000000
ensure_minimum_balance $agent_address $suggested_amount "agent instance's address"



echo "Copying agent and operator keys..."
# generate private key files in the format required by the CLI tool
agent_pkey_file="agent_pkey.txt"
agent_pkey=$(get_private_key "../$keys_json_path")
agent_pkey="${agent_pkey#0x}"
echo -n "$agent_pkey" >"$agent_pkey_file"

operator_pkey_file="operator_pkey.txt"
operator_pkey=$(get_private_key "../$operator_keys_file")
operator_pkey="${operator_pkey#0x}"
echo -n "$operator_pkey" >"$operator_pkey_file"

# # update service
echo "[Service owner] Updating on-chain service $service_id..."
agent_id=12
cost_of_bonding=10000000000000000
nft="bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq"
output=$(
    poetry run autonomy mint \
        --skip-hash-check \
        --use-custom-chain \
        service packages/valory/services/trader/ \
        --key "$operator_pkey_file" \
        --nft $nft \
        -a $agent_id \
        -n $n_agents \
        --threshold $n_agents \
        -c $cost_of_bonding \
        --update "$service_id"
)
if [[ $? -ne 0 ]]; then
    echo "Updating service failed.\n$output"
    rm -f $agent_pkey_file
    rm -f $operator_pkey_file
    exit 1
fi

# activate service
echo "[Service owner] Activating registration for on-chain service $service_id..."
output=$(poetry run autonomy service --use-custom-chain activate --key "$operator_pkey_file" "$service_id")
if [[ $? -ne 0 ]]; then
    echo "Activating service failed.\n$output"
    rm -f $agent_pkey_file
    rm -f $operator_pkey_file
    exit 1
fi

# register agent instance
echo "[Operator] Registering agent instance for on-chain service $service_id..."
output=$(poetry run autonomy service --use-custom-chain register --key "$operator_pkey_file" "$service_id" -a $agent_id -i "$agent_address")
if [[ $? -ne 0 ]]; then
    echo "Registering agent instance failed.\n$output"
    rm -f $agent_pkey_file
    rm -f $operator_pkey_file
    exit 1
fi

# deploy on-chain service
echo "[Service owner] Deploying on-chain service $service_id..."
output=$(poetry run autonomy service --use-custom-chain deploy "$service_id" --key "$operator_pkey_file" --reuse-multisig)
if [[ $? -ne 0 ]]; then
    echo "Deploying service failed.\n$output"
    rm -f $agent_pkey_file
    rm -f $operator_pkey_file
    exit 1
fi

# delete the pkey files
rm -f $agent_pkey_file
rm -f $operator_pkey_file
echo ""
echo "Finished update of on-chain service $service_id."