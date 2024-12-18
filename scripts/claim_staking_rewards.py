#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

import json
import os
import sys
from getpass import getpass
from pathlib import Path
from typing import Any, Dict, Optional

from aea.crypto.helpers import DecryptError, KeyIsIncorrect
from aea_ledger_ethereum.ethereum import EthereumCrypto
from dotenv import dotenv_values
from web3 import Web3


SCRIPT_PATH = Path(__file__).resolve().parent
STORE_PATH = Path(SCRIPT_PATH, "..", ".trader_runner")
DOTENV_PATH = Path(STORE_PATH, ".env")
RPC_PATH = Path(STORE_PATH, "rpc.txt")
SERVICE_ID_PATH = Path(STORE_PATH, "service_id.txt")
SERVICE_SAFE_ADDRESS_PATH = Path(STORE_PATH, "service_safe_address.txt")
OPERATOR_PKEY_PATH = Path(STORE_PATH, "operator_pkey.txt")
DEFAULT_ENCODING = "utf-8"

OLAS_TOKEN_ADDRESS_GNOSIS = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
GNOSIS_CHAIN_ID = 100
DEFAULT_GAS = 100000
SAFE_WEBAPP_URL = "https://app.safe.global/home?safe=gno:"

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


def _is_keystore(pkeypath: Path) -> bool:
    try:
        with open(pkeypath, "r", encoding="utf-8") as f:
            json.load(f)
        return True
    except json.JSONDecodeError:
        return False


def _load_abi_from_file(path: Path) -> Dict[str, Any]:
    if not os.path.exists(path):
        print(
            "Error: Contract airtfacts not found. Please execute 'run_service.sh' before executing this script."
        )
        sys.exit(1)

    with open(path, "r", encoding=DEFAULT_ENCODING) as f:
        data = json.load(f)

    return data.get("abi")


def _erc20_balance(
    address: str,
    token_address: str = OLAS_TOKEN_ADDRESS_GNOSIS,
    token_name: str = "OLAS",
    decimal_precision: int = 2,
) -> str:
    """Get ERC20 balance"""
    rpc = RPC_PATH.read_text(encoding=DEFAULT_ENCODING).strip()
    w3 = Web3(Web3.HTTPProvider(rpc))
    abi = _load_abi_from_file(ERC20_ABI_PATH)
    contract = w3.eth.contract(address=token_address, abi=abi)
    balance = contract.functions.balanceOf(address).call()
    return f"{balance / 10**18:.{decimal_precision}f} {token_name}"


def _claim_rewards(  # pylint: disable=too-many-locals
    password: Optional[str] = None,
) -> None:
    service_safe_address = SERVICE_SAFE_ADDRESS_PATH.read_text(
        encoding=DEFAULT_ENCODING
    ).strip()
    print(
        f"OLAS Balance of service Safe {service_safe_address}: {_erc20_balance(service_safe_address)}"
    )

    env_file_vars = dotenv_values(DOTENV_PATH)
    staking_token_address = env_file_vars["CUSTOM_STAKING_ADDRESS"]
    service_id = int(SERVICE_ID_PATH.read_text(encoding=DEFAULT_ENCODING).strip())

    rpc = RPC_PATH.read_text(encoding=DEFAULT_ENCODING).strip()
    w3 = Web3(Web3.HTTPProvider(rpc))
    abi = _load_abi_from_file(STAKING_TOKEN_IMPLEMENTATION_ABI_PATH)
    staking_token_contract = w3.eth.contract(address=staking_token_address, abi=abi)

    try:
        ethereum_crypto = EthereumCrypto(OPERATOR_PKEY_PATH, password=password)
        operator_address = ethereum_crypto.address
        operator_pkey = ethereum_crypto.private_key
    except DecryptError:
        print(
            f"Could not decrypt key {OPERATOR_PKEY_PATH}. Please verify if your key file is password-protected, and if the provided password is correct (passwords are case-sensitive)."
        )
        sys.exit(1)
    except KeyIsIncorrect:
        print(f"Error decoding key file {OPERATOR_PKEY_PATH}.")
        sys.exit(1)

    function = staking_token_contract.functions.claim(service_id)
    claim_transaction = function.build_transaction(
        {
            "chainId": GNOSIS_CHAIN_ID,
            "gas": DEFAULT_GAS,
            "gasPrice": w3.to_wei("3", "gwei"),
            "nonce": w3.eth.get_transaction_count(operator_address),
        }
    )

    signed_tx = w3.eth.account.sign_transaction(claim_transaction, operator_pkey)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"Claim transaction done. Hash: {tx_hash.hex()}")

    if "status" in tx_receipt and tx_receipt["status"] == 0:
        print(
            "WARNING: The transaction was reverted. This may be caused because your service does not have rewards to claim."
        )
    else:
        print("")
        print(f"Claimed OLAS transferred to your service Safe {service_safe_address}")

    print("")
    print(
        f"You can use your Owner/Operator wallet (address {operator_address}) to connect your Safe at {SAFE_WEBAPP_URL}{service_safe_address}."
    )


def main() -> None:
    """Main method."""
    print("---------------------")
    print("Claim staking rewards")
    print("---------------------")
    print("")
    print(
        "This script will claim the OLAS staking rewards accrued in the current staking contract and transfer them to your service Safe."
    )
    _continue = input("Do you want to continue (yes/no)? ").strip().lower()

    if _continue not in ("y", "yes"):
        sys.exit(0)

    print("")

    password = None
    if _is_keystore(OPERATOR_PKEY_PATH):
        print("Enter your password")
        print("-------------------")
        print("Your key files are protected with a password.")
        password = getpass("Please, enter your password: ").strip()
        print("")

    _claim_rewards(password)


if __name__ == "__main__":
    main()
