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

import json
import math
import time
import traceback
from argparse import ArgumentParser
from collections import Counter

from dotenv import dotenv_values
from enum import Enum
from pathlib import Path
import requests
import sys
from typing import Any, List

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
DOTENV_PATH = Path(STORE_PATH, ".env")
RPC_PATH = Path(STORE_PATH, "rpc.txt")
AGENT_KEYS_JSON_PATH = Path(STORE_PATH, "keys.json")
OPERATOR_KEYS_JSON_PATH = Path(STORE_PATH, "operator_keys.json")
SAFE_ADDRESS_PATH = Path(STORE_PATH, "service_safe_address.txt")
SERVICE_ID_PATH = Path(STORE_PATH, "service_id.txt")
STAKING_TOKEN_JSON_PATH = Path(
    SCRIPT_PATH,
    "trader",
    "packages",
    "valory",
    "contracts",
    "staking_token",
    "build",
    "StakingToken.json",
)
ACTIVITY_CHECKER_JSON_PATH = Path(
    SCRIPT_PATH,
    "trader",
    "packages",
    "valory",
    "contracts",
    "mech_activity",
    "build",
    "MechActivity.json",
)
SERVICE_REGISTRY_L2_JSON_PATH = Path(
    SCRIPT_PATH,
    "trader",
    "packages",
    "valory",
    "contracts",
    "service_registry",
    "build",
    "ServiceRegistryL2.json",
)
SERVICE_REGISTRY_TOKEN_UTILITY_JSON_PATH = Path(
    SCRIPT_PATH,
    "contracts",
    "ServiceRegistryTokenUtility.json",
)
MECH_CONTRACT_ADDRESS = "0x77af31De935740567Cf4fF1986D04B2c964A786a"
MECH_CONTRACT_JSON_PATH = Path(
    SCRIPT_PATH,
    "trader",
    "packages",
    "valory",
    "contracts",
    "mech",
    "build",
    "mech.json",
)

SAFE_BALANCE_THRESHOLD = 500000000000000000
AGENT_XDAI_BALANCE_THRESHOLD = 50000000000000000
OPERATOR_XDAI_BALANCE_THRESHOLD = 50000000000000000
MECH_REQUESTS_PER_EPOCH_THRESHOLD = 10
TRADES_LOOKBACK_DAYS = 3
REBETS_LOOKBACK_DAYS = 3
DAY_IN_UNIX = 60 * 60 * 24

OUTPUT_WIDTH = 80


class ColorCode:
    """Terminal color codes"""

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


class StakingState(Enum):
    """Staking state enumeration for the staking."""

    UNSTAKED = 0
    STAKED = 1
    EVICTED = 2


def _color_string(text: str, color_code: str) -> str:
    return f"{color_code}{text}{ColorCode.RESET}"


def _color_bool(
    is_true: bool, true_string: str = "True", false_string: str = "False"
) -> str:
    if is_true:
        return _color_string(true_string, ColorCode.GREEN)
    return _color_string(false_string, ColorCode.RED)


def _color_percent(p: float, multiplier: float = 100, symbol: str = "%") -> str:
    if p >= 0:
        return f"{p*multiplier:.2f} {symbol}"
    return _color_string(f"{p*multiplier:.2f} {symbol}", ColorCode.RED)


def _trades_since_message(trades_json: dict[str, Any], utc_ts: float = 0) -> str:
    filtered_trades = [
        trade
        for trade in trades_json.get("data", {}).get("fpmmTrades", [])
        if float(trade["creationTimestamp"]) >= utc_ts
    ]
    unique_markets = set(trade["fpmm"]["id"] for trade in filtered_trades)
    trades_count = len(filtered_trades)
    markets_count = len(unique_markets)
    return f"{trades_count} trades on {markets_count} markets"


def _calculate_rebets_since(trades_json: dict[str, Any], utc_ts: float = 0) -> tuple[Counter[Any], int, int, int]:
    filtered_trades = Counter((
        trade.get("fpmm", {}).get("id", None)
        for trade in trades_json.get("data", {}).get("fpmmTrades", [])
        if float(trade.get("creationTimestamp", 0)) >= utc_ts
    ))

    if None in filtered_trades:
        raise ValueError(
            f"Unexpected format in trades_json: {filtered_trades[None]} trades have no associated market ID.")

    unique_markets = set(filtered_trades)
    n_unique_markets = len(unique_markets)
    n_bets = sum(filtered_trades.values())
    n_rebets = sum(n_bets - 1 for n_bets in filtered_trades.values() if n_bets > 1)

    return filtered_trades, n_unique_markets, n_bets, n_rebets

def _rebets_since_message(n_unique_markets: int, n_bets: int, n_rebets: int) -> str:
    return f"{n_rebets} rebets on total {n_bets} bets in {n_unique_markets} markets"

