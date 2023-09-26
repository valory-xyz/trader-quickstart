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

"""This script gets the service hash of a specific service on the registry."""

import json
from typing import List

import requests
from web3 import Web3, HTTPProvider

RPC_PATH = "../.trader_runner/rpc.txt"
SERVICE_ID_PATH = "../.trader_runner/service_id.txt"
REGISTRY_L2_JSON = "../contracts/ServiceRegistryL2.json"
REGISTRY_ADDRESS = "0x9338b5153AE39BB89f50468E608eD9d764B755fD"
AUTONOLAS_GATEWAY = "https://gateway.autonolas.tech/ipfs/"
URI_HASH_POSITION = 7


def _get_hash_from_ipfs(hash_decoded: str) -> str:
    """Get the service's `bafybei` hash from IPFS."""
    res = requests.get(f"{AUTONOLAS_GATEWAY}{hash_decoded}")
    if res.status_code == 200:
        return res.json().get("code_uri", "")[URI_HASH_POSITION:]
    raise ValueError(f"Something went wrong while trying to get the code uri from IPFS: {res}")


def get_hash() -> str:
    """Get the service's hash."""
    contract_data = json.loads(registry_l2_json)
    abi = contract_data.get('abi', [])

    w3 = Web3(HTTPProvider(rpc))
    contract_instance = w3.eth.contract(address=REGISTRY_ADDRESS, abi=abi)
    hash_encoded = contract_instance.functions.getService(int(service_id)).call()[2]
    hash_decoded = f"f01701220{hash_encoded.hex()}"
    hash_ = _get_hash_from_ipfs(hash_decoded)

    return hash_


def _parse_args() -> List[str]:
    """Parse the RPC and service id."""
    params = []
    for path in (RPC_PATH, SERVICE_ID_PATH, REGISTRY_L2_JSON):
        with open(path) as file:
            params.append(file.read())
    return params


if __name__ == "__main__":
    rpc, service_id, registry_l2_json = _parse_args()
    print(get_hash())
