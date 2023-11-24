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

from datetime import datetime, timezone
import json
from argparse import ArgumentParser
from pathlib import Path
import time
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
STAKING_CONTRACT_ADDRESS = "0x5add592ce0a1B5DceCebB5Dcac086Cd9F9e3eA5C"
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

SAFE_BALANCE_THRESHOLD = 500000000000000000
AGENT_XDAI_BALANCE_THRESHOLD = 50000000000000000
OPERATOR_XDAI_BALANCE_THRESHOLD = 50000000000000000
MECH_REQUESTS_PER_EPOCH_THRESHOLD = 10
TRADES_LOOKBACK_DAYS = 3

OUTPUT_WIDTH = 80


class ColorCode:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


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
    filtered_trades = [trade for trade in trades_json.get("data", {}).get("fpmmTrades", []) if float(trade["creationTimestamp"]) >= utc_ts]
    unique_markets = set(trade["fpmm"]["id"] for trade in filtered_trades)
    trades_count = len(filtered_trades)
    markets_count = len(unique_markets)
    return f"{trades_count} trades on {markets_count} markets"


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
        f"- Too low. Threshold is {wei_to_unit(threshold):.2f}.",
        ColorCode.YELLOW,
    )
    if current_value < threshold:
        return (
            _color_string(f"- {message}", ColorCode.YELLOW)
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
    # mech_requests = trades.get_mech_requests(rpc, safe_address)
    mech_requests = {}
    mech_statistics = trades._get_mech_statistics(mech_requests)
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
        with open(SERVICE_STAKING_TOKEN_JSON_PATH, "r", encoding="utf-8") as file:
            service_staking_token_data = json.load(file)

        service_staking_token_abi = service_staking_token_data.get("abi", [])
        service_staking_token_contract = w3.eth.contract(address=STAKING_CONTRACT_ADDRESS, abi=service_staking_token_abi)
        is_staked = service_staking_token_contract.functions.isServiceStaked(service_id).call()
        _print_status("Is service staked?", _color_bool(is_staked, "Yes", "No"))

        if is_staked:
            with open(SERVICE_REGISTRY_TOKEN_UTILITY_JSON_PATH, "r", encoding="utf-8") as file:
                service_registry_token_utility_data = json.load(file)

            service_registry_token_utility_abi = service_registry_token_utility_data.get("abi", [])
            service_registry_token_utility_contract = w3.eth.contract(address=STAKING_CONTRACT_ADDRESS, abi=service_staking_token_abi)


            _print_status("Staked (security deposit)", f"{wei_to_olas(25000000000000000000)}")
            _print_status("Staked (slashable bond)", f"{wei_to_olas(25000000000000000000)}")

            service_info = service_staking_token_contract.functions.mapServiceInfo(service_id).call()
            rewards = service_info[3]
            _print_status("Accrued rewards", f"{wei_to_olas(rewards)}")

            mech_requests_current_epoch = 3
            _print_status("Num. Mech txs current epoch", f"{mech_requests_current_epoch} {_warning_message(mech_requests_current_epoch, MECH_REQUESTS_PER_EPOCH_THRESHOLD)}")

    except Exception:
        print("An error occurred while interacting with the staking contract.")

    _print_subsection_header(f"Prediction market trading")
    _print_status(
        "ROI on closed markets",
        _color_percent(statistics_table[MarketAttribute.ROI][MarketState.CLOSED]),
    )

    since_ts = time.time() - 60*60*24 * TRADES_LOOKBACK_DAYS
    _print_status(
        f"Trades on last {TRADES_LOOKBACK_DAYS} days",
        _trades_since_message(trades_json, since_ts),
    )

    # Service
    _print_section_header("Service")
    _print_status("ID", str(service_id))

    # Agent
    agent_status = _get_agent_status()
    agent_xdai = get_balance(agent_address, rpc)
    _print_subsection_header(f"Agent")
    _print_status("Status", agent_status)
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
    _print_subsection_header(f"Owner/Operator")
    _print_status("Address", operator_address)
    _print_status(
        "xDAI Balance",
        f"{wei_to_xdai(operator_xdai)} {_warning_message(operator_xdai, OPERATOR_XDAI_BALANCE_THRESHOLD)}",
    )
    print("")