def _average_bets_since_message(n_bets: int, n_markets: int) -> str:
    if n_markets == 0:
        average_bets = 0
    else:
        average_bets = round(n_bets / n_markets, 2)

    return f"{average_bets} bets per market"

def _max_bets_since_message(filtered_trades: Counter[Any]) -> str:
    if filtered_trades == Counter():
        max_bets = 0
    else:
        max_bets = max(filtered_trades.values())

    return f"{max_bets} bets per market"


def _get_mech_requests_count(
    mech_requests: dict[str, Any], timestamp: float = 0
) -> int:
    return sum(
        1
        for mech_request in mech_requests.values()
        if mech_request.get("block_timestamp", 0) > timestamp
    )


def _print_section_header(header: str) -> None:
    print("\n\n" + header)
    print("=" * OUTPUT_WIDTH)


def _print_subsection_header(header: str) -> None:
    print("\n" + header)
    print("-" * OUTPUT_WIDTH)


def _print_status(key: str, value: str, message: str = "") -> None:
    print(f"{key:<30}{value:<10} {message or ''}")


def _warning_message(current_value: int, threshold: int = 0, message: str = "") -> str:
    default_message = _color_string(
        f"- Balance too low. Threshold is {wei_to_unit(threshold):.2f}.",
        ColorCode.YELLOW,
    )
    if current_value < threshold:
        return (
            _color_string(f"{message}", ColorCode.YELLOW)
            if message
            else default_message
        )
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

    is_running = trader_abci_container and trader_tm_container
    return _color_bool(is_running, "Running", "Stopped")


