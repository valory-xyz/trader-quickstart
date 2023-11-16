#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""This script performs staking related operations."""

import argparse
import sys
import time
import traceback
from pathlib import Path

from datetime import datetime
from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto


from utils import is_service_staked, get_next_checkpoint_ts, get_unstake_txs, send_tx_and_wait_for_receipt, \
    get_available_rewards, get_stake_txs

if __name__ == "__main__":
    try:
        print(f"  - Starting {Path(__file__).name} script...")

        parser = argparse.ArgumentParser(
            description="Stake or unstake the service based on the state."
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
            "staking_contract_address",
            type=str,
            help="The staking contract address.",
        )
        parser.add_argument(
            "owner_private_key_path",
            type=str,
            help="Path to the file containing the service owner's Ethereum private key",
        )
        parser.add_argument("rpc", type=str, help="RPC for the Gnosis chain")
        parser.add_argument(
            "unstake",
            type=bool,
            help="True if the service should be unstaked, False if it should be staked",
            default=False,
        )
        args = parser.parse_args()
        ledger_api = EthereumApi(address=args.rpc)
        owner_crypto = EthereumCrypto(private_key_path=args.owner_private_key_path)
        if args.unstake:
            if not is_service_staked(ledger_api, args.service_id, args.staking_contract_address):
                # the service is not staked, so we don't need to do anything
                print(f"Service {args.service_id} is not staked. Exiting...")
                sys.exit(0)

            next_ts = get_next_checkpoint_ts(
                ledger_api, args.staking_contract_address
            )

            staked_ts = 0 # TODO read from contract
            liveness_period = 24*60*60 # TODO Read from contract
            last_ts = next_ts - liveness_period
            now = time.time()

            if (now - staked_ts) < liveness_period:
                print(
                    f"WARNING: Your service has been staked for less than one liveness period ({liveness_period/3600} hours).\n"
                    "If you proceed with unstaking, you will lose any rewards accrued.\n"
                    "Consider waiting until the liveness period has passed."
                )
                user_input = input("Do you want to continue? (yes/no): ").lower()

                if user_input not in ["yes", "y"]:
                    print("Terminating script.")
                    sys.exit(1)                

            elif now < next_ts:
                formatted_last_ts = datetime.utcfromtimestamp(last_ts).strftime('%Y-%m-%d %H:%M:%S UTC')

                print(
                    f"WARNING: The liveness period ({liveness_period/3600} hours) has not passed since the last checkpoint was called on the staking contract (on {formatted_last_ts}).\n"
                    "If you proceed with unstaking, you will lose any rewards accrued after the last checkpoint call.\n"
                    "Consider waiting until the liveness period has passed."
                )

                user_input = input("Do you want to continue? (yes/no): ").lower()

                if user_input not in ["yes", "y"]:
                    print("Terminating script.")
                    sys.exit(1)

            print(f"Unstaking service {args.service_id}")
            unstake_txs = get_unstake_txs(
                ledger_api, args.service_id, args.staking_contract_address
            )
            for tx in unstake_txs:
                send_tx_and_wait_for_receipt(ledger_api, owner_crypto, tx)
            print("Successfully unstaked.")
            sys.exit(0)

        if is_service_staked(ledger_api, args.service_id, args.staking_contract_address):
            print(
                f"Service {args.service_id} is already staked. "
                f"Checking if the staking contract has any rewards..."
            )
            available_rewards = get_available_rewards(ledger_api, args.staking_contract_address)
            if available_rewards == 0:
                print("No rewards available. Unstaking...")
                unstake_txs = get_unstake_txs(
                    ledger_api, args.service_id, args.staking_contract_address
                )
                for tx in unstake_txs:
                    send_tx_and_wait_for_receipt(ledger_api, owner_crypto, tx)

                print("Unstaked successfully.")
                sys.exit(0)

            print("There are rewards available. The service should remain staked.")
            sys.exit(0)

        print(
            f"Service {args.service_id} is not staked. Checking for available rewards..."
        )
        available_rewards = get_available_rewards(ledger_api, args.staking_contract_address)
        if available_rewards == 0:
            # no rewards available, do nothing
            print("No rewards available. The service cannot be staked.")
            sys.exit(0)

        print(f"Rewards available: {available_rewards}. Staking the service...")
        stake_txs = get_stake_txs(
            ledger_api,
            args.service_id,
            args.service_registry_address,
            args.staking_contract_address,
        )
        for tx in stake_txs:
            send_tx_and_wait_for_receipt(ledger_api, owner_crypto, tx)

        print(f"Service {args.service_id} staked successfully.")
    except Exception as e:  # pylint: disable=broad-except
        print(f"An error occurred while executing {Path(__file__).name}: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
