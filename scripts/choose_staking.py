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


def _fetch_json(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


# Information stored in the "deployment" key is used only to retrieve "stakingTokenInstanceAddress" (proxy)
# and "stakingTokenAddress" (implementation). The rest of the parameters are read on-chain.
staking_programs = {
    "no_staking": {
        "name": "No staking",
        "description": "Your Olas Predict agent will still actively participate in prediction markets, but it will not be staked within any staking program.",
        "deployment": {
            "stakingTokenInstanceAddress": "0x43fB32f25dce34EB76c78C7A42C8F40F84BCD237",
            "stakingTokenAddress": "0x43fB32f25dce34EB76c78C7A42C8F40F84BCD237",
        }
    },
    "quickstart_beta_hobbyist": {
        "name": "Quickstart Beta - Hobbyist",
        "description": "The Quickstart Beta - Hobbyist staking contract offers 100 slots for operators running Olas Predict agents with the quickstart. It is designed as a step up from Coastal Staker Expeditions, requiring 100 OLAS for staking. The rewards are also more attractive than with Coastal Staker Expeditions.",
        "deployment": _fetch_json("https://raw.githubusercontent.com/valory-xyz/autonolas-staking-programmes/main/scripts/deployment/globals_gnosis_mainnet_qs_beta_hobbyist.json"),
    },
    "quickstart_beta_expert": {
        "name": "Quickstart Beta - Expert",
        "description": "The Quickstart Beta - Expert staking contract offers 20 slots for operators running Olas Predict agents with the quickstart. It is designed for professional agent operators, requiring 1000 OLAS for staking. The rewards are proportional to the Quickstart Beta - Hobbyist.",
        "deployment": _fetch_json("https://raw.githubusercontent.com/valory-xyz/autonolas-staking-programmes/main/scripts/deployment/globals_gnosis_mainnet_qs_beta_expert.json"),
    },
    "quickstart_alpha_coastal": {
        "name": "Quickstart Alpha - Coastal (Deprecated)",
        "description": "The Quickstart Alpha - Coastal is a deprecated staking contract. It offers 100 slots for operators running Olas Predict agents with the quickstart. It requires 20 OLAS for staking.",
        "deployment": {
            "stakingTokenInstanceAddress": "0x43fB32f25dce34EB76c78C7A42C8F40F84BCD237",
            "stakingTokenAddress": "0x43fB32f25dce34EB76c78C7A42C8F40F84BCD237",
        }
    }
}


def _prompt_use_staking() -> None:
    env_file_vars = dotenv_values(DOTENV_PATH)

    if 'USE_STAKING' in env_file_vars:
        return

    print("Use staking?")
    print("------------")

    while True:
        use_staking = input("Do you want to stake this service? (yes/no): ").strip().lower()

        if use_staking in ('yes', 'y'):
            use_staking_value = "true"
            break
        elif use_staking in ('no', 'n'):
            use_staking_value = "false"
            break
        else:
            print("Please enter 'yes' or 'no'.")

    set_key(dotenv_path=DOTENV_PATH, key_to_set="USE_STAKING", value_to_set=use_staking_value, quote_mode="never")
    print("")


def _prompt_select_staking_program() -> None:
    env_file_vars = dotenv_values(DOTENV_PATH)

    selected_key = None
    if 'STAKING_PROGRAM' in env_file_vars:
        print("The staking program is already selected.")

        selected_key = env_file_vars.get('STAKING_PROGRAM')
        if selected_key not in staking_programs:
            selected_key = None
            print(f"WARNING: Selected staking program {selected_key} is unknown.")
            print("")

    if not selected_key:
        print("Please, select your staking program preference")
        print("----------------------------------------------")
        program_keys = list(staking_programs.keys())
        for index, key in enumerate(program_keys):
            program = staking_programs[key]
            wrapped_description = textwrap.fill(program['description'], width=80, initial_indent='   ', subsequent_indent='   ')
            print(f"{index + 1}) {program['name']}\n{wrapped_description}\n")

        while True:
            try:
                choice = int(input(f"Enter your choice (1 - {len(program_keys)}): ")) - 1
                if not (0 <= choice < len(program_keys)):
                    raise ValueError
                selected_key = program_keys[choice]
                break
            except ValueError:
                print(f"Please enter a valid option (1 - {len(program_keys)}).")

    selected_staking_program_data = staking_programs[selected_key]
    print(f"Selected staking program: {selected_staking_program_data['name']}")

    print("Populating the staking program variables in the .env file")
    _populate_env_file_variables(selected_key)
    print("")


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


def _populate_env_file_variables(staking_program_key: str) -> None:

    staking_program_data = staking_programs.get(staking_program_key)

    with open(RPC_PATH, 'r', encoding="utf-8") as file:
        rpc = file.read().strip()

    w3 = Web3(Web3.HTTPProvider(rpc))
    staking_token_instance_address = staking_program_data["deployment"]["stakingTokenInstanceAddress"]  # Instance/proxy
    staking_token_address = staking_program_data["deployment"]["stakingTokenAddress"]  # Implementation
    abi = _get_abi(staking_token_address)
    staking_token_contract = w3.eth.contract(address=staking_token_instance_address, abi=abi)

    agent_id = staking_token_contract.functions.agentIds(0).call()
    service_registry = staking_token_contract.functions.serviceRegistry().call()
    staking_token = staking_token_contract.functions.stakingToken().call()
    service_registry_token_utility = staking_token_contract.functions.serviceRegistryTokenUtility().call()

    if 'activityChecker' in [func.fn_name for func in staking_token_contract.all_functions()]:
        activity_checker = staking_token_contract.functions.activityChecker().call()
        abi = _get_abi(activity_checker)
        activity_checker_contract = w3.eth.contract(address=activity_checker, abi=abi)
        agent_mech = activity_checker_contract.functions.agentMech().call()
    else:
        activity_checker = '0x0000000000000000000000000000000000000000'
        agent_mech = staking_token_contract.functions.agentMech().call()

    if staking_program_key == "no_staking":
        set_key(dotenv_path=DOTENV_PATH, key_to_set="USE_STAKING", value_to_set="false", quote_mode="never")
    else:
        set_key(dotenv_path=DOTENV_PATH, key_to_set="USE_STAKING", value_to_set="true", quote_mode="never")

    set_key(dotenv_path=DOTENV_PATH, key_to_set="STAKING_PROGRAM", value_to_set=staking_program_key, quote_mode="never")
    set_key(dotenv_path=DOTENV_PATH, key_to_set="CUSTOM_STAKING_ADDRESS", value_to_set=staking_token_instance_address, quote_mode="never")
    set_key(dotenv_path=DOTENV_PATH, key_to_set="AGENT_ID", value_to_set=agent_id, quote_mode="never")
    set_key(dotenv_path=DOTENV_PATH, key_to_set="CUSTOM_SERVICE_REGISTRY_ADDRESS", value_to_set=service_registry, quote_mode="never")
    set_key(dotenv_path=DOTENV_PATH, key_to_set="CUSTOM_OLAS_ADDRESS", value_to_set=staking_token, quote_mode="never")
    set_key(dotenv_path=DOTENV_PATH, key_to_set="CUSTOM_SERVICE_REGISTRY_TOKEN_UTILITY_ADDRESS", value_to_set=service_registry_token_utility, quote_mode="never")
    set_key(dotenv_path=DOTENV_PATH, key_to_set="MECH_ACTIVITY_CHECKER_CONTRACT", value_to_set=activity_checker, quote_mode="never")
    set_key(dotenv_path=DOTENV_PATH, key_to_set="MECH_CONTRACT_ADDRESS", value_to_set=agent_mech, quote_mode="never")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Set up staking configuration.')
    parser.add_argument('--reset', action='store_true', help='Reset USE_STAKING and STAKING_PROGRAM in .env file')
    args = parser.parse_args()

    if args.reset:
        unset_key(dotenv_path=DOTENV_PATH, key_to_unset="USE_STAKING")
        unset_key(dotenv_path=DOTENV_PATH, key_to_unset="STAKING_PROGRAM")
        print("Environment variables USE_STAKING and STAKING_PROGRAM have been reset.")
        print("")

    _prompt_select_staking_program()
