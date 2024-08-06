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
import textwrap
from dotenv import dotenv_values, set_key, unset_key
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent
STORE_PATH = Path(SCRIPT_PATH, "..", ".trader_runner")
DOTENV_PATH = Path(STORE_PATH, ".env")


def _fetch_json(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


staking_programs = {
    "quickstart_beta_hobbyist": {
        "name": "Quickstart Beta - Hobbyist",
        "description": "The Quickstart Beta - Hobbyist staking contract offers 100 slots for operators running Olas Predict agents with the quickstart. It is designed as a step up from Coastal Staker Expeditions, requiring 100 OLAS for staking. The rewards are also more attractive than with Coastal Staker Expeditions.",
        "deployment": _fetch_json("https://raw.githubusercontent.com/valory-xyz/autonolas-staking-programmes/e8c023886ebf1f10f2ccd3519a934c1f2590b78d/scripts/deployment/globals_gnosis_mainnet_qs_beta_hobbyist.json"),
        "stakingProxyAddress": "0x389B46c259631Acd6a69Bde8B6cEe218230bAE8C"
    },
    "quickstart_beta_expert": {
        "name": "Quickstart Beta - Expert",
        "description": "The Quickstart Beta - Expert staking contract offers 20 slots for operators running Olas Predict agents with the quickstart. It is designed for professional agent operators, requiring 1000 OLAS for staking. The rewards are proportional to the Quickstart Beta - Hobbyist.",
        "deployment": _fetch_json("https://raw.githubusercontent.com/valory-xyz/autonolas-staking-programmes/e8c023886ebf1f10f2ccd3519a934c1f2590b78d/scripts/deployment/globals_gnosis_mainnet_qs_beta_expert.json"),
        "stakingProxyAddress": "0x5344B7DD311e5d3DdDd46A4f71481bD7b05AAA3e"
    }
}

no_staking = {
    "name": "No staking",
    "description": "No staking",
    "deployment": {
        "gnosisSafeAddress": "0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552",
        "gnosisSafeProxyFactoryAddress": "0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2",
        "serviceRegistryAddress": "0x9338b5153AE39BB89f50468E608eD9d764B755fD",
        "serviceRegistryTokenUtilityAddress": "0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8",
        "olasAddress": "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f",
        "stakingTokenAddress": "0xEa00be6690a871827fAfD705440D20dd75e67AB1",
        "agentMechAddress": "0x77af31De935740567Cf4fF1986D04B2c964A786a",
        "mechActivityCheckerAddress": "0x87E6a97bD97D41904B1125A014B16bec50C6A89D",
        "stakingFactoryAddress": "0xb0228CA253A88Bc8eb4ca70BCAC8f87b381f4700",
        "stakingParams": {
            "agentIds": [
                "25"
            ],
            "serviceRegistry": "0x9338b5153AE39BB89f50468E608eD9d764B755fD",
            "activityChecker": "0x87E6a97bD97D41904B1125A014B16bec50C6A89D"
        },
        "stakingTokenInstanceAddress": ""
        },
    "stakingProxyAddress": "0x0000000000000000000000000000000000000000"
}


def _prompt_use_staking():
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


def _prompt_select_staking_program():
    env_file_vars = dotenv_values(DOTENV_PATH)

    if 'USE_STAKING' not in env_file_vars:
        print("'USE_STAKING' is not defined.")
        return

    if not env_file_vars.get('USE_STAKING').lower() == "true":
        print("'USE_STAKING' is not set to 'true'.")
        selected_program = no_staking
    elif 'STAKING_PROGRAM' in env_file_vars:
        print("The staking program is already selected.")
        selected_key = env_file_vars.get('STAKING_PROGRAM')
    else:
        print("Select a staking program")
        print("------------------------")
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

    selected_program = staking_programs[selected_key]
    print(f"Selected staking program: {selected_program['name']}")

    print("Setting the staking program variables in the .env file")
    set_key(dotenv_path=DOTENV_PATH, key_to_set="STAKING_PROGRAM", value_to_set=selected_key)
    set_key(dotenv_path=DOTENV_PATH, key_to_set="CUSTOM_SERVICE_REGISTRY_ADDRESS", value_to_set=selected_program["deployment"]["serviceRegistryAddress"])
    set_key(dotenv_path=DOTENV_PATH, key_to_set="CUSTOM_STAKING_ADDRESS", value_to_set=selected_program["stakingProxyAddress"])
    set_key(dotenv_path=DOTENV_PATH, key_to_set="CUSTOM_OLAS_ADDRESS", value_to_set=selected_program["deployment"]["olasAddress"])
    set_key(dotenv_path=DOTENV_PATH, key_to_set="CUSTOM_SERVICE_REGISTRY_TOKEN_UTILITY_ADDRESS", value_to_set=selected_program["deployment"]["serviceRegistryTokenUtilityAddress"])
    set_key(dotenv_path=DOTENV_PATH, key_to_set="MECH_CONTRACT_ADDRESS", value_to_set=selected_program["deployment"]["agentMechAddress"])
    set_key(dotenv_path=DOTENV_PATH, key_to_set="MECH_ACTIVITY_CHECKER_CONTRACT", value_to_set=selected_program["deployment"]["mechActivityCheckerAddress"])
    set_key(dotenv_path=DOTENV_PATH, key_to_set="AGENT_ID", value_to_set=selected_program["deployment"]["stakingParams"]["agentIds"][0], quote_mode="never")
    print("")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Set up staking configuration.')
    parser.add_argument('--reset', action='store_true', help='Reset USE_STAKING and STAKING_PROGRAM in .env file')
    args = parser.parse_args()

    if args.reset:
        unset_key(dotenv_path=DOTENV_PATH, key_to_unset="USE_STAKING")
        unset_key(dotenv_path=DOTENV_PATH, key_to_unset="STAKING_PROGRAM")
        print("Environment variables USE_STAKING and STAKING_PROGRAM have been reset.")
        print("")

    _prompt_use_staking()
    _prompt_select_staking_program()
