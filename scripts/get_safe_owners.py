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

"""Get a Safe current owners' addresses."""

import argparse
import sys
import traceback
import typing
from pathlib import Path

from aea.contracts.base import Contract
from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto

from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract


ContractType = typing.TypeVar("ContractType")


def load_contract(ctype: ContractType) -> ContractType:
    """Load contract."""
    *parts, _ = ctype.__module__.split(".")
    path = "/".join(parts)
    return Contract.from_dir(directory=path)


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            description="Get a Safe current owners' addresses."
        )
        parser.add_argument(
            "safe_address",
            type=str,
            help="Safe address",
        )
        parser.add_argument(
            "private_key_path",
            type=str,
            help="Path to the file containing the Ethereum private key",
        )
        parser.add_argument("rpc", type=str, help="RPC for the Gnosis chain")
        parser.add_argument("--password", type=str, help="Private key password")
        args = parser.parse_args()

        ledger_api = EthereumApi(address=args.rpc)
        ethereum_crypto: EthereumCrypto
        ethereum_crypto = EthereumCrypto(
            private_key_path=args.private_key_path, password=args.password
        )

        safe = load_contract(GnosisSafeContract)
        print(
            safe.get_owners(
                ledger_api=ledger_api, contract_address=args.safe_address
            ).get("owners", [])
        )

    except Exception as e:  # pylint: disable=broad-except
        print(f"An error occurred while executing {Path(__file__).name}: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
