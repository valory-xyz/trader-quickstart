#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022-2023 Valory AG
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
import json
import sys
from typing import List
from web3 import Web3


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Get agent bond from service registry token utility contract.")
    parser.add_argument('contract_address', type=str, help='Service registry token utility contract address')
    parser.add_argument('service_id', type=int, help='Service ID')
    parser.add_argument('agent_id', type=int, help='Agent ID')
    parser.add_argument('rpc', type=str, help='RPC')
    args = parser.parse_args()

    contract_address = args.contract_address
    service_id = args.service_id
    agent_id = args.agent_id
    rpc = args.rpc

    w3 = Web3(Web3.HTTPProvider(rpc))
    abi = _get_abi(contract_address)
    contract = w3.eth.contract(address=contract_address, abi=abi)
    agent_bond = contract.functions.getAgentBond(service_id, agent_id).call()

    print(agent_bond)


if __name__ == "__main__":
    main()