def _parse_args() -> Any:
    """Parse the script arguments."""
    parser = ArgumentParser(description="Get a report for a trader service.")
    args = parser.parse_args()
    return args


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

    env_file_vars = dotenv_values(DOTENV_PATH)

    # Prediction market trading
    mech_requests = trades.get_mech_requests(safe_address)
    mech_statistics = trades.get_mech_statistics(mech_requests)
    trades_json = trades._query_omen_xdai_subgraph(safe_address)
    _, statistics_table = trades.parse_user(
        rpc, safe_address, trades_json, mech_statistics
    )

    print("")
    print("==============")
    print("Service report")
    print("==============")

    # Performance
    _print_section_header("Performance")
    _print_subsection_header("Staking")

    try:
        w3 = Web3(HTTPProvider(rpc))

        staking_token_address = env_file_vars.get("CUSTOM_STAKING_ADDRESS")
        with open(STAKING_TOKEN_JSON_PATH, "r", encoding="utf-8") as file:
            staking_token_data = json.load(file)

        staking_token_abi = staking_token_data.get("abi", [])
        staking_token_contract = w3.eth.contract(
            address=staking_token_address, abi=staking_token_abi  # type: ignore
        )

        staking_state = StakingState(
            staking_token_contract.functions.getStakingState(
                service_id
            ).call()
        )

        is_staked = (
            staking_state == StakingState.STAKED
            or staking_state == StakingState.EVICTED
        )
        _print_status("Is service staked?", _color_bool(is_staked, "Yes", "No"))
        if is_staked:
            _print_status("Staking program", env_file_vars.get("STAKING_PROGRAM"))  # type: ignore
        if staking_state == StakingState.STAKED:
            _print_status("Staking state", staking_state.name)
        elif staking_state == StakingState.EVICTED:
            _print_status("Staking state", _color_string(staking_state.name, ColorCode.RED))

        if is_staked:

            activity_checker_address = staking_token_contract.functions.activityChecker().call()
            with open(ACTIVITY_CHECKER_JSON_PATH, "r", encoding="utf-8") as file:
                activity_checker_data = json.load(file)

            activity_checker_abi = activity_checker_data.get("abi", [])
            activity_checker_contract = w3.eth.contract(
                address=activity_checker_address, abi=activity_checker_abi  # type: ignore
            )

            with open(
                SERVICE_REGISTRY_TOKEN_UTILITY_JSON_PATH, "r", encoding="utf-8"
            ) as file:
                service_registry_token_utility_data = json.load(file)

            service_registry_token_utility_contract_address = (
                staking_token_contract.functions.serviceRegistryTokenUtility().call()
            )
            service_registry_token_utility_abi = (
                service_registry_token_utility_data.get("abi", [])
            )
            service_registry_token_utility_contract = w3.eth.contract(
                address=service_registry_token_utility_contract_address,
                abi=service_registry_token_utility_abi,
            )

            mech_contract_address = env_file_vars.get("MECH_CONTRACT_ADDRESS")
            with open(MECH_CONTRACT_JSON_PATH, "r", encoding="utf-8") as file:
                mech_contract_data = json.load(file)

            mech_contract_abi = mech_contract_data.get("abi", [])

            mech_contract = w3.eth.contract(
                address=mech_contract_address, abi=mech_contract_abi   # type: ignore
            )

            security_deposit = (
                service_registry_token_utility_contract.functions.getOperatorBalance(
                    operator_address, service_id
                ).call()
            )
            agent_id = int(env_file_vars.get("AGENT_ID").strip())
            agent_bond = service_registry_token_utility_contract.functions.getAgentBond(
                service_id, agent_id
            ).call()
            min_staking_deposit = (
                staking_token_contract.functions.minStakingDeposit().call()
            )

            # In the setting 1 agent instance as of now: minOwnerBond = minStakingDeposit
            min_security_deposit = min_staking_deposit
            _print_status(
                "Staked (security deposit)",
                f"{wei_to_olas(security_deposit)} {_warning_message(security_deposit, min_security_deposit)}",
            )
            _print_status(
                "Staked (agent bond)",
                f"{wei_to_olas(agent_bond)} {_warning_message(agent_bond, min_staking_deposit)}",
            )

            service_info = staking_token_contract.functions.mapServiceInfo(
                service_id
            ).call()
            rewards = service_info[3]
            _print_status("Accrued rewards", f"{wei_to_olas(rewards)}")

            liveness_ratio = (
                activity_checker_contract.functions.livenessRatio().call()
            )
            mech_requests_24h_threshold = math.ceil(
                (liveness_ratio * 60 * 60 * 24) / 10**18
            )

            next_checkpoint_ts = (
                staking_token_contract.functions.getNextRewardCheckpointTimestamp().call()
            )
            liveness_period = (
                staking_token_contract.functions.livenessPeriod().call()
            )
            last_checkpoint_ts = next_checkpoint_ts - liveness_period

            mech_request_count = mech_contract.functions.getRequestsCount(safe_address).call()
            mech_request_count_on_last_checkpoint = (
                staking_token_contract.functions.getServiceInfo(service_id).call()
            )[2][1]
            mech_requests_since_last_cp = mech_request_count - mech_request_count_on_last_checkpoint
            # mech_requests_current_epoch = _get_mech_requests_count(
            #     mech_requests, last_checkpoint_ts
            # )
            mech_requests_current_epoch = mech_requests_since_last_cp
            _print_status(
                "Num. Mech txs current epoch",
                f"{mech_requests_current_epoch} {_warning_message(mech_requests_current_epoch, mech_requests_24h_threshold, f'- Too low. Threshold is {mech_requests_24h_threshold}.')}",
            )

    except Exception:  # pylint: disable=broad-except
        traceback.print_exc()
        print("An error occurred while interacting with the staking contract.")

    _print_subsection_header("Prediction market trading")
    _print_status(
        "ROI on closed markets",
        _color_percent(statistics_table[MarketAttribute.ROI][MarketState.CLOSED]),
    )

    since_ts = time.time() - DAY_IN_UNIX * TRADES_LOOKBACK_DAYS
    _print_status(
        f"Trades on last {TRADES_LOOKBACK_DAYS} days",
        _trades_since_message(trades_json, since_ts),
    )

    #Multi bet strategy
    rebets_since_ts = time.time() - DAY_IN_UNIX * REBETS_LOOKBACK_DAYS
    filtered_trades, n_unique_markets, n_bets, n_rebets = _calculate_rebets_since(trades_json, rebets_since_ts)
    _print_subsection_header(f"Multi-bet markets in previous {REBETS_LOOKBACK_DAYS} days")
    _print_status(f"Multi-bet markets", _rebets_since_message(n_unique_markets, n_bets, n_rebets))
    _print_status(f"Average bets per market", _average_bets_since_message(n_bets, n_unique_markets))
    _print_status(f"Max bets per market", _max_bets_since_message(filtered_trades))

    # Service
    _print_section_header("Service")
    _print_status("ID", str(service_id))

    # Agent
    agent_status = _get_agent_status()
    agent_xdai = get_balance(agent_address, rpc)
    _print_subsection_header("Agent")
    _print_status("Status (on this machine)", agent_status)
    _print_status("Address", agent_address)
    _print_status(
        "xDAI Balance",
        f"{wei_to_xdai(agent_xdai)} {_warning_message(agent_xdai, AGENT_XDAI_BALANCE_THRESHOLD)}",
    )

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
    _print_subsection_header("Owner/Operator")
    _print_status("Address", operator_address)
    _print_status(
        "xDAI Balance",
        f"{wei_to_xdai(operator_xdai)} {_warning_message(operator_xdai, OPERATOR_XDAI_BALANCE_THRESHOLD)}",
    )
    print("")
