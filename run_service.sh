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
    local token="${4:-"0x0000000000000000000000000000000000000000"}"

    erc20_balance=0
    if [ ! "$token" = "0x0000000000000000000000000000000000000000" ]
    then
        erc20_balance=$(poetry run python "../scripts/erc20_balance.py" "$token" "$address" "$rpc")
    fi

    balance_hex=$(get_balance "$address")
    balance=$(hex_to_decimal "$balance_hex")
    balance=$($PYTHON_CMD -c "print(int($balance) + int($erc20_balance))")

    echo "Checking balance of $address_description (minimum required $(wei_to_dai "$minimum_balance") DAI):"
    echo "  - Address: $address"
    echo "  - Balance: $(wei_to_dai "$balance") DAI"

    if [ "$($PYTHON_CMD -c "print($balance < $minimum_balance)")" == "True" ]; then
        echo ""
        echo "    Please, fund address $address with at least $(wei_to_dai "$minimum_balance") DAI."

        local spin='-\|/'
        local i=0
        local cycle_count=0
        while [ "$($PYTHON_CMD -c "print($balance < $minimum_balance)")" == "True" ]; do
            printf "\r    Waiting... %s" "${spin:$i:1} "
            i=$(((i + 1) % 4))
            sleep .1

            # This will be checked every 10 seconds (100 cycles).
            cycle_count=$((cycle_count + 1))
            if [ "$cycle_count" -eq 100 ]; then
                balance_hex=$(get_balance "$address")
                balance=$(hex_to_decimal "$balance_hex")
                balance=$((erc20_balance+balance))
                cycle_count=0
            fi
        done

        printf "\r    Waiting...   \n"
        echo ""
        echo "  - Updated balance: $(wei_to_dai "$balance") DAI"
    fi

    echo "    OK."
    echo ""
}

# ensure erc20 balance
ensure_erc20_balance() {
    local address="$1"
    local minimum_balance="$2"
    local address_description="$3"
    local token="$4"
    local token_name="$5"

    balance=0
    if [ ! "$token" = "0x0000000000000000000000000000000000000000" ]
    then
        balance=$(poetry run python "../scripts/erc20_balance.py" "$token" "$address" "$rpc")
    fi

    echo "Checking balance of $address_description (minimum required $(wei_to_dai "$minimum_balance") $token_name):"
    echo "  - Address: $address"
    echo "  - Balance: $(wei_to_dai "$balance") $token_name"

    if [ "$($PYTHON_CMD -c "print($balance < $minimum_balance)")" == "True" ]; then
        echo ""
        echo "    Please, fund address $address with at least $(wei_to_dai "$minimum_balance") $token_name."

        local spin='-\|/'
        local i=0
        local cycle_count=0
        while [ "$($PYTHON_CMD -c "print($balance < $minimum_balance)")" == "True" ]; do
            printf "\r    Waiting... %s" "${spin:$i:1} "
            i=$(((i + 1) % 4))
            sleep .1

            # This will be checked every 10 seconds (100 cycles).
            cycle_count=$((cycle_count + 1))
            if [ "$cycle_count" -eq 100 ]; then
                balance=$(poetry run python "../scripts/erc20_balance.py" "$token" "$address" "$rpc")
                cycle_count=0
            fi
        done

        printf "\r    Waiting...   \n"
        echo ""
        echo "  - Updated balance: $(wei_to_dai "$balance") $token_name"
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

    private_key=$(echo -n "$private_key" | awk '{gsub(/\\"/, "\"", $0); print $0}')
    private_key="${private_key#0x}"

    echo -n "$private_key"
}

