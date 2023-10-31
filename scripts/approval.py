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
from pathlib import Path

from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto

from utils import (
    get_balances,
    send_tx_and_wait_for_receipt,
    get_allowance,
    get_approval_tx,
)

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
        owner_crypto = EthereumCrypto(private_key_path=args.operator_private_key_path)
        token_balance, native_balance = get_balances(
            ledger_api, args.olas_address, owner_crypto.address
        )
        if token_balance < args.minimum_olas_balance:
            raise ValueError(
                f"Operator has insufficient OLAS balance. Required: {args.minimum_olas_balance}, Actual: {token_balance}"
            )

        if native_balance == 0:
            raise ValueError("Operator has no xDAI.")

        allowance = get_allowance(
            ledger_api,
            args.olas_address,
            owner_crypto.address,
            args.service_registry_address,
        )
        if allowance >= args.minimum_olas_balance:
            print("Operator has sufficient OLAS allowance.")
            sys.exit(0)

        approval_tx = get_approval_tx(
            ledger_api,
            args.olas_address,
            args.service_registry_address,
            args.minimum_olas_balance,
        )
        send_tx_and_wait_for_receipt(ledger_api, owner_crypto, approval_tx)
        print("Approved service registry to spend OLAS.")
        sys.exit(0)

    except Exception as e:  # pylint: disable=broad-except
        print(f"An error occurred while executing {Path(__file__).name}: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
