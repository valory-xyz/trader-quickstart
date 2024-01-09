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

    private_key=$(echo -n "$private_key" | awk '{gsub(/\\"/, "\"", $0); print $0}')
    private_key="${private_key#0x}"

    echo -n "$private_key"
}

# Function to retrieve on-chain service state (requires env variables set to use --use-custom-chain)
get_on_chain_service_state() {
    local service_id="$1"
    local service_info=$(poetry run autonomy service --use-custom-chain info "$service_id")
    local state="$(echo "$service_info" | awk '/Service State/ {sub(/\|[ \t]*Service State[ \t]*\|[ \t]*/, ""); sub(/[ \t]*\|[ \t]*/, ""); print}')"
    echo "$state"
}

# Asks password if key files are password-protected
ask_password_if_needed() {
    agent_pkey=$(get_private_key "$keys_json_path")
    if [[ "$agent_pkey" = *crypto* ]]; then
        echo "Enter your password"
        echo "-------------------"
        echo "Your key files are protected with a password."
        read -s -p "Please, enter your password: " password
        use_password=true
        password_argument="--password $password"
        echo ""
    else
        echo "Your key files are not protected with a password."
        use_password=false
        password_argument=""
    fi
    echo ""
}

# Validates the provided password
validate_password() {
    local is_password_valid_1=$(poetry run python ../scripts/is_keys_json_password_valid.py ../$keys_json_path $password_argument)
    local is_password_valid_2=$(poetry run python ../scripts/is_keys_json_password_valid.py ../$operator_keys_file $password_argument)

    if [ "$is_password_valid_1" != "True" ] || [ "$is_password_valid_2" != "True" ]; then
        echo "Could not decrypt key files. Please verify if your key files are password-protected, and if the provided password is correct (passwords are case-sensitive)."
        echo "Terminating the script."
        exit 1
    fi
}

store=".trader_runner"
env_file_path="$store/.env"
rpc_path="$store/rpc.txt"
operator_keys_file="$store/operator_keys.json"
operator_pkey_path="$store/operator_pkey.txt"
keys_json="keys.json"
keys_json_path="$store/$keys_json"
agent_pkey_path="$store/agent_pkey.txt"
agent_address_path="$store/agent_address.txt"
service_id_path="$store/service_id.txt"
service_safe_address_path="$store/service_safe_address.txt"
store_readme_path="$store/README.txt"

source "$env_file_path"
rpc=$(cat $rpc_path)
operator_address=$(get_address $operator_keys_file)
service_id=$(cat $service_id_path)
unstake=true
gnosis_chain_id=100

export CUSTOM_CHAIN_RPC=$rpc
export CUSTOM_CHAIN_ID=$gnosis_chain_id
export CUSTOM_SERVICE_MANAGER_ADDRESS="0x04b0007b2aFb398015B76e5f22993a1fddF83644"
export CUSTOM_SERVICE_REGISTRY_ADDRESS="0x9338b5153AE39BB89f50468E608eD9d764B755fD"
export CUSTOM_STAKING_ADDRESS="0x5add592ce0a1B5DceCebB5Dcac086Cd9F9e3eA5C"
export CUSTOM_OLAS_ADDRESS="0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
export CUSTOM_SERVICE_REGISTRY_TOKEN_UTILITY_ADDRESS="0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8"
export CUSTOM_GNOSIS_SAFE_PROXY_FACTORY_ADDRESS="0x3C1fF68f5aa342D296d4DEe4Bb1cACCA912D95fE"
export CUSTOM_GNOSIS_SAFE_SAME_ADDRESS_MULTISIG_ADDRESS="0x6e7f594f680f7aBad18b7a63de50F0FeE47dfD06"
export CUSTOM_MULTISEND_ADDRESS="0x40A2aCCbd92BCA938b02010E17A5b8929b49130D"
export MECH_AGENT_ADDRESS="0x77af31De935740567Cf4fF1986D04B2c964A786a"
export WXDAI_ADDRESS="0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"

set -e  # Exit script on first error
echo "--------------------------"
echo "Terminate on-chain service"
echo "--------------------------"
echo ""
echo "This script will terminate and unbond your on-chain service (id $service_id)."
echo "If your service is staked, you will receive the staking funds to the owner/operator address:"
echo "$operator_address"
echo 
echo "Please, ensure that your service is stopped (./stop_service.sh) before proceeding."
echo "Do you want to continue? (yes/no)"
read -r response
echo ""

if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    echo "Cancelled."
    exit 0
fi

ask_password_if_needed
cd trader
validate_password

if [ "${USE_STAKING}" = true ]; then
    poetry run python "../scripts/staking.py" "$service_id" "$CUSTOM_SERVICE_REGISTRY_ADDRESS" "$CUSTOM_STAKING_ADDRESS" "../$operator_pkey_path" "$rpc" "$unstake";
fi

service_safe_address=$(cat "../$service_safe_address_path")
current_safe_owners=$(poetry run python "../scripts/get_safe_owners.py" "$service_safe_address" "../$agent_pkey_path" "$rpc" $password_argument | awk '{gsub(/"/, "\047", $0); print $0}')
agent_address=$(get_address "../$keys_json_path")

# transfer the ownership of the Safe from the agent to the service owner
# (in a live service, this should be done by sending a 0 DAI transfer to its Safe)
if [[ "$(get_on_chain_service_state "$service_id")" == "DEPLOYED" && "$current_safe_owners" == "['$agent_address']" ]]; then
    echo "[Agent instance] Swapping Safe owner..."
    poetry run python "../scripts/swap_safe_owner.py" "$service_safe_address" "../$agent_pkey_path" "$operator_address" "$rpc" $password_argument
fi

# terminate current service
if [ "$(get_on_chain_service_state "$service_id")" == "DEPLOYED" ]; then
    echo "[Service owner] Terminating on-chain service $service_id..."
    output=$(
        poetry run autonomy service \
            --use-custom-chain \
            terminate "$service_id" \
            --key "../$operator_pkey_path" $password_argument
    )
fi

# unbond current service
if [ "$(get_on_chain_service_state "$service_id")" == "TERMINATED_BONDED" ]; then
    echo "[Operator] Unbonding on-chain service $service_id..."
    output=$(
        poetry run autonomy service \
            --use-custom-chain \
            unbond "$service_id" \
            --key "../$operator_pkey_path" $password_argument
    )
fi

if [ "$(get_on_chain_service_state "$service_id")" == "PRE_REGISTRATION" ]; then
    echo "Service $service_id is now terminated and unbonded (i.e., it is on PRE-REGISTRATION state)."
    echo "You can check this on https://registry.olas.network/gnosis/services/$service_id."
    echo "In order to deploy your on-chain service again, please execute './run_service.sh'."
fi
echo "Finished."