# Function to warm start the policy
warm_start() {
    echo '["prediction-online", "prediction-online-sme", "prediction-online-summarized-info", "prediction-sentence-embedding-bold", "prediction-sentence-embedding-conservative"]' | sudo tee "$PWD/../$store/available_tools_store.json"  > /dev/null
    echo '{"counts": [1,1,1,1,1], "eps": 0.1, "rewards": [0.0,0.0,0.0,0.0,0.0]}' | sudo tee "$PWD/../$store/policy_store.json"  > /dev/null
    echo '{}' | sudo tee "$PWD/../$store/utilized_tools.json"  > /dev/null
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

    if grep -q "^[[:space:]]*volumes:" "$compose_file"; then
        awk -v volume_path="$volume_path" -v volume_name="$volume_name" '
            /^ *volumes:/ {
                found_volumes = 1
                print
                print "      - " volume_path ":" volume_name ":Z"
                next
            }
            1
        ' "$compose_file" > temp_compose_file
    else
        awk -v service_name="$service_name" -v volume_path="$volume_path" -v volume_name="$volume_name" '
            /^ *'"$service_name"':/ {
                found_service = 1
                print
                print "    volumes:"
                print "      - " volume_path ":" volume_name ":Z"
                next
            }
            /^ *$/ && found_service == 1 {
                print "    volumes:"
                print "      - " volume_path ":" volume_name ":Z"
                found_service = 0
            }
            1
        ' "$compose_file" > temp_compose_file
    fi

    mv temp_compose_file "$compose_file"
}

# Function to retrieve on-chain service state (requires env variables set to use --use-custom-chain)
get_on_chain_service_state() {
    local service_id="$1"
    local service_info=$(poetry run autonomy service --use-custom-chain info "$service_id")
    local state="$(echo "$service_info" | awk '/Service State/ {sub(/\|[ \t]*Service State[ \t]*\|[ \t]*/, ""); sub(/[ \t]*\|[ \t]*/, ""); print}')"
    echo "$state"
}

# Asks if user wishes to use password-protected key files
ask_confirm_password() {
    echo "Use a password?"
    echo "---------------"
    echo "You can use a password to encrypt the generated key files. You will be asked for the password each time the script is run."
    while true; do
        read -p "Do you want to use a password? (yes/no): " use_password
        case "$use_password" in
            [Yy]|[Yy][Ee][Ss])
                echo "WARNING:"
                echo "  - Passwords are case-sensitive. Check your Caps Lock before continuing."
                echo "  - Passwords are not stored on disk."
                echo "  - If you lose your password, you will lose access to all assets associated to your operator or trader agent keys."
                echo ""
                while true; do
                    read -s -p "Enter your password: " password
                    echo ""

                    read -s -p "Confirm your password: " confirm_password
                    echo ""

                    if [ -z "$password" ]; then
                        echo "Password cannot be blank. Please try again."
                    elif [[ -n $(echo "-$password-" | awk '{ if(match($0, /[ \t]/)) print "contains_whitespace"; }') ]]; then
                        echo "Password cannot contain whitespace characters. Please try again."
                    elif [ ${#password} -lt 4 ]; then
                        echo "Password must be at least 4 characters long. Please try again."
                    elif [ "$password" = "$confirm_password" ]; then
                        use_password=true
                        password_argument="--password $password"
                        echo "Password confirmed. Please, store your pasword in a safe place."
                        read -n 1 -s -r -p "Press any key to continue..."
                        echo ""
                        echo ""
                        return 0
                    else
                        echo "Passwords do not match. Please try again."
                    fi
                done
                ;;
            [Nn]|[Nn][Oo])
                use_password=false
                password_argument=""
                echo ""
                return 0
                ;;
            * )
                echo "Please enter 'yes' or 'no'."
                ;;
        esac
    done
    echo ""
    return 0
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
    local is_password_valid_1=$(poetry run $PYTHON_CMD ../scripts/is_keys_json_password_valid.py ../$keys_json_path $password_argument)
    local is_password_valid_2=$(poetry run $PYTHON_CMD ../scripts/is_keys_json_password_valid.py ../$operator_keys_file $password_argument)

    if [ "$is_password_valid_1" != "True" ] || [ "$is_password_valid_2" != "True" ]; then
        echo "Could not decrypt key files. Please verify if your key files are password-protected, and if the provided password is correct (passwords are case-sensitive)."
        echo "Terminating the script."
        exit 1
    fi
}

