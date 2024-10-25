#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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
import os
import sys
import time
import traceback
from datetime import datetime
from dotenv import dotenv_values
from pathlib import Path

import dotenv
from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto
from choose_staking import (
    STAKING_PROGRAMS,
    DEPRECATED_STAKING_PROGRAMS,
    NO_STAKING_PROGRAM_ID,
)
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

SCRIPT_PATH = Path(__file__).resolve().parent
STORE_PATH = Path(SCRIPT_PATH, "..", ".trader_runner")
DOTENV_PATH = Path(STORE_PATH, ".env")


def _format_duration(duration_seconds: int) -> str:
    days, remainder = divmod(duration_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    formatted_duration = f"{days}D {hours}h {minutes}m"
    return formatted_duration


def _check_unstaking_availability(
    ledger_api: EthereumApi,
    service_id: int,
    staking_contract_address: str,
    staking_program: str,
) -> bool:
    """Service can only be unstaked if one of these conditions occur:
    - No rewards available
    - Staked for longer than > minimum_staking_durtion.
    A service can NOT be unstaked if evicted but has been staked for < minimum_staking_duration
    """

    now = time.time()
    ts_start = get_service_info(
        ledger_api, service_id, staking_contract_address
    )[3]
    minimum_staking_duration = get_min_staking_duration(
        ledger_api, staking_contract_address
    )
    available_rewards = get_available_rewards(ledger_api, staking_contract_address)
    if (now - ts_start) < minimum_staking_duration and available_rewards > 0:
        print(
            f"WARNING: Your service has been staked on {staking_program} for {_format_duration(int(now - ts_start))}."
        )
        print(
            f"You cannot unstake your service from {staking_program} until it has been staked for at least {_format_duration(minimum_staking_duration)}."
        )
        return False

    return True


def _get_current_staking_program(ledger_api, service_id):
    all_staking_programs = STAKING_PROGRAMS.copy()
    all_staking_programs.update(DEPRECATED_STAKING_PROGRAMS)
    del all_staking_programs[NO_STAKING_PROGRAM_ID]
    del all_staking_programs["quickstart_alpha_everest"]  # Very old program, not used likely - causes issues on "is_service_staked"  

    staking_program = NO_STAKING_PROGRAM_ID
    staking_contract_address = None
    for program, address in all_staking_programs.items():
        if is_service_staked(
            ledger_api, service_id, address
        ):
            staking_program = program
            staking_contract_address = address
            print(f"Service {service_id} is staked on {program}.")
        else:
            print(f"Service {service_id} is not staked on {program}.")
    return staking_contract_address, staking_program


def _try_unstake_service(
    ledger_api: EthereumApi,
    service_id: int,
    owner_crypto: EthereumCrypto,
    warn_if_checkpoint_unavailable: bool = True,
) -> None:

    staking_contract_address, staking_program = _get_current_staking_program(ledger_api, service_id)
    print("")

    # Exit if not staked
    if staking_contract_address is None:
        print(f"Service {service_id} is not staked in any active program.")
        return
    else:
        print(f"Service {service_id} is staked on {staking_program}.")

    env_file_vars = dotenv_values(DOTENV_PATH)
    target_program = env_file_vars.get("STAKING_PROGRAM")
    print(f"Target program is set to {target_program}.")
    print("")

    # Collect information
    next_ts = get_next_checkpoint_ts(ledger_api, staking_contract_address)
    liveness_period = get_liveness_period(ledger_api, staking_contract_address)
    last_ts = next_ts - liveness_period
    now = time.time()

    if is_service_evicted(
        ledger_api, service_id, staking_contract_address
    ):
        print(
            f"WARNING: Service {service_id} has been evicted from the {staking_program} staking program due to inactivity."
        )
        if os.environ.get("ATTENDED") == "true":
            input("Press Enter to continue...")

    can_unstake = _check_unstaking_availability(
        ledger_api,
        service_id,
        staking_contract_address,
        staking_program,
    )

    if not can_unstake:
        print("Terminating script.")
        sys.exit(1)

    if warn_if_checkpoint_unavailable and (now < next_ts):
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

        user_input = "y"
        if os.environ.get("ATTENDED") == "true":
            user_input = input(
                f"Do you want to continue unstaking service {service_id} from {staking_program}? (yes/no)\n"
            ).lower()
            print()

        if user_input not in ["yes", "y"]:
            print("Terminating script.")
            sys.exit(1)

    print(f"Unstaking service {service_id} from {staking_program}...")
    unstake_txs = get_unstake_txs(
        ledger_api, service_id, staking_contract_address
    )
    for tx in unstake_txs:
        send_tx_and_wait_for_receipt(ledger_api, owner_crypto, tx)
    print(
        f"Successfully unstaked service {service_id} from {staking_program}."
    )


def _try_stake_service(
    ledger_api: EthereumApi,
    service_id: int,
    owner_crypto: EthereumCrypto,
    service_registry_address: str,
    staking_contract_address: str,
    staking_program: str,
) -> None:

    print(f"Service {service_id} has set {staking_program} staking program.")

    if staking_program == "no_staking":
        return

    if get_available_staking_slots(ledger_api, staking_contract_address) > 0:
        print(
            f"Service {service_id} is not staked on {staking_program}. Checking for available rewards..."
        )
        available_rewards = get_available_rewards(ledger_api, staking_contract_address)
        if available_rewards == 0:
            # no rewards available, do nothing
            print(f"No rewards available on the {staking_program} staking program. Service {service_id} cannot be staked.")
            print("Please choose another staking program.")
            print("Terminating script.")
            sys.exit(1)

        print(
            f"Rewards available on {staking_program}: {available_rewards/10**18:.2f} OLAS. Staking service {service_id}..."
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
    else:
        print(
            f"All staking slots for contract {staking_contract_address} are taken. Service {service_id} cannot be staked."
        )
        print("The script will finish.")
        sys.exit(1)


def main() -> None:
    try:

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

        env_file_vars = dotenv_values(DOTENV_PATH)
        target_program = env_file_vars.get("STAKING_PROGRAM")

        print(f"Starting {Path(__file__).name} script ({target_program})...\n")

        ledger_api = EthereumApi(address=args.rpc)
        owner_crypto = EthereumCrypto(
            private_key_path=args.owner_private_key_path, password=args.password
        )

        # --------------
        # Unstaking flow
        # --------------
        if args.unstake:
            _try_unstake_service(
                ledger_api=ledger_api,
                service_id=args.service_id,
                owner_crypto=owner_crypto,
            )
            return

        # --------------
        # Staking flow
        # --------------
        current_staking_contract_address, current_program = _get_current_staking_program(ledger_api, args.service_id)
        is_staked = current_program != NO_STAKING_PROGRAM_ID

        if is_staked and current_program != target_program:
            print(
                f"WARNING: Service {args.service_id} is staked on {current_program}, but target program is {target_program}. Unstaking..."
            )
            _try_unstake_service(
                ledger_api=ledger_api,
                service_id=args.service_id,
                owner_crypto=owner_crypto,
            )
            is_staked = False
        
        if is_staked and is_service_evicted(
            ledger_api, args.service_id, current_staking_contract_address
        ):
            print(
                f"Service {args.service_id} has been evicted from the {current_program} staking program due to inactivity. Unstaking..."
            )
            _try_unstake_service(
                ledger_api=ledger_api,
                service_id=args.service_id,
                owner_crypto=owner_crypto,
                warn_if_checkpoint_unavailable=False,
            )
            is_staked = False

        if is_staked and get_available_rewards(ledger_api, current_staking_contract_address) == 0:
            print(
                f"No rewards available on the {current_program} staking program. Unstaking service {args.service_id} from {current_program}..."
            )
            _try_unstake_service(
                ledger_api=ledger_api,
                service_id=args.service_id,
                owner_crypto=owner_crypto,
            )
            is_staked = False
        elif is_staked:
            print(
                f"There are rewards available. The service {args.service_id} should remain staked."
            )

        if is_staked:
            print(
                f"Service {args.service_id} is already staked on {target_program}. "
                f"Checking if the staking contract has any rewards..."
            )
        else:

            # At this point must be ensured all these conditions
            #
            # USE_STAKING==True
            # staking_state==Unstaked
            # available_slots > 0
            # available_rewards > 0
            # staking params==OK
            # state==DEPLOYED

            _try_stake_service(
                ledger_api=ledger_api,
                service_id=args.service_id,
                owner_crypto=owner_crypto,
                service_registry_address=args.service_registry_address,
                staking_contract_address=args.staking_contract_address,
                staking_program=target_program,
            )

    except Exception as e:  # pylint: disable=broad-except
        print(f"An error occurred while executing {Path(__file__).name}: {str(e)}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
