#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022-2024 Valory AG
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

"""Get the available staking slots."""

import argparse
import sys
import traceback
import typing
from pathlib import Path

from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto
from utils import get_available_staking_slots


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            description="Get the available staking slots."
        )
        parser.add_argument(
            "staking_contract_address",
            type=str,
            help="The staking contract address.",
        )
        parser.add_argument("rpc", type=str, help="RPC for the Gnosis chain")
        args = parser.parse_args()

        ledger_api = EthereumApi(address=args.rpc)
        available_staking_slots = get_available_staking_slots(
            ledger_api, args.staking_contract_address
        )

        print(available_staking_slots)

    except Exception as e:  # pylint: disable=broad-except
        print(f"An error occurred while executing {Path(__file__).name}: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