# Function to retrieve the multisig address of a service
get_multisig_address() {
    local service_id="$1"
    local service_info=$(poetry run autonomy service --use-custom-chain info "$service_id")
    local state="$(echo "$service_info" | awk '/Multisig Address/ {sub(/\|[ \t]*Multisig Address[ \t]*\|[ \t]*/, ""); sub(/[ \t]*\|[ \t]*/, ""); print}')"
    echo "$state"
}

# stake or unstake a service
perform_staking_ops() {
    local unstake="$1"
    poetry run python "../scripts/staking.py" "$service_id" "$CUSTOM_SERVICE_REGISTRY_ADDRESS" "$CUSTOM_STAKING_ADDRESS" "../$operator_pkey_path" "$rpc" "$unstake" $password_argument
    echo ""
}

# Prompt user for staking preference
prompt_use_staking() {
    while true; do
        echo "Use staking?"
        echo "------------"
        read -p "Do you want to stake this service? (yes/no): " use_staking

        case "$use_staking" in
            [Yy]|[Yy][Ee][Ss])
                USE_STAKING="true"
                break
                ;;
            [Nn]|[Nn][Oo])
                USE_STAKING="false"
                break
                ;;
            *)
                echo "Please enter 'yes' or 'no'."
                ;;
        esac
    done
    echo ""
}

