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

"""This script swaps ownership of a Safe with a single owner."""

import argparse
import sys
import traceback
import typing
from pathlib import Path

from aea.contracts.base import Contract
from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto
from eth_typing import HexStr

from packages.valory.contracts.erc20.contract import (
    ERC20,
)
from packages.valory.contracts.service_staking_token.contract import (
    ServiceStakingTokenContract,
)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ZERO_ETH = 0

ContractType = typing.TypeVar("ContractType")

GAS_PARAMS = {
    "maxFeePerGas": 30_000_000_000,
    "maxPriorityFeePerGas": 3_000_000_000,
    "gas": 100_000,
}

def load_contract(ctype: ContractType) -> ContractType:
    """Load contract."""
    *parts, _ = ctype.__module__.split(".")
    path = "/".join(parts)
    return Contract.from_dir(directory=path)


def get_approval_tx(token: str, spender: str, amount: int) -> typing.Dict[str, typing.Any]:
    """Get approval tx"""
    approval_tx_data = erc20.build_approval_tx(
        ledger_api,
        token,
        spender,
        amount,
    ).pop('data')
    approval_tx = {
        "data": approval_tx_data,
        "to": token,
        "value": ZERO_ETH,
    }
    return approval_tx


def get_balances(token: str, owner: str) -> typing.Tuple[int, int]:
    """Returns the native and token balance of owner."""
    balances = erc20.check_balance(ledger_api, token, owner)
    token_balance, native_balance = balances.pop("token"), balances.pop("wallet")
    return token_balance, native_balance


def send_tx(crypto: EthereumCrypto, raw_tx: typing.Dict[str, typing.Any]) -> str:
    """Send transaction."""
    raw_tx = {
        **raw_tx,
        **GAS_PARAMS,
        "from": crypto.address,
        "nonce": ledger_api.api.eth.get_transaction_count(crypto.address),
        "chainId": ledger_api.api.eth.chain_id,
    }
    signed_tx = crypto.sign_transaction(raw_tx)
    tx_digest = typing.cast(
        str, ledger_api.send_signed_transaction(signed_tx, raise_on_try=True)
    )
    return tx_digest


def send_tx_and_wait_for_receipt(crypto: EthereumCrypto, raw_tx: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
    """Send transaction and wait for receipt."""
    tx_digest = HexStr(send_tx(crypto, raw_tx))
    receipt = ledger_api.api.eth.wait_for_transaction_receipt(tx_digest)
    if receipt["status"] != 1:
        raise ValueError("Transaction failed. Receipt:", receipt)
    return receipt


if __name__ == "__main__":
    try:
        print(f"  - Starting {Path(__file__).name} script...")

        parser = argparse.ArgumentParser(
            description="Swap ownership of a Safe with a single owner on the Gnosis chain."
        )
        parser.add_argument(
            "service_id",
            type=int,
            help="The on-chain service id.",
        )
        parser.add_argument(
            "service_registry_address",
            type=str,
            help="The service registry contract address.",
        )
        parser.add_argument(
            "operator_private_key_path",
            type=str,
            help="Path to the file containing the service operator's Ethereum private key",
        )
        parser.add_argument(
            "olas_address",
            type=str,
            help="The address of the OLAS token.",
        )
        parser.add_argument(
            "minimum_olas_balance",
            type=int,
            help="The minimum OLAS balance required for agent registration.",
        )
        parser.add_argument("rpc", type=str, help="RPC for the Gnosis chain")
        args = parser.parse_args()

        ledger_api = EthereumApi(address=args.rpc)
        owner_crypto = EthereumCrypto(
            private_key_path=args.operator_private_key_path
        )
        staking_contract = typing.cast(
            typing.Type[ServiceStakingTokenContract],
            load_contract(ServiceStakingTokenContract)
        )
        erc20 = typing.cast(typing.Type[ERC20], load_contract(ERC20))
        token_balance, native_balance = get_balances(args.olas_address, owner_crypto.address)
        if token_balance < args.minimum_olas_balance:
            raise ValueError(f"Operator has insufficient OLAS balance. Required: {args.minimum_olas_balance}, Actual: {token_balance}")

        if native_balance == 0:
            raise ValueError("Operator has no xDAI.")

        allowance = erc20.get_allowance(ledger_api, args.olas_address, owner_crypto.address, args.service_registry_address).pop('data')
        if allowance >= args.minimum_olas_balance:
            print("Operator has sufficient OLAS allowance.")
            sys.exit(0)

        approval_tx = get_approval_tx(args.olas_address, args.service_registry_address, args.minimum_olas_balance)
        send_tx_and_wait_for_receipt(owner_crypto, approval_tx)
        print("Approved service registry to spend OLAS.")
        sys.exit(0)

    except Exception as e:  # pylint: disable=broad-except
        print(f"An error occurred while executing {Path(__file__).name}: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
