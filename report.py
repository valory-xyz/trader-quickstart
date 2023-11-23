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

"""Obtains a report of the current service."""

import datetime
import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

import docker
import trades
from trades import (
    MarketAttribute,
    MarketState,
    get_balance,
    get_token_balance,
    wei_to_olas,
    wei_to_unit,
    wei_to_wxdai,
    wei_to_xdai,
)
from web3 import HTTPProvider, Web3


SCRIPT_PATH = Path(__file__).resolve().parent
STORE_PATH = Path(SCRIPT_PATH, ".trader_runner")
RPC_PATH = Path(STORE_PATH, "rpc.txt")
AGENT_KEYS_JSON_PATH = Path(STORE_PATH, "keys.json")
OPERATOR_KEYS_JSON_PATH = Path(STORE_PATH, "operator_keys.json")
SAFE_ADDRESS_PATH = Path(STORE_PATH, "service_safe_address.txt")
SERVICE_ID_PATH = Path(STORE_PATH, "service_id.txt")
SERVICE_STAKING_TOKEN_JSON_PATH = Path(
    SCRIPT_PATH,
    "trader",
    "packages",
    "valory",
    "contracts",
    "service_staking_token",
    "build",
    "ServiceStakingToken.json",
)
STAKING_CONTRACT_ADDRESS = "0x5add592ce0a1B5DceCebB5Dcac086Cd9F9e3eA5C"

SAFE_BALANCE_THRESHOLD = 500000000000000000
AGENT_BALANCE_THRESHOLD = 50000000000000000
OPERATOR_BALANCE_THRESHOLD = 50000000000000000

OUTPUT_WIDTH = 80

class TerminalColors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


def _print_section_header(header: str) -> None:
    print("\n" + header)
    print("—" * OUTPUT_WIDTH)


def _print_subsection_header(header: str) -> None:
    print("\n" + header)
    print("=" * OUTPUT_WIDTH)


def _print_status(key: str, value: str, message: str = None) -> None:
    print(f"{key:<30}{value:<10} {message or ''}")


def _warning_message(current_value: int, threshold: int = 0, message: str = "") -> str:
    default_message = (
        f"{TerminalColors.YELLOW}- Balance too low. Threshold is {wei_to_unit(threshold):.2f}.{TerminalColors.RESET}"
    )
    if current_value < threshold:
        return f"{TerminalColors.YELLOW}- {message}{TerminalColors.RESET}" if message else default_message
    return ""


def _get_agent_status() -> str:
    client = docker.from_env()
    trader_abci_container = (
        client.containers.get("trader_abci_0")
        if "trader_abci_0" in [c.name for c in client.containers.list()]
        else None
    )
    trader_tm_container = (
        client.containers.get("trader_tm_0")
        if "trader_tm_0" in [c.name for c in client.containers.list()]
        else None
    )

    if trader_abci_container and trader_tm_container:
        return f"{TerminalColors.GREEN}Running{TerminalColors.RESET}"
    else:
        return f"{TerminalColors.RED}Not Running{TerminalColors.RESET}"


def _parse_args() -> Any:
    """Parse the script arguments."""
    parser = ArgumentParser(description="Get a report for a trader service.")