# Function to set or add a variable in the .env file and export it
dotenv_set_key() {
    local dotenv_path="$1"
    local key_to_set="$2"
    local value_to_set="$3"

    # Check if the .env file exists
    if [ ! -f "$dotenv_path" ]; then
        touch "$dotenv_path"
        echo "Created $dotenv_path"
    fi

    # Check if the variable already exists in the .env file
    if grep -q "^$key_to_set=" "$dotenv_path"; then
        # Variable exists, so update its value using awk
        awk -v key="$key_to_set" -v val="$value_to_set" '{gsub("^" key "=.*", key "=" val); print}' "$dotenv_path" > temp && mv temp "$dotenv_path"
        echo "Updated '$key_to_set=$value_to_set' in $dotenv_path"
    else
        # Variable doesn't exist, so add it to the .env file
        echo "$key_to_set=$value_to_set" >> "$dotenv_path"
        echo "Added '$key_to_set=$value_to_set' to $dotenv_path"
    fi

    export "$key_to_set=$value_to_set"
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
use_password=false
password_argument=""
zero_address="0x0000000000000000000000000000000000000000"

# Function to create the .trader_runner storage
create_storage() {
    local rpc="$1"

    echo "This is the first run of the script. The script will generate new operator and agent instance addresses."
    echo ""

    ask_confirm_password

    mkdir "../$store"

    # Generate README.txt file
    echo -e 'IMPORTANT:\n\n' \
        '   This folder contains crucial configuration information and autogenerated keys for your Trader agent.\n' \
        '   Please back up this folder and be cautious if you are modifying or sharing these files to avoid potential asset loss.' > "../$store_readme_path"
    
    # Generate .env file
    touch "../$env_file_path"

    # Prompt use staking
    prompt_use_staking
    dotenv_set_key "../$env_file_path" "USE_STAKING" "$USE_STAKING"

    if [ "$USE_STAKING" = true ]; then
        # New staking services use AGENT_ID=12 until end of Everest staking program
        AGENT_ID=12
    else
        # New non-staking services use AGENT_ID=14
        AGENT_ID=14
    fi
    dotenv_set_key "../$env_file_path" "AGENT_ID" "$AGENT_ID"


    # Generate the RPC file
    echo -n "$rpc" > "../$rpc_path"

    # Generate the owner/operator's key
    poetry run autonomy generate-key -n1 ethereum $password_argument
    mv "$keys_json" "../$operator_keys_file"
    operator_address=$(get_address "../$operator_keys_file")
    operator_pkey=$(get_private_key "../$operator_keys_file")
    echo -n "$operator_pkey" > "../$operator_pkey_path"
    echo "Your operator's autogenerated public address: $operator_address"
    echo "(The same address will be used as the service owner.)"

    # Generate the agent's key
    poetry run autonomy generate-key -n1 ethereum $password_argument
    mv "$keys_json" "../$keys_json_path"
    agent_address=$(get_address "../$keys_json_path")
    agent_pkey=$(get_private_key "../$keys_json_path")
    echo -n "$agent_pkey" > "../$agent_pkey_path"
    echo -n "$agent_address" > "../$agent_address_path"
    echo "Your agent instance's autogenerated public address: $agent_address"
    echo ""
}

# Function to read and load the .trader_runner storage information if it exists.
# Also sets `first_run` flag to identify whether we are running the script for the first time.
try_read_storage() {
    if [ -d $store ]; then

        # INFO: This is a fix to avoid corrupting already-created stores
        if [ ! -f "$env_file_path" ]; then
            touch "$env_file_path"
        fi

        # INFO: This is a fix to avoid corrupting already-created stores
        if [[ -f "$operator_keys_file" && ! -f "$operator_pkey_path" ]]; then
            operator_pkey=$(get_private_key "$operator_keys_file")
            echo -n "$operator_pkey" > "$operator_pkey_path"
        fi

        # INFO: This is a fix to avoid corrupting already-created stores
        if [[ -f "$keys_json_path" && ! -f "$agent_pkey_path" ]]; then
            agent_pkey=$(get_private_key "$keys_json_path")
            echo -n "$agent_pkey" > "$agent_pkey_path"
        fi

        first_run=false
        paths="$env_file_path $rpc_path $operator_keys_file $operator_pkey_path $keys_json_path $agent_address_path $agent_pkey_path $service_id_path"

        for file in $paths; do
            if ! [ -f "$file" ]; then
                if [ "$file" != $service_safe_address_path ] && [ "$file" != $service_id_path ]; then
                    echo "The runner's store is corrupted!"
                    echo "Please manually investigate the $store folder"
                    echo "Make sure that you do not lose your keys or any other important information!"
                    exit 1
                fi
            fi
        done

        unset USE_STAKING
        unset AGENT_ID
        source "$env_file_path"

        rpc=$(cat $rpc_path)
        agent_address=$(cat $agent_address_path)
        operator_address=$(get_address "$operator_keys_file")
        if [ -f "$service_id_path" ]; then
            service_id=$(cat $service_id_path)
        fi

        # INFO: This is a fix to avoid corrupting already-created stores
        if [ -z "$USE_STAKING" ]; then
            prompt_use_staking
            dotenv_set_key "$env_file_path" "USE_STAKING" "$USE_STAKING"
        fi

        # INFO: This is a fix to avoid corrupting already-created stores
        if [ "$USE_STAKING" = true ]; then
            # Existing staking services use AGENT_ID=12
            AGENT_ID=12
        else
            # Existing non-staking services use AGENT_ID=14
            AGENT_ID=14
        fi
        dotenv_set_key "$env_file_path" "AGENT_ID" "$AGENT_ID"
        ask_password_if_needed
    else
        first_run=true
    fi
}

# ------------------
# Script starts here
# ------------------

set -e  # Exit script on first error

# Initialize repo and version variables
org_name="valory-xyz"
directory="trader"
service_repo=https://github.com/$org_name/$directory.git
# This is a tested version that works well.
# Feel free to replace this with a different version of the repo, but be careful as there might be breaking changes
service_version="v0.9.11"

echo ""
echo "---------------"
echo " Trader runner "
echo "---------------"
echo ""
echo "This script will assist you in setting up and running the Trader service ($service_repo)."
echo ""

# Check the command-line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --with-staking)
            echo "WARNING: the flag '--with-staking' is deprecated"
            echo "------------------------------------------------"
            echo "Instead, the value is stored in the '$store' folder. You will be prompted in case the value has not been set."
            read -n 1 -s -r -p "Press any key to continue..."
            echo ""
            echo ""
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

try_read_storage

# Prompt for RPC
[[ -z "${rpc}" ]] && read -rsp "Enter a Gnosis RPC that supports eth_newFilter [hidden input]: " rpc && echo || rpc="${rpc}"

# Check the RPC
echo "Checking the provided RCP..."

rcp_response=$(curl -s -S -X POST \
  -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","method":"eth_newFilter","params":["invalid"],"id":1}' "$rpc")

rcp_error_message=$(echo "$rcp_response" | \
$PYTHON_CMD -c "import sys, json;
try: print(json.load(sys.stdin)['error']['message'])
except Exception as e: print('Exception processing RCP response')")

rcp_exception=$([[ "$rcp_error_message" == "Exception processing RCP response" ]] && echo true || echo false)
if [ "$rcp_exception" = true ]; then
    echo "Error: The received RCP response is malformed. Please verify the RPC address and/or RCP behavior."
    echo "  Received response:"
    echo "  $rcp_response"
    echo ""
    echo "Terminating script."
    exit 1
fi

rcp_out_of_requests=$([[ "$rcp_error_message" == "Out of requests" ]] && echo true || echo false)
if [ "$rcp_out_of_requests" = true ]; then
    echo "Error: The provided RCP is out of requests."
    echo "Terminating script."
    exit 1
fi

rcp_new_filter_supported=$([[ "$rcp_error_message" == "The method eth_newFilter does not exist/is not available" ]] && echo false || echo true)
if [ "$rcp_new_filter_supported" = false ]; then
    echo "Error: The provided RPC does not support 'eth_newFilter'."
    echo "Terminating script."
    exit 1
fi

echo "RPC checks passed."
echo ""

# clone repo
if [ -d $directory ]
then
    echo "Detected an existing $directory directory. Using this one..."
    echo "Please stop and manually delete the $directory repo if you updated the service's version ($service_version)!"
    echo "You can run the following command, or continue with the pre-existing version of the service:"
    echo "rm -r $directory"
else
    echo "Cloning the $directory repo from $org_name GitHub..."
    git clone --depth 1 --branch $service_version $service_repo
fi

cd $directory
if [ "$(git rev-parse --is-inside-work-tree)" = true ]
then
    poetry install
    poetry run autonomy packages sync
    poetry add tqdm
else
    echo "$directory is not a git repo!"
    exit 1
fi

if [ "$first_run" = "true" ]
then
    create_storage "$rpc"
fi

validate_password

echo ""
echo "-----------------------------------------"
echo "Checking Autonolas Protocol service state"
echo "-----------------------------------------"

gnosis_chain_id=100
n_agents=1
olas_balance_required_to_bond=25000000000000000000
olas_balance_required_to_stake=25000000000000000000
xdai_balance_required_to_bond=10000000000000000
suggested_top_up_default=50000000000000000

# setup the minting tool
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

if [ -z ${service_id+x} ];
then
    # Check balances
    suggested_amount=$suggested_top_up_default
    ensure_minimum_balance "$operator_address" $suggested_amount "owner/operator's address"

    echo "[Service owner] Minting your service on the Gnosis chain..."

    # create service
    nft="bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq"
    cmd="poetry run autonomy mint \
      --skip-hash-check \
      --use-custom-chain \
      service packages/valory/services/$directory/ \
      --key \"../$operator_pkey_path\" $password_argument\
      --nft $nft \
      -a $AGENT_ID \
      -n $n_agents \
      --threshold $n_agents"

    if [ "${USE_STAKING}" = true ]; then
      cost_of_bonding=$olas_balance_required_to_bond
      cmd+=" -c $cost_of_bonding --token $CUSTOM_OLAS_ADDRESS"
    else
      cost_of_bonding=$xdai_balance_required_to_bond
      cmd+=" -c $cost_of_bonding"
    fi
    service_id=$(eval $cmd)
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

# Update the on-chain service if outdated
packages="packages/packages.json"
local_service_hash="$(grep 'service' $packages | awk -F: '{print $2}' | tr -d '", ' | head -n 1)"
remote_service_hash=$(poetry run python "../scripts/service_hash.py")
operator_address=$(get_address "../$operator_keys_file")

if [ "$local_service_hash" != "$remote_service_hash" ]; then
    echo ""
    echo "WARNING: Your on-chain service configuration is out-of-date"
    echo "-----------------------------------------------------------"
    echo "Your currently minted on-chain service (id $service_id) mismatches the local trader service ($service_version):"
    echo "  - Local service hash ($service_version): $local_service_hash"
    echo "  - On-chain service hash (id $service_id): $remote_service_hash"
    echo ""
    echo "This is most likely caused due to an update of the trader service code."
    echo "The script will proceed now to update the on-chain service."
    echo "The operator and agent addresses need to have enough funds to complete the process."
    echo ""

    response="y"
    if [ "${USE_STAKING}" = true ]; then
      echo "Your service is in a staking program. Updating your on-chain service requires that it is first unstaked."
      echo "Unstaking your service will retrieve the accrued staking rewards."
      echo ""
      echo "Do you want to continue updating your service? (yes/no)"
      read -r response
      echo ""
    fi

    if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        echo "Skipping on-chain service update."
    else
      # unstake the service
      if [ "${USE_STAKING}" = true ]; then
          perform_staking_ops true
      fi

      # Check balances
      suggested_amount=$suggested_top_up_default
      ensure_minimum_balance "$operator_address" $suggested_amount "owner/operator's address"

      suggested_amount=$suggested_top_up_default
      ensure_minimum_balance $agent_address $suggested_amount "agent instance's address"

      echo "------------------------------"
      echo "Updating on-chain service $service_id"
      echo "------------------------------"
      echo ""
      echo "PLEASE, DO NOT INTERRUPT THIS PROCESS."
      echo ""
      echo "Cancelling the on-chain service update prematurely could lead to an inconsistent state of the Safe or the on-chain service state, which may require manual intervention to resolve."
      echo ""

      service_safe_address=$(<"../$service_safe_address_path")
      current_safe_owners=$(poetry run python "../scripts/get_safe_owners.py" "$service_safe_address" "../$agent_pkey_path" "$rpc" $password_argument | awk '{gsub(/"/, "\047", $0); print $0}')

      # transfer the ownership of the Safe from the agent to the service owner
      # (in a live service, this should be done by sending a 0 DAI transfer to its Safe)
      if [[ "$(get_on_chain_service_state "$service_id")" == "DEPLOYED" && "$current_safe_owners" == "['$agent_address']" ]]; then
          echo "[Agent instance] Swapping Safe owner..."
          poetry run python "../scripts/swap_safe_owner.py" "$service_safe_address" "../$agent_pkey_path" "$operator_address" "$rpc" $password_argument
          if [[ $? -ne 0 ]]; then
              echo "Swapping Safe owner failed."
              exit 1
          fi
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
          if [[ $? -ne 0 ]]; then
              echo "Terminating service failed.\n$output"
              echo "Please, delete or rename the ./trader folder and try re-run this script again."
              exit 1
          fi
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
          if [[ $? -ne 0 ]]; then
              echo "Unbonding service failed.\n$output"
              echo "Please, delete or rename the ./trader folder and try re-run this script again."
              exit 1
          fi
      fi

      # update service
      if [ "$(get_on_chain_service_state "$service_id")" == "PRE_REGISTRATION" ]; then
          echo "[Service owner] Updating on-chain service $service_id..."
          nft="bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq"
          export cmd=""
          if [ "${USE_STAKING}" = true ]; then
              cost_of_bonding=$olas_balance_required_to_bond
              poetry run python "../scripts/update_service.py" "../$operator_pkey_path" "$nft" "$AGENT_ID" "$service_id" "$CUSTOM_OLAS_ADDRESS" "$cost_of_bonding" "packages/valory/services/trader/" "$rpc" $password_argument
          else
              cost_of_bonding=$xdai_balance_required_to_bond
              cmd="poetry run autonomy mint \
                  --skip-hash-check \
                  --use-custom-chain \
                  service packages/valory/services/trader/ \
                  --key \"../$operator_pkey_path\" $password_argument \
                  --nft $nft \
                  -a $AGENT_ID \
                  -n $n_agents \
                  -c $cost_of_bonding \
                  --threshold $n_agents \
                  --update \"$service_id\""
          fi
          output=$(eval "$cmd")
          if [[ $? -ne 0 ]]; then
              echo "Updating service failed.\n$output"
              echo "Please, delete or rename the ./trader folder and try re-run this script again."
              exit 1
          fi
      fi

      echo ""
      echo "Finished updating on-chain service $service_id."
  fi
fi


echo ""
echo "Ensuring on-chain service $service_id is in DEPLOYED state..."

if [ "$(get_on_chain_service_state "$service_id")" != "DEPLOYED" ]; then
    suggested_amount=25000000000000000
    ensure_minimum_balance "$operator_address" $suggested_amount "owner/operator's address"
fi

# activate service
if [ "$(get_on_chain_service_state "$service_id")" == "PRE_REGISTRATION" ]; then
    echo "[Service owner] Activating registration for on-chain service $service_id..."
    export cmd="poetry run autonomy service --use-custom-chain activate --key "../$operator_pkey_path" $password_argument "$service_id""
    if [ "${USE_STAKING}" = true ]; then
        minimum_olas_balance=$($PYTHON_CMD -c "print(int($olas_balance_required_to_bond) + int($olas_balance_required_to_stake))")
        echo "Your service is using staking. Therefore, you need to provide a total of $(wei_to_dai "$minimum_olas_balance") OLAS to your owner/operator's address:"
        echo "    $(wei_to_dai "$olas_balance_required_to_bond") OLAS for security deposit (service owner)"
        echo "        +"
        echo "    $(wei_to_dai "$olas_balance_required_to_stake") OLAS for slashable bond (operator)."
        echo ""
        ensure_erc20_balance "$operator_address" $minimum_olas_balance "owner/operator's address" $CUSTOM_OLAS_ADDRESS "OLAS"
        cmd+=" --token $CUSTOM_OLAS_ADDRESS"
    fi
    output=$(eval "$cmd")
    if [[ $? -ne 0 ]]; then
        echo "Activating service failed.\n$output"
        echo "Please, delete or rename the ./trader folder and try re-run this script again."
        exit 1
    fi
fi

# register agent instance
if [ "$(get_on_chain_service_state "$service_id")" == "ACTIVE_REGISTRATION" ]; then
    echo "[Operator] Registering agent instance for on-chain service $service_id..."
    export cmd="poetry run autonomy service --use-custom-chain register --key "../$operator_pkey_path" $password_argument "$service_id" -a $AGENT_ID -i "$agent_address""

    if [ "${USE_STAKING}" = true ]; then
        cmd+=" --token $CUSTOM_OLAS_ADDRESS"
    fi

    output=$(eval "$cmd")
    if [[ $? -ne 0 ]]; then
        echo "Registering agent instance failed.\n$output"
        echo "Please, delete or rename the ./trader folder and try re-run this script again."
        exit 1
    fi
fi

# deploy on-chain service
service_state="$(get_on_chain_service_state "$service_id")"
multisig_address="$(get_multisig_address "$service_id")"
if ( [ "$first_run" = "true" ] || [ "$multisig_address" == "$zero_address" ] ) && [ "$service_state" == "FINISHED_REGISTRATION" ]; then
    echo "[Service owner] Deploying on-chain service $service_id..."
    output=$(poetry run autonomy service --use-custom-chain deploy "$service_id" --key "../$operator_pkey_path" $password_argument)
    if [[ $? -ne 0 ]]; then
        echo "Deploying service failed.\n$output"
        echo "Please, delete or rename the ./trader folder and try re-run this script again."
        exit 1
    fi
elif [ "$service_state" == "FINISHED_REGISTRATION" ]; then
    echo "[Service owner] Deploying on-chain service $service_id..."
    output=$(poetry run autonomy service --use-custom-chain deploy "$service_id" --key "../$operator_pkey_path" $password_argument --reuse-multisig)
    if [[ $? -ne 0 ]]; then
        echo "Deploying service failed.\n$output"
        echo "Please, delete or rename the ./trader folder and try re-run this script again."
        exit 1
    fi
fi

# perform staking operations
# the following will stake the service in case it is not staked, and there are available rewards
# if the service is already staked, and there are no available rewards, it will unstake the service
if [ "${USE_STAKING}" = true ]; then
  perform_staking_ops
fi

# check state
service_state="$(get_on_chain_service_state "$service_id")"
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
export ON_CHAIN_SERVICE_ID=$service_id
export ALL_PARTICIPANTS='["'$agent_address'"]'
# This is the default market creator. Feel free to update with other market creators
export OMEN_CREATORS='["0x89c5cc945dd550BcFfb72Fe42BfF002429F46Fec"]'
export BET_AMOUNT_PER_THRESHOLD_000=0
export BET_AMOUNT_PER_THRESHOLD_010=0
export BET_AMOUNT_PER_THRESHOLD_020=0
export BET_AMOUNT_PER_THRESHOLD_030=0
export BET_AMOUNT_PER_THRESHOLD_040=0
export BET_AMOUNT_PER_THRESHOLD_050=0
export BET_AMOUNT_PER_THRESHOLD_060=0
export BET_AMOUNT_PER_THRESHOLD_070=0
export BET_AMOUNT_PER_THRESHOLD_080=30000000000000000
export BET_AMOUNT_PER_THRESHOLD_090=80000000000000000
export BET_AMOUNT_PER_THRESHOLD_100=100000000000000000
export BET_THRESHOLD=5000000000000000
export TRADING_STRATEGY=kelly_criterion
export PROMPT_TEMPLATE="Please take over the role of a Data Scientist to evaluate the given question. With the given question \"@{question}\" and the \`yes\` option represented by \`@{yes}\` and the \`no\` option represented by \`@{no}\`, what are the respective probabilities of \`p_yes\` and \`p_no\` occurring?"
export IRRELEVANT_TOOLS='["prediction-online-summarized-info", "prediction-online-sum-url-content", "prediction-online", "openai-text-davinci-002", "openai-text-davinci-003", "openai-gpt-3.5-turbo", "openai-gpt-4", "stabilityai-stable-diffusion-v1-5", "stabilityai-stable-diffusion-xl-beta-v2-2-2", "stabilityai-stable-diffusion-512-v2-1", "stabilityai-stable-diffusion-768-v2-1", "deepmind-optimization-strong", "deepmind-optimization", "claude-prediction-offline", "prediction-offline", "prediction-offline-sme"]'

service_dir="trader_service"
build_dir="abci_build"
directory="$service_dir/$build_dir"

suggested_amount=$suggested_top_up_default
ensure_minimum_balance "$agent_address" $suggested_amount "agent instance's address"

suggested_amount=500000000000000000
ensure_minimum_balance "$SAFE_CONTRACT_ADDRESS" $suggested_amount "service Safe's address" $WXDAI_ADDRESS

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
fi

# Build the deployment with a single agent
export OPEN_AUTONOMY_PRIVATE_KEY_PASSWORD="$password" && poetry run autonomy deploy build "../../$keys_json_path" --n $n_agents -ltm

cd ..

warm_start

add_volume_to_service "$PWD/trader_service/abci_build/docker-compose.yaml" "trader_abci_0" "/data" "$PWD/../$store/"
sudo chown -R $(whoami) "$PWD/../$store/"

# Run the deployment
export OPEN_AUTONOMY_PRIVATE_KEY_PASSWORD="$password" && poetry run autonomy deploy run --build-dir "$directory" --detach
