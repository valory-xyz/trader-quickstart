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

"""Claim earned OLAS"""

import argparse
import os
import requests
import sys
import textwrap
import json
from dotenv import dotenv_values, set_key, unset_key
from pathlib import Path
from typing import Any, Dict, List, Tuple
from web3 import Web3

SCRIPT_PATH = Path(__file__).resolve().parent
STORE_PATH = Path(SCRIPT_PATH, "..", ".trader_runner")
DOTENV_PATH = Path(STORE_PATH, ".env")
RPC_PATH = Path(STORE_PATH, "rpc.txt")
SERVICE_ID_PATH = Path(STORE_PATH, "service_id.txt")
SERVICE_SAFE_ADDRESS_PATH = Path(STORE_PATH, "service_safe_address.txt")
OWNER_KEYS_JSON_PATH = Path(STORE_PATH, "operator_keys.json")

OLAS_TOKEN_ADDRESS_GNOSIS = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
GNOSIS_CHAIN_ID = 100

STAKING_TOKEN_INSTANCE_ABI_PATH = Path(
    SCRIPT_PATH,
    "..",
    "trader",
    "packages",
    "valory",
    "contracts",
    "staking_token",
    "build",
    "StakingToken.json",
)
STAKING_TOKEN_IMPLEMENTATION_ABI_PATH = STAKING_TOKEN_INSTANCE_ABI_PATH

ERC20_ABI_PATH = Path(
    SCRIPT_PATH,
    "..",
    "trader",
    "packages",
    "valory",
    "contracts",
    "erc20",
    "build",
    "ERC20.json",
)

def _load_abi_from_file(path: Path) -> Dict[str, Any]:
    if not os.path.exists(path):
        print(
            "Error: Contract airtfacts not found. Please execute 'run_service.sh' before executing this script."
        )
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("abi")




def _erc20_balance(
    address: str,
    token_address: str = OLAS_TOKEN_ADDRESS_GNOSIS,
    token_name: str = "OLAS"
) -> int:
    """Get ERC20 balance"""
    rpc = RPC_PATH.read_text().strip()
    w3 = Web3(Web3.HTTPProvider(rpc))
    abi = _load_abi_from_file(ERC20_ABI_PATH)
    contract = w3.eth.contract(address=token_address, abi=abi)
    balance = contract.functions.balanceOf(address).call()
    return f"{balance / 10**18:.2f} {token_name}"

def _claim_rewards() -> None:
    env_file_vars = dotenv_values(DOTENV_PATH)
    staking_token_address = env_file_vars["CUSTOM_STAKING_ADDRESS"]
    service_id = int(SERVICE_ID_PATH.read_text().strip())

    rpc = RPC_PATH.read_text().strip()
    w3 = Web3(Web3.HTTPProvider(rpc))
    abi = _load_abi_from_file(STAKING_TOKEN_IMPLEMENTATION_ABI_PATH)
    staking_token_contract = w3.eth.contract(address=staking_token_address, abi=abi)

    owner_private_key = json.loads(OWNER_KEYS_JSON_PATH.read_text())[0]["private_key"]
    owner_address = Web3.to_checksum_address(w3.eth.account.from_key(owner_private_key).address)

    function = staking_token_contract.functions.claim(service_id)
    claim_transaction = function.build_transaction(
        {
            "chainId": GNOSIS_CHAIN_ID,
            "gas": 100000,
            "gasPrice": w3.to_wei("3", "gwei"),
            "nonce": w3.eth.get_transaction_count(owner_address),
        }
    )

    signed_tx = w3.eth.account.sign_transaction(claim_transaction, owner_private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"Claim done. Receipt: {tx_receipt}")



def main() -> None:
    "Main method"
    service_safe_address = SERVICE_SAFE_ADDRESS_PATH.read_text().strip()

    print(f"OLAS Balance on service Safe {service_safe_address}: {_erc20_balance(service_safe_address)}")
    _claim_rewards()

if __name__ == "__main__":
    main()