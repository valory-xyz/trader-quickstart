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
from datetime import datetime
from pathlib import Path

import dotenv
from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto
from utils import (
    get_available_rewards,
    get_available_staking_slots,
    get_liveness_period,
    get_min_staking_duration,
    get_next_checkpoint_ts,
    get_service_ids,
    get_service_info,
    get_stake_txs,
    get_unstake_txs,
    is_service_evicted,
    is_service_staked,
    send_tx_and_wait_for_receipt,
)


EVEREST_STAKING_CONTRACT_ADDRESS = "0x5add592ce0a1B5DceCebB5Dcac086Cd9F9e3eA5C"


def _format_duration(duration_seconds: int) -> str:
    days, remainder = divmod(duration_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    formatted_duration = f"{days}D {hours}h {minutes}m"
    return formatted_duration


def _unstake_everest(
    ledger_api: EthereumApi, service_id: int, owner_crypto: EthereumCrypto
) -> None:
    print("Checking if service is staked on Everest...")
    staking_contract_address = EVEREST_STAKING_CONTRACT_ADDRESS

    if service_id not in get_service_ids(ledger_api, staking_contract_address):
        print(f"Service {service_id} is not staked on Everest.")
        return

    print(
        f"Service {service_id} is staked on Everest. To continue in a new staking program, first, it must be unstaked from Everest."
    )
    user_input = input(
        "Do you want to continue unstaking from Everest? (yes/no)\n"
    ).lower()
    print()

    if user_input not in ["yes", "y"]:
        print("Terminating script.")
        sys.exit(1)

    print(f"Unstaking service {service_id} from Everest...")
    unstake_txs = get_unstake_txs(ledger_api, service_id, staking_contract_address)
    for tx in unstake_txs:
        send_tx_and_wait_for_receipt(ledger_api, owner_crypto, tx)
    print("Successfully unstaked from Everest.")


def _check_unstaking_availability(
    now: float,
    ts_start: float,
    minimum_staking_duration: int,
    available_rewards: float,
    staking_program: str,
) -> None:
    if (now - ts_start) < minimum_staking_duration and available_rewards > 0:
        print(
            f"WARNING: Your service has been staked on {staking_program} for {_format_duration(int(now - ts_start))}."
        )
        print(
            f"You cannot unstake your service from {staking_program} until it has been staked for at least {_format_duration(minimum_staking_duration)}."
        )
        print("Terminating script.")
        sys.exit(1)


def _try_stake_service(
    ledger_api: EthereumApi,
    service_id: int,
    owner_crypto: EthereumCrypto,
    service_registry_address: str,
    staking_contract_address: str,
) -> None:
    if get_available_staking_slots(ledger_api, staking_contract_address) > 0:
        print(
            f"Service {service_id} is not staked on {staking_program}. Checking for available rewards..."
        )
        available_rewards = get_available_rewards(ledger_api, staking_contract_address)
        if available_rewards == 0:
            # no rewards available, do nothing
            print(f"No rewards available. Service {service_id} cannot be staked.")
            sys.exit(0)

        print(
            f"Rewards available: {available_rewards/10**18:.2f} OLAS. Staking service {service_id}..."
        )
        stake_txs = get_stake_txs(
            ledger_api,
            service_id,
            service_registry_address,
            staking_contract_address,
        )
        for tx in stake_txs:
            send_tx_and_wait_for_receipt(ledger_api, owner_crypto, tx)

        print(f"Service {service_id} staked successfully on {staking_program}.")
        sys.exit(0)
    else:
        print(
            f"All staking slots for contract {staking_contract_address} are taken. Service {service_id} cannot be staked."
        )
        print("The script will finish.")
        sys.exit(1)


if __name__ == "__main__":
    try:
        staking_program = "Alpine"
        print(f"Starting {Path(__file__).name} script ({staking_program})...\n")

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
        parser.add_argument("--password", type=str, help="Private key password")
        args = parser.parse_args()
        ledger_api = EthereumApi(address=args.rpc)
        owner_crypto = EthereumCrypto(
            private_key_path=args.owner_private_key_path, password=args.password
        )

        _unstake_everest(ledger_api, args.service_id, owner_crypto)

        # Collect information
        next_ts = get_next_checkpoint_ts(ledger_api, args.staking_contract_address)
        ts_start = get_service_info(
            ledger_api, args.service_id, args.staking_contract_address
        )[3]

        liveness_period = get_liveness_period(ledger_api, args.staking_contract_address)
        last_ts = next_ts - liveness_period
        now = time.time()

        minimum_staking_duration = get_min_staking_duration(
            ledger_api, args.staking_contract_address
        )
        available_rewards = get_available_rewards(
            ledger_api, args.staking_contract_address
        )

        if args.unstake:
            if not is_service_staked(
                ledger_api, args.service_id, args.staking_contract_address
            ):
                # the service is not staked, so we don't need to do anything
                print(f"Service {args.service_id} is not staked.")
                sys.exit(0)

            if is_service_evicted(
                ledger_api, args.service_id, args.staking_contract_address
            ):
                print(
                    f"WARNING: Service {args.service_id} has been evicted from the {staking_program} staking program due to inactivity."
                )
                input("Press Enter to continue...")

            _check_unstaking_availability(
                now,
                ts_start,
                minimum_staking_duration,
                available_rewards,
                staking_program,
            )

            if now < next_ts:
                formatted_last_ts = datetime.utcfromtimestamp(last_ts).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                )
                formatted_next_ts = datetime.utcfromtimestamp(next_ts).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                )

                print(
                    "WARNING: Staking checkpoint call not available yet\n"
                    "--------------------------------------------------\n"
                    f"The liveness period ({liveness_period/3600} hours) has not passed since the last checkpoint call.\n"
                    f"  - {formatted_last_ts} - Last checkpoint call.\n"
                    f"  - {formatted_next_ts} - Next checkpoint call availability.\n"
                    "\n"
                    "If you proceed with unstaking, your agent's work done between the last checkpoint call until now will not be accounted for rewards.\n"
                    "(Note: To maximize agent work eligible for rewards, the recommended practice is to unstake shortly after a checkpoint has been called and stake again immediately after.)\n"
                )

                user_input = input(
                    f"Do you want to continue unstaking service {args.service_id} from {staking_program}? (yes/no)\n"
                ).lower()
                print()

                if user_input not in ["yes", "y"]:
                    print("Terminating script.")
                    sys.exit(1)

            print(f"Unstaking service {args.service_id} from {staking_program}...")
            unstake_txs = get_unstake_txs(
                ledger_api, args.service_id, args.staking_contract_address
            )
            for tx in unstake_txs:
                send_tx_and_wait_for_receipt(ledger_api, owner_crypto, tx)
            print(
                f"Successfully unstaked service {args.service_id} from {staking_program}."
            )
            sys.exit(0)

        if is_service_staked(
            ledger_api, args.service_id, args.staking_contract_address
        ):
            if is_service_evicted(
                ledger_api, args.service_id, args.staking_contract_address
            ):
                print(
                    f"Service {args.service_id} has been evicted from the {staking_program} staking program due to inactivity. Unstaking..."
                )

                _check_unstaking_availability(
                    now,
                    ts_start,
                    minimum_staking_duration,
                    available_rewards,
                    staking_program,
                )

                unstake_txs = get_unstake_txs(
                    ledger_api, args.service_id, args.staking_contract_address
                )
                for tx in unstake_txs:
                    send_tx_and_wait_for_receipt(ledger_api, owner_crypto, tx)

                print(
                    f"Successfully unstaked service {args.service_id} from {staking_program}."
                )

                _try_stake_service(
                    ledger_api=ledger_api,
                    service_id=args.service_id,
                    owner_crypto=owner_crypto,
                    service_registry_address=args.service_registry_address,
                    staking_contract_address=args.staking_contract_address,
                )
                sys.exit(0)

            print(
                f"Service {args.service_id} is already staked on {staking_program}."
                f"Checking if the staking contract has any rewards..."
            )
            available_rewards = get_available_rewards(
                ledger_api, args.staking_contract_address
            )
            if available_rewards == 0:
                print(
                    f"No rewards available. Unstaking service {args.service_id} from {staking_program}..."
                )
                unstake_txs = get_unstake_txs(
                    ledger_api, args.service_id, args.staking_contract_address
                )
                for tx in unstake_txs:
                    send_tx_and_wait_for_receipt(ledger_api, owner_crypto, tx)

                print(
                    f"Successfully unstaked service {args.service_id} from {staking_program}."
                )
                sys.exit(0)

            print(
                f"There are rewards available. The service {args.service_id} should remain staked."
            )
            sys.exit(0)
        else:
            _try_stake_service(
                ledger_api=ledger_api,
                service_id=args.service_id,
                owner_crypto=owner_crypto,
                service_registry_address=args.service_registry_address,
                staking_contract_address=args.staking_contract_address,
            )

    except Exception as e:  # pylint: disable=broad-except
        print(f"An error occurred while executing {Path(__file__).name}: {str(e)}")
        traceback.print_exc()
        dotenv.unset_key("../.trader_runner/.env", "USE_STAKING")
        print(
            "\nPlease confirm whether your service is participating in a staking program, and then retry running the script."
        )
        sys.exit(1)