if __name__ == "__main__":
    user_args = _parse_args()

    with open(AGENT_KEYS_JSON_PATH, "r", encoding="utf-8") as file:
        agent_keys_data = json.load(file)
    agent_address = agent_keys_data[0]["address"]

    with open(OPERATOR_KEYS_JSON_PATH, "r", encoding="utf-8") as file:
        operator_keys_data = json.load(file)
    operator_address = operator_keys_data[0]["address"]

    with open(SAFE_ADDRESS_PATH, "r", encoding="utf-8") as file:
        safe_address = file.read().strip()

    with open(SERVICE_ID_PATH, "r", encoding="utf-8") as file:
        service_id = int(file.read().strip())

    with open(RPC_PATH, "r", encoding="utf-8") as file:
        rpc = file.read().strip()

    # Prediction market trading
    mech_requests = trades.get_mech_requests(rpc, safe_address)
    mech_statistics = trades._get_mech_statistics(mech_requests)
    trades_json = trades._query_omen_xdai_subgraph(safe_address)
    _, statistics_table = trades.parse_user(
        rpc, safe_address, trades_json, mech_statistics
    )

    print("")
    print("==============")
    print("Service report")
    print("==============")
    print("")

    # Performance
    _print_section_header("Performance")
    _print_subsection_header("Staking")

    is_staked = False
    try:
        w3 = Web3(HTTPProvider(rpc))
        with open(SERVICE_STAKING_TOKEN_JSON_PATH, "r", encoding="utf-8") as file:
            contract_data = json.load(file)

        abi = contract_data.get("abi", [])
        contract_instance = w3.eth.contract(address=STAKING_CONTRACT_ADDRESS, abi=abi)
        is_staked = contract_instance.functions.isServiceStaked(service_id).call()
        _print_status("Is service staked?", f"{is_staked}")

        if is_staked:
            service_info = contract_instance.functions.mapServiceInfo(service_id).call()
            ts_start = service_info[2]
            rewards = service_info[3]
            staked_utc_datetime = datetime.datetime.utcfromtimestamp(ts_start).replace(
                tzinfo=datetime.timezone.utc
            )
            staked_utc_string = staked_utc_datetime.strftime("%Y-%m-%d %H:%M:%S UTC")
            _print_status("Staked at", f"{staked_utc_string}")
            _print_status("Accrued rewards", f"{wei_to_olas(rewards)}")

            next_reward_checkpoint_ts = (
                contract_instance.functions.getNextRewardCheckpointTimestamp().call()
            )
            next_reward_utc_datetime = datetime.datetime.utcfromtimestamp(
                next_reward_checkpoint_ts
            ).replace(tzinfo=datetime.timezone.utc)
            next_reward_utc_string = next_reward_utc_datetime.strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
            _print_status("Next rewards checkpoint", f"{next_reward_utc_string}")

            # TODO
            # Staked OLAS 25 too low – threshold is 50
            # Number of txns this epoch	4 too low – threshold is 10
            # Accrued OLAS rewards 1

    except Exception:
        print("An error occurred while interacting with the staking contract.")

    _print_subsection_header(f"Prediction market trading")
    _print_status(
        "ROI closed markets",
        f"{statistics_table[MarketAttribute.ROI][MarketState.CLOSED]*100.0:.2f} %",
    )
    _print_status(
        "ROI total", f"{statistics_table[MarketAttribute.ROI]['TOTAL']*100.0:.2f} %"
    )

    # TODO
    # 3d participation/market 100%

    # Service
    _print_section_header("Service")
    _print_status("ID", service_id)

    # Agent
    agent_status = _get_agent_status()
    agent_xdai = get_balance(agent_address, rpc)
    agent_wxdai = get_token_balance(agent_address, trades.WXDAI_CONTRACT_ADDRESS, rpc)
    _print_subsection_header(
        f"Agent {_warning_message(agent_xdai + agent_wxdai, SAFE_BALANCE_THRESHOLD)}"
    )
    _print_status("Status", agent_status)
    _print_status("Address", agent_address)
    _print_status("xDAI Balance", wei_to_xdai(agent_xdai))
    _print_status("WxDAI Balance", wei_to_xdai(agent_wxdai))

    # Safe
    safe_xdai = get_balance(safe_address, rpc)
    safe_wxdai = get_token_balance(safe_address, trades.WXDAI_CONTRACT_ADDRESS, rpc)
    _print_subsection_header(
        f"Safe {_warning_message(safe_xdai + safe_wxdai, SAFE_BALANCE_THRESHOLD)}"
    )
    _print_status("Address", safe_address)
    _print_status("xDAI Balance", wei_to_xdai(safe_xdai))
    _print_status("WxDAI Balance", wei_to_wxdai(safe_wxdai))

    # Owner/Operator
    operator_xdai = get_balance(operator_address, rpc)
    operator_wxdai = get_token_balance(
        operator_address, trades.WXDAI_CONTRACT_ADDRESS, rpc
    )
    _print_subsection_header(
        f"Owner/Operator {_warning_message(operator_xdai + operator_wxdai, SAFE_BALANCE_THRESHOLD)}"
    )
    _print_status("Address", operator_address)
    _print_status("xDAI Balance", wei_to_xdai(operator_xdai))
    _print_status("WxDAI Balance", wei_to_xdai(operator_wxdai))
    print("")
