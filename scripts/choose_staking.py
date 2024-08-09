#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

import argparse
import requests
import sys
import textwrap
import json
from dotenv import dotenv_values, set_key, unset_key
from pathlib import Path
from typing import Any, Dict, List
from web3 import Web3
from eth_utils import keccak

SCRIPT_PATH = Path(__file__).resolve().parent
STORE_PATH = Path(SCRIPT_PATH, "..", ".trader_runner")
DOTENV_PATH = Path(STORE_PATH, ".env")
RPC_PATH = Path(STORE_PATH, "rpc.txt")

IPFS_ADDRESS = "https://gateway.autonolas.tech/ipfs/f01701220{}"
NEVERMINED_MECH_CONTRACT_ADDRESS = "0x327E26bDF1CfEa50BFAe35643B23D5268E41F7F9"
NEVERMINED_AGENT_REGISTRY_ADDRESS = "0xAed729d4f4b895d8ca84ba022675bB0C44d2cD52"
NEVERMINED_MECH_REQUEST_PRICE = "0"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
DEPRECATED_TEXT = "(DEPRECATED)"


def _fetch_json(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


# Information stored in the "deployment" key is used only to retrieve "stakingTokenInstanceAddress" (proxy)
# and "stakingTokenAddress" (implementation). The rest of the parameters are read on-chain.
STAKING_PROGRAMS = {
    "no_staking": {
        "name": "No staking",
        "description": "Your Olas Predict agent will still actively participate in prediction markets, but it will not be staked within any staking program.",
        "deployment": {
            "stakingTokenAddress": "0x43fB32f25dce34EB76c78C7A42C8F40F84BCD237",
            "stakingTokenInstanceAddress": "0x43fB32f25dce34EB76c78C7A42C8F40F84BCD237"
        }
    },
    "quickstart_beta_hobbyist": {
        "name": "Quickstart Beta - Hobbyist",
        "description": "The Quickstart Beta - Hobbyist staking contract offers 100 slots for operators running Olas Predict agents with the quickstart. It is designed as a step up from Coastal Staker Expeditions, requiring 100 OLAS for staking. The rewards are also more attractive than with Coastal Staker Expeditions.",
        # https://github.com/valory-xyz/autonolas-staking-programmes/blob/main/scripts/deployment/globals_gnosis_mainnet_qs_beta_hobbyist.json
        "deployment": {
            "stakingTokenAddress": "0xEa00be6690a871827fAfD705440D20dd75e67AB1",
            "stakingTokenInstanceAddress": "0x389B46c259631Acd6a69Bde8B6cEe218230bAE8C"
        }
    },
    "quickstart_beta_expert": {
        "name": "Quickstart Beta - Expert",
        "description": "The Quickstart Beta - Expert staking contract offers 20 slots for operators running Olas Predict agents with the quickstart. It is designed for professional agent operators, requiring 1000 OLAS for staking. The rewards are proportional to the Quickstart Beta - Hobbyist.",
        # https://github.com/valory-xyz/autonolas-staking-programmes/blob/main/scripts/deployment/globals_gnosis_mainnet_qs_beta_expert.json
        "deployment": {
            "stakingTokenAddress": "0xEa00be6690a871827fAfD705440D20dd75e67AB1",
            "stakingTokenInstanceAddress": "0x5344B7DD311e5d3DdDd46A4f71481bD7b05AAA3e"
        }
    },
    "quickstart_alpha_coastal": {
        "name": "Quickstart Alpha - Coastal",
        "description": "The Quickstart Alpha - Coastal offers 100 slots for operators running Olas Predict agents with the quickstart. It requires 20 OLAS for staking.",
        "deployment": {
            "stakingTokenAddress": "0x43fB32f25dce34EB76c78C7A42C8F40F84BCD237",
            "stakingTokenInstanceAddress": "0x43fB32f25dce34EB76c78C7A42C8F40F84BCD237"
        }
    }
}

DEPRECATED_STAKING_PROGRAMS = {
    "quickstart_alpha_everest": {
        "name": "Quickstart Alpha - Everest",
        "description": "",
        "deployment": {
            "stakingTokenAddress": "0x5add592ce0a1B5DceCebB5Dcac086Cd9F9e3eA5C",
            "stakingTokenInstanceAddress": "0x5add592ce0a1B5DceCebB5Dcac086Cd9F9e3eA5C"
        }
    },
    "quickstart_alpha_alpine": {
        "name": "Quickstart Alpha - Alpine",
        "description": "",
        "deployment": {
            "stakingTokenAddress": "0x2Ef503950Be67a98746F484DA0bBAdA339DF3326",
            "stakingTokenInstanceAddress": "0x2Ef503950Be67a98746F484DA0bBAdA339DF3326"
        }
    }
}


def _prompt_select_staking_program() -> str:
    env_file_vars = dotenv_values(DOTENV_PATH)

    program_id = None
    if 'STAKING_PROGRAM' in env_file_vars:
        print("The staking program is already selected.")

        program_id = env_file_vars.get('STAKING_PROGRAM')
        if program_id not in STAKING_PROGRAMS:
            print(f"WARNING: Selected staking program {program_id} is unknown.")
            print("")
            program_id = None

    if not program_id:
        print("Please, select your staking program preference")
        print("----------------------------------------------")
        ids = list(STAKING_PROGRAMS.keys())
        for index, key in enumerate(ids):
            program = STAKING_PROGRAMS[key]            
            wrapped_description = textwrap.fill(program['description'], width=80, initial_indent='   ', subsequent_indent='   ')
            print(f"{index + 1}) {program['name']}\n{wrapped_description}\n")

        while True:
            try:
                choice = int(input(f"Enter your choice (1 - {len(ids)}): ")) - 1
                if not (0 <= choice < len(ids)):
                    raise ValueError
                program_id = ids[choice]
                break
            except ValueError:
                print(f"Please enter a valid option (1 - {len(ids)}).")

    print(f"Selected staking program: {STAKING_PROGRAMS[program_id]['name']}")
    print("")
    return program_id


def _get_abi(contract_address: str) -> List:
    contract_abi_url = "https://gnosis.blockscout.com/api/v2/smart-contracts/{contract_address}"
    response = requests.get(contract_abi_url.format(contract_address=contract_address)).json()

    if "result" in response:
        result = response["result"]
        try:
            abi = json.loads(result)
        except json.JSONDecodeError:
            print("Error: Failed to parse 'result' field as JSON")
            sys.exit(1)
    else:
        abi = response.get("abi")

    return abi if abi else []


def _get_staking_env_variables(program_id: str) -> Dict[str, str]:
    staking_program_data = STAKING_PROGRAMS.get(program_id)

    with open(RPC_PATH, 'r', encoding="utf-8") as file:
        rpc = file.read().strip()

    w3 = Web3(Web3.HTTPProvider(rpc))
    staking_token_instance_address = staking_program_data["deployment"]["stakingTokenInstanceAddress"]  # Instance/proxy
    staking_token_address = staking_program_data["deployment"]["stakingTokenAddress"]  # Implementation
    abi = _get_abi(staking_token_address)
    staking_token_contract = w3.eth.contract(address=staking_token_instance_address, abi=abi)

    agent_id = 14 # staking_token_contract.functions.agentIds(0).call()
    service_registry = staking_token_contract.functions.serviceRegistry().call()
    staking_token = staking_token_contract.functions.stakingToken().call()
    service_registry_token_utility = staking_token_contract.functions.serviceRegistryTokenUtility().call()
    min_staking_deposit = staking_token_contract.functions.minStakingDeposit().call()
    min_staking_bond = min_staking_deposit

    if 'activityChecker' in [func.fn_name for func in staking_token_contract.all_functions()]:
        activity_checker = staking_token_contract.functions.activityChecker().call()
        abi = _get_abi(activity_checker)
        activity_checker_contract = w3.eth.contract(address=activity_checker, abi=abi)
        agent_mech = activity_checker_contract.functions.agentMech().call()
    else:
        activity_checker = ZERO_ADDRESS
        agent_mech = staking_token_contract.functions.agentMech().call()

    if program_id == "no_staking":
        use_staking = "false"
    else:
        use_staking = "true"

    return {
        "USE_STAKING": use_staking,
        "STAKING_PROGRAM": program_id,
        "CUSTOM_STAKING_ADDRESS": staking_token_instance_address,
        "AGENT_ID": agent_id,
        "CUSTOM_SERVICE_REGISTRY_ADDRESS": service_registry,
        "CUSTOM_OLAS_ADDRESS": staking_token,
        "CUSTOM_SERVICE_REGISTRY_TOKEN_UTILITY_ADDRESS": service_registry_token_utility,
        "MECH_ACTIVITY_CHECKER_CONTRACT": activity_checker,
        "MECH_CONTRACT_ADDRESS": agent_mech,
        "MIN_STAKING_DEPOSIT_OLAS": min_staking_deposit,
        "MIN_STAKING_BOND_OLAS": min_staking_bond
    }


def _set_dotenv_file_variables(env_vars: Dict[str, str]) -> None:
    for key, value in env_vars.items():
        if value:
            set_key(dotenv_path=DOTENV_PATH, key_to_set=key, value_to_set=value, quote_mode="never")
        else:
            unset_key(dotenv_path=DOTENV_PATH, key_to_unset=key)


def _get_nevermined_env_variables() -> Dict[str, str]:
    env_file_vars = dotenv_values(DOTENV_PATH)
    use_nevermined = False

    if 'USE_NEVERMINED' not in env_file_vars:
        set_key(dotenv_path=DOTENV_PATH, key_to_set="USE_NEVERMINED", value_to_set="false", quote_mode="never")
    elif env_file_vars.get('USE_NEVERMINED').strip() not in ("True", "true"):
        set_key(dotenv_path=DOTENV_PATH, key_to_set="USE_NEVERMINED", value_to_set="false", quote_mode="never")
    else:
        use_nevermined = True

    if use_nevermined:
        print("A Nevermined subscription will be used to pay for the mech requests.")
        return {
            "MECH_CONTRACT_ADDRESS": NEVERMINED_MECH_CONTRACT_ADDRESS,
            "AGENT_REGISTRY_ADDRESS": NEVERMINED_AGENT_REGISTRY_ADDRESS,
            "MECH_REQUEST_PRICE": NEVERMINED_MECH_REQUEST_PRICE
        }
    else:
        print("No Nevermined subscription set.")
        return {
            "AGENT_REGISTRY_ADDRESS": "",
            "MECH_REQUEST_PRICE": ""
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up staking configuration.")
    parser.add_argument("--reset", action="store_true", help="Reset USE_STAKING and STAKING_PROGRAM in .env file")
    args = parser.parse_args()

    if args.reset:
        unset_key(dotenv_path=DOTENV_PATH, key_to_unset="USE_STAKING")
        unset_key(dotenv_path=DOTENV_PATH, key_to_unset="STAKING_PROGRAM")
        print(f"Environment variables USE_STAKING and STAKING_PROGRAM have been reset in '{DOTENV_PATH}'.")
        print("You can now execute './run_service.sh' and select a different staking program.")
        print("")
        return

    program_id = _prompt_select_staking_program()

    print("Populating staking program variables in the .env file")
    print("")
    staking_env_variables = _get_staking_env_variables(program_id)
    _set_dotenv_file_variables(staking_env_variables)

    print("Populating Nevermined variables in the .env file")
    print("")
    nevermined_env_variables = _get_nevermined_env_variables()
    _set_dotenv_file_variables(nevermined_env_variables)


if __name__ == "__main__":
    main()
