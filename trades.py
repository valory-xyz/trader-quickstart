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

"""This script queries the OMEN subgraph to obtain the trades of a given address."""

import datetime
import os
import re
from argparse import Action, ArgumentError, ArgumentParser, Namespace
from collections import defaultdict
from dotenv import load_dotenv
from enum import Enum
from pathlib import Path
from string import Template
from typing import Any, Dict, Optional

import requests

from scripts.mech_events import get_mech_requests


IRRELEVANT_TOOLS = [
    "openai-text-davinci-002",
    "openai-text-davinci-003",
    "openai-gpt-3.5-turbo",
    "openai-gpt-4",
    "stabilityai-stable-diffusion-v1-5",
    "stabilityai-stable-diffusion-xl-beta-v2-2-2",
    "stabilityai-stable-diffusion-512-v2-1",
    "stabilityai-stable-diffusion-768-v2-1",
    "deepmind-optimization-strong",
    "deepmind-optimization",
]
QUERY_BATCH_SIZE = 1000
DUST_THRESHOLD = 10000000000000
INVALID_ANSWER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
FPMM_CREATOR = "0x89c5cc945dd550bcffb72fe42bff002429f46fec"
DEFAULT_FROM_DATE = "1970-01-01T00:00:00"
DEFAULT_TO_DATE = "2038-01-19T03:14:07"
DEFAULT_FROM_TIMESTAMP = 0
DEFAULT_TO_TIMESTAMP = 2147483647
SCRIPT_PATH = Path(__file__).resolve().parent
STORE_PATH = Path(SCRIPT_PATH, ".trader_runner")
RPC_PATH = Path(STORE_PATH, "rpc.txt")
ENV_FILE = Path(STORE_PATH, ".env")
WXDAI_CONTRACT_ADDRESS = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"
SCRIPT_PATH = Path(__file__).resolve().parent
STORE_PATH = Path(SCRIPT_PATH, ".trader_runner")
SAFE_ADDRESS_PATH = Path(STORE_PATH, "service_safe_address.txt")


load_dotenv(ENV_FILE)


headers = {
    "Accept": "application/json, multipart/mixed",
    "Content-Type": "application/json",
}


omen_xdai_trades_query = Template(
    """
    {
        fpmmTrades(
            where: {
                type: Buy,
                creator: "${creator}",
                fpmm_: {
                    creator: "${fpmm_creator}"
                    creationTimestamp_gte: "${fpmm_creationTimestamp_gte}",
                    creationTimestamp_lt: "${fpmm_creationTimestamp_lte}"
                },
                creationTimestamp_gte: "${creationTimestamp_gte}",
                creationTimestamp_lte: "${creationTimestamp_lte}"
                creationTimestamp_gt: "${creationTimestamp_gt}"
            }
            first: ${first}
            orderBy: creationTimestamp
            orderDirection: asc
        ) {
            id
            title
            collateralToken
            outcomeTokenMarginalPrice
            oldOutcomeTokenMarginalPrice
            type
            creator {
                id
            }
            creationTimestamp
            collateralAmount
            collateralAmountUSD
            feeAmount
            outcomeIndex
            outcomeTokensTraded
            transactionHash
            fpmm {
                id
                outcomes
                title
                answerFinalizedTimestamp
                currentAnswer
                isPendingArbitration
                arbitrationOccurred
                openingTimestamp
                condition {
                    id
                }
            }
        }
    }
    """
)


conditional_tokens_gc_user_query = Template(
    """
    {
        user(id: "${id}") {
            userPositions(
                first: ${first}
                where: {
                    id_gt: "${userPositions_id_gt}"
                }
                orderBy: id
            ) {
                balance
                id
                position {
                    id
                    conditionIds
                }
                totalBalance
                wrappedBalance
            }
        }
    }
    """
)


class MarketState(Enum):
    """Market state"""

    OPEN = 1
    PENDING = 2
    FINALIZING = 3
    ARBITRATING = 4
    CLOSED = 5
    UNKNOWN = 6

    def __str__(self) -> str:
        """Prints the market status."""
        return self.name.capitalize()


class MarketAttribute(Enum):
    """Attribute"""

    NUM_TRADES = "Num_trades"
    NUM_VALID_TRADES = "Num_valid_trades"
    WINNER_TRADES = "Winner_trades"
    NUM_REDEEMED = "Num_redeemed"
    NUM_INVALID_MARKET = "Num_invalid_market"
    INVESTMENT = "Investment"
    FEES = "Fees"
    MECH_CALLS = "Mech_calls"
    MECH_FEES = "Mech_fees"
    EARNINGS = "Earnings"
    NET_EARNINGS = "Net_earnings"
    REDEMPTIONS = "Redemptions"
    ROI = "ROI"

    def __str__(self) -> str:
        """Prints the attribute."""
        return self.value

    def __repr__(self) -> str:
        """Prints the attribute representation."""
        return self.name

    @staticmethod
    def argparse(s: str) -> "MarketAttribute":
        """Performs string conversion to MarketAttribute."""
        try:
            return MarketAttribute[s.upper()]
        except KeyError as e:
            raise ValueError(f"Invalid MarketAttribute: {s}") from e


STATS_TABLE_COLS = list(MarketState) + ["TOTAL"]
STATS_TABLE_ROWS = list(MarketAttribute)


def get_balance(address: str, rpc_url: str) -> int:
    """Get the native xDAI balance of an address in wei."""
    headers = {"Content-Type": "application/json"}
    data = {
        "jsonrpc": "2.0",
        "method": "eth_getBalance",
        "params": [address, "latest"],
        "id": 1,
    }
    response = requests.post(rpc_url, headers=headers, json=data)
    return int(response.json().get("result"), 16)


def get_token_balance(
    gnosis_address: str, token_contract_address: str, rpc_url: str
) -> int:
    """Get the token balance of an address in wei."""
    function_selector = "70a08231"  # function selector for balanceOf(address)
    padded_address = gnosis_address.replace("0x", "").rjust(
        64, "0"
    )  # remove '0x' and pad the address to 32 bytes
    data = function_selector + padded_address

    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": token_contract_address, "data": data}, "latest"],
        "id": 1,
    }
    response = requests.post(rpc_url, json=payload)
    result = response.json().get("result", "0x0")
    balance_wei = int(result, 16)  # convert hex to int
    return balance_wei


class EthereumAddressAction(Action):
    """Argparse class to validate an Ethereum addresses."""

    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: Any,
        option_string: Optional[str] = None,
    ) -> None:
        """Validates an Ethereum addresses."""

        address = values
        if not re.match(r"^0x[a-fA-F0-9]{40}$", address):
            raise ArgumentError(self, f"Invalid Ethereum address: {address}")
        setattr(namespace, self.dest, address)


def _parse_args() -> Any:
    """Parse the script arguments."""
    parser = ArgumentParser(description="Get trades on Omen for a Safe address.")
    parser.add_argument(
        "--creator",
        action=EthereumAddressAction,
        help="Ethereum address of the service Safe",
    )
    parser.add_argument(
        "--from-date",
        type=datetime.datetime.fromisoformat,
        default=DEFAULT_FROM_DATE,
        help="Start date (UTC) in YYYY-MM-DD:HH:mm:ss format",
    )
    parser.add_argument(
        "--to-date",
        type=datetime.datetime.fromisoformat,
        default=DEFAULT_TO_DATE,
        help="End date (UTC) in YYYY-MM-DD:HH:mm:ss format",
    )
    parser.add_argument(
        "--fpmm-created-from-date",
        type=datetime.datetime.fromisoformat,
        default=DEFAULT_FROM_DATE,
        help="Start date (UTC) in YYYY-MM-DD:HH:mm:ss format",
    )
    parser.add_argument(
        "--fpmm-created-to-date",
        type=datetime.datetime.fromisoformat,
        default=DEFAULT_TO_DATE,
        help="End date (UTC) in YYYY-MM-DD:HH:mm:ss format",
    )
    args = parser.parse_args()

    if args.creator is None:
        with open(SAFE_ADDRESS_PATH, "r", encoding="utf-8") as file:
            args.creator = file.read().strip()

    args.from_date = args.from_date.replace(tzinfo=datetime.timezone.utc)
    args.to_date = args.to_date.replace(tzinfo=datetime.timezone.utc)
    args.fpmm_created_from_date = args.fpmm_created_from_date.replace(
        tzinfo=datetime.timezone.utc
    )
    args.fpmm_created_to_date = args.fpmm_created_to_date.replace(
        tzinfo=datetime.timezone.utc
    )

    return args


def _to_content(q: str) -> Dict[str, Any]:
    """Convert the given query string to payload content, i.e., add it under a `queries` key and convert it to bytes."""
    finalized_query = {
        "query": q,
        "variables": None,
        "extensions": {"headers": None},
    }
    return finalized_query


def _query_omen_xdai_subgraph(  # pylint: disable=too-many-locals
    creator: str,
    from_timestamp: float = DEFAULT_FROM_TIMESTAMP,
    to_timestamp: float = DEFAULT_TO_TIMESTAMP,
    fpmm_from_timestamp: float = DEFAULT_FROM_TIMESTAMP,
    fpmm_to_timestamp: float = DEFAULT_TO_TIMESTAMP,
) -> Dict[str, Any]:
    """Query the subgraph."""
    subgraph_api_key = os.getenv('SUBGRAPH_API_KEY')
    url = f"https://gateway-arbitrum.network.thegraph.com/api/{subgraph_api_key}/subgraphs/id/9fUVQpFwzpdWS9bq5WkAnmKbNNcoBwatMR4yZq81pbbz"

    grouped_results = defaultdict(list)
    creationTimestamp_gt = "0"

    while True:
        query = omen_xdai_trades_query.substitute(
            creator=creator.lower(),
            fpmm_creator=FPMM_CREATOR.lower(),
            creationTimestamp_gte=int(from_timestamp),
            creationTimestamp_lte=int(to_timestamp),
            fpmm_creationTimestamp_gte=int(fpmm_from_timestamp),
            fpmm_creationTimestamp_lte=int(fpmm_to_timestamp),
            first=QUERY_BATCH_SIZE,
            creationTimestamp_gt=creationTimestamp_gt,
        )
        content_json = _to_content(query)
        res = requests.post(url, headers=headers, json=content_json)
        result_json = res.json()
        trades = result_json.get("data", {}).get("fpmmTrades", [])

        if not trades:
            break

        for trade in trades:
            fpmm_id = trade.get("fpmm", {}).get("id")
            grouped_results[fpmm_id].append(trade)

        creationTimestamp_gt = trades[len(trades) - 1]["creationTimestamp"]

    all_results = {
        "data": {
            "fpmmTrades": [
                trade
                for trades_list in grouped_results.values()
                for trade in trades_list
            ]
        }
    }

    return all_results


def _query_conditional_tokens_gc_subgraph(creator: str) -> Dict[str, Any]:
    """Query the subgraph."""
    subgraph_api_key = os.getenv('SUBGRAPH_API_KEY')
    url = f"https://gateway-arbitrum.network.thegraph.com/api/{subgraph_api_key}/subgraphs/id/7s9rGBffUTL8kDZuxvvpuc46v44iuDarbrADBFw5uVp2"

    all_results: Dict[str, Any] = {"data": {"user": {"userPositions": []}}}
    userPositions_id_gt = ""
    while True:
        query = conditional_tokens_gc_user_query.substitute(
            id=creator.lower(),
            first=QUERY_BATCH_SIZE,
            userPositions_id_gt=userPositions_id_gt,
        )
        content_json = {"query": query}
        res = requests.post(url, headers=headers, json=content_json)
        result_json = res.json()
        user_data = result_json.get("data", {}).get("user", {})

        if not user_data:
            break

        user_positions = user_data.get("userPositions", [])

        if user_positions:
            all_results["data"]["user"]["userPositions"].extend(user_positions)
            userPositions_id_gt = user_positions[len(user_positions) - 1]["id"]
        else:
            break

    if len(all_results["data"]["user"]["userPositions"]) == 0:
        return {"data": {"user": None}}

    return all_results


def wei_to_unit(wei: int) -> float:
    """Converts wei to currency unit."""
    return wei / 10**18


def wei_to_xdai(wei: int) -> str:
    """Converts and formats wei to xDAI."""
    return "{:.2f} xDAI".format(wei_to_unit(wei))


def wei_to_wxdai(wei: int) -> str:
    """Converts and formats wei to WxDAI."""
    return "{:.2f} WxDAI".format(wei_to_unit(wei))


def wei_to_olas(wei: int) -> str:
    """Converts and formats wei to WxDAI."""
    return "{:.2f} OLAS".format(wei_to_unit(wei))


def _is_redeemed(user_json: Dict[str, Any], fpmmTrade: Dict[str, Any]) -> bool:
    user_positions = user_json["data"]["user"]["userPositions"]
    outcomes_tokens_traded = int(fpmmTrade["outcomeTokensTraded"])
    condition_id = fpmmTrade["fpmm"]["condition"]["id"]

    for position in user_positions:
        position_condition_ids = position["position"]["conditionIds"]
        balance = int(position["balance"])

        if condition_id in position_condition_ids and balance == outcomes_tokens_traded:
            return False

    for position in user_positions:
        position_condition_ids = position["position"]["conditionIds"]
        balance = int(position["balance"])

        if condition_id in position_condition_ids and balance == 0:
            return True

    return False


def _compute_roi(initial_value: int, final_value: int) -> float:
    if initial_value != 0:
        roi = (final_value - initial_value) / initial_value
    else:
        roi = 0.0

    return roi


def _compute_totals(
    table: Dict[Any, Dict[Any, Any]], mech_statistics: Dict[str, Any]
) -> None:
    for row in table.keys():
        total = sum(table[row][c] for c in table[row])
        table[row]["TOTAL"] = total

    # Total mech fees and calls need to be recomputed, because there could be mech calls
    # for markets that were not traded
    total_mech_calls = 0
    total_mech_fees = 0

    for _, v in mech_statistics.items():
        total_mech_calls += v["count"]
        total_mech_fees += v["fees"]

    table[MarketAttribute.MECH_CALLS]["TOTAL"] = total_mech_calls
    table[MarketAttribute.MECH_FEES]["TOTAL"] = total_mech_fees

    for col in STATS_TABLE_COLS:
        # Omen deducts the fee from collateral_amount (INVESTMENT) to compute outcomes_tokens_traded (EARNINGS).
        table[MarketAttribute.INVESTMENT][col] = (
            table[MarketAttribute.INVESTMENT][col] - table[MarketAttribute.FEES][col]
        )
        table[MarketAttribute.NET_EARNINGS][col] = (
            table[MarketAttribute.EARNINGS][col]
            - table[MarketAttribute.INVESTMENT][col]
            - table[MarketAttribute.FEES][col]
            - table[MarketAttribute.MECH_FEES][col]
        )
        # ROI is recomputed here for all columns, including TOTAL.
        table[MarketAttribute.ROI][col] = _compute_roi(
            table[MarketAttribute.INVESTMENT][col]
            + table[MarketAttribute.FEES][col]
            + table[MarketAttribute.MECH_FEES][col],
            table[MarketAttribute.EARNINGS][col],
        )


def _get_market_state(market: Dict[str, Any]) -> MarketState:
    try:
        now = datetime.datetime.utcnow()

        market_state = MarketState.CLOSED
        if market[
            "currentAnswer"
        ] is None and now >= datetime.datetime.utcfromtimestamp(
            float(market.get("openingTimestamp", 0))
        ):
            market_state = MarketState.PENDING
        elif market["currentAnswer"] is None:
            market_state = MarketState.OPEN
        elif market["isPendingArbitration"]:
            market_state = MarketState.ARBITRATING
        elif now < datetime.datetime.utcfromtimestamp(
            float(market.get("answerFinalizedTimestamp", 0))
        ):
            market_state = MarketState.FINALIZING

        return market_state
    except Exception:  # pylint: disable=broad-except
        return MarketState.UNKNOWN


def _format_table(table: Dict[Any, Dict[Any, Any]]) -> str:
    column_width = 18

    table_str = " " * column_width

    for col in STATS_TABLE_COLS:
        table_str += f"{col:>{column_width}}"

    table_str += "\n"
    table_str += "-" * column_width * (len(STATS_TABLE_COLS) + 1) + "\n"

    table_str += (
        f"{MarketAttribute.NUM_TRADES:<{column_width}}"
        + "".join(
            [
                f"{table[MarketAttribute.NUM_TRADES][c]:>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.NUM_VALID_TRADES:<{column_width}}"
        + "".join(
            [
                f"{table[MarketAttribute.NUM_VALID_TRADES][c]:>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.WINNER_TRADES:<{column_width}}"
        + "".join(
            [
                f"{table[MarketAttribute.WINNER_TRADES][c]:>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.NUM_REDEEMED:<{column_width}}"
        + "".join(
            [
                f"{table[MarketAttribute.NUM_REDEEMED][c]:>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.NUM_INVALID_MARKET:<{column_width}}"
        + "".join(
            [
                f"{table[MarketAttribute.NUM_INVALID_MARKET][c]:>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.MECH_CALLS:<{column_width}}"
        + "".join(
            [
                f"{table[MarketAttribute.MECH_CALLS][c]:>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.INVESTMENT:<{column_width}}"
        + "".join(
            [
                f"{wei_to_xdai(table[MarketAttribute.INVESTMENT][c]):>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.FEES:<{column_width}}"
        + "".join(
            [
                f"{wei_to_xdai(table[MarketAttribute.FEES][c]):>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.MECH_FEES:<{column_width}}"
        + "".join(
            [
                f"{wei_to_xdai(table[MarketAttribute.MECH_FEES][c]):>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.EARNINGS:<{column_width}}"
        + "".join(
            [
                f"{wei_to_xdai(table[MarketAttribute.EARNINGS][c]):>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.NET_EARNINGS:<{column_width}}"
        + "".join(
            [
                f"{wei_to_xdai(table[MarketAttribute.NET_EARNINGS][c]):>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.REDEMPTIONS:<{column_width}}"
        + "".join(
            [
                f"{wei_to_xdai(table[MarketAttribute.REDEMPTIONS][c]):>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.ROI:<{column_width}}"
        + "".join(
            [
                f"{table[MarketAttribute.ROI][c]*100.0:>{column_width-5}.2f} %   "
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )

    return table_str


def parse_user(  # pylint: disable=too-many-locals,too-many-statements
    rpc: str,
    creator: str,
    creator_trades_json: Dict[str, Any],
    mech_statistics: Dict[str, Any],
) -> tuple:
    """Parse the trades from the response."""

    _mech_statistics = dict(mech_statistics)
    user_json = _query_conditional_tokens_gc_subgraph(creator)

    statistics_table = {
        row: {col: 0 for col in STATS_TABLE_COLS} for row in STATS_TABLE_ROWS
    }

    output = "------\n"
    output += "Trades\n"
    output += "------\n"

    for fpmmTrade in creator_trades_json["data"]["fpmmTrades"]:
        try:
            collateral_amount = int(fpmmTrade["collateralAmount"])
            outcome_index = int(fpmmTrade["outcomeIndex"])
            fee_amount = int(fpmmTrade["feeAmount"])
            outcomes_tokens_traded = int(fpmmTrade["outcomeTokensTraded"])
            creation_timestamp = float(fpmmTrade["creationTimestamp"])

            fpmm = fpmmTrade["fpmm"]

            output += f'      Question: {fpmmTrade["title"]}\n'
            output += f'    Market URL: https://aiomen.eth.limo/#/{fpmm["id"]}\n'

            creation_timestamp_utc = datetime.datetime.fromtimestamp(
                creation_timestamp, tz=datetime.timezone.utc
            )
            output += f'    Trade date: {creation_timestamp_utc.strftime("%Y-%m-%d %H:%M:%S %Z")}\n'

            market_status = _get_market_state(fpmm)

            statistics_table[MarketAttribute.NUM_TRADES][market_status] += 1
            statistics_table[MarketAttribute.INVESTMENT][
                market_status
            ] += collateral_amount
            statistics_table[MarketAttribute.FEES][market_status] += fee_amount
            mech_data = _mech_statistics.pop(fpmmTrade["title"], {})
            statistics_table[MarketAttribute.MECH_CALLS][
                market_status
            ] += mech_data.get("count", 0)
            mech_fees = mech_data.get("fees", 0)
            statistics_table[MarketAttribute.MECH_FEES][market_status] += mech_fees

            output += f" Market status: {market_status}\n"
            output += f"        Bought: {wei_to_xdai(collateral_amount)} for {wei_to_xdai(outcomes_tokens_traded)} {fpmm['outcomes'][outcome_index]!r} tokens\n"
            output += f"           Fee: {wei_to_xdai(fee_amount)}\n"
            output += f"   Your answer: {fpmm['outcomes'][outcome_index]!r}\n"

            if market_status == MarketState.FINALIZING:
                current_answer = int(fpmm["currentAnswer"], 16)  # type: ignore
                is_invalid = current_answer == INVALID_ANSWER

                if is_invalid:
                    earnings = collateral_amount
                    output += "Current answer: Market has been declared invalid.\n"
                elif outcome_index == current_answer:
                    earnings = outcomes_tokens_traded
                    output += f"Current answer: {fpmm['outcomes'][current_answer]!r}\n"
                    statistics_table[MarketAttribute.WINNER_TRADES][market_status] += 1
                else:
                    earnings = 0
                    output += f"Current answer: {fpmm['outcomes'][current_answer]!r}\n"

                statistics_table[MarketAttribute.EARNINGS][market_status] += earnings

            elif market_status == MarketState.CLOSED:
                current_answer = int(fpmm["currentAnswer"], 16)  # type: ignore
                is_invalid = current_answer == INVALID_ANSWER

                if is_invalid:
                    earnings = collateral_amount
                    output += "  Final answer: Market has been declared invalid.\n"
                    output += f"      Earnings: {wei_to_xdai(earnings)}\n"
                    redeemed = _is_redeemed(user_json, fpmmTrade)
                    if redeemed:
                        statistics_table[MarketAttribute.NUM_INVALID_MARKET][
                            market_status
                        ] += 1
                        statistics_table[MarketAttribute.REDEMPTIONS][
                            market_status
                        ] += earnings

                elif outcome_index == current_answer:
                    earnings = outcomes_tokens_traded
                    output += f"  Final answer: {fpmm['outcomes'][current_answer]!r} - Congrats! The trade was for the winner answer.\n"
                    output += f"      Earnings: {wei_to_xdai(earnings)}\n"
                    redeemed = _is_redeemed(user_json, fpmmTrade)
                    output += f"      Redeemed: {redeemed}\n"
                    statistics_table[MarketAttribute.WINNER_TRADES][market_status] += 1

                    if redeemed:
                        statistics_table[MarketAttribute.NUM_REDEEMED][
                            market_status
                        ] += 1
                        statistics_table[MarketAttribute.REDEMPTIONS][
                            market_status
                        ] += earnings
                else:
                    earnings = 0
                    output += f"  Final answer: {fpmm['outcomes'][current_answer]!r} - The trade was for the loser answer.\n"


                statistics_table[MarketAttribute.EARNINGS][
                        market_status
                    ] += earnings
                
                statistics_table[MarketAttribute.NUM_VALID_TRADES][
                        market_status
                    ] = statistics_table[MarketAttribute.NUM_TRADES][
                        market_status
                    ] - statistics_table[MarketAttribute.NUM_INVALID_MARKET][
                        market_status
                    ]

                if 0 < earnings < DUST_THRESHOLD:
                    output += "Earnings are dust.\n"

            output += "\n"
        except TypeError:
            output += "ERROR RETRIEVING TRADE INFORMATION.\n\n"

    output += "\n"
    output += "--------------------------\n"
    output += "Summary (per market state)\n"
    output += "--------------------------\n"
    output += "\n"

    # Read rpc and get safe address balance
    safe_address_balance = get_balance(creator, rpc)

    output += f"Safe address:    {creator}\n"
    output += f"Address balance: {wei_to_xdai(safe_address_balance)}\n"

    wxdai_balance = get_token_balance(creator, WXDAI_CONTRACT_ADDRESS, rpc)
    output += f"Token balance:   {wei_to_wxdai(wxdai_balance)}\n\n"

    _compute_totals(statistics_table, mech_statistics)
    output += _format_table(statistics_table)

    return output, statistics_table


def get_mech_statistics(mech_requests: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """Outputs a table with Mech statistics"""

    mech_statistics: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for mech_request in mech_requests.values():
        if (
            "ipfs_contents" not in mech_request
            or "tool" not in mech_request["ipfs_contents"]
            or "prompt" not in mech_request["ipfs_contents"]
        ):
            continue

        if mech_request["ipfs_contents"]["tool"] in IRRELEVANT_TOOLS:
            continue

        prompt = mech_request["ipfs_contents"]["prompt"]
        prompt = prompt.replace("\n", " ")
        prompt = prompt.strip()
        prompt = re.sub(r"\s+", " ", prompt)
        prompt_match = re.search(r"\"(.*)\"", prompt)
        if prompt_match:
            question = prompt_match.group(1)
        else:
            question = prompt

        mech_statistics[question]["count"] += 1
        mech_statistics[question]["fees"] += mech_request["fee"]

    return mech_statistics


if __name__ == "__main__":
    user_args = _parse_args()

    with open(RPC_PATH, "r", encoding="utf-8") as rpc_file:
        rpc = rpc_file.read()

    mech_requests = get_mech_requests(
        user_args.creator,
        user_args.from_date.timestamp(),
        user_args.to_date.timestamp(),
    )
    mech_statistics = get_mech_statistics(mech_requests)

    trades_json = _query_omen_xdai_subgraph(
        user_args.creator,
        user_args.from_date.timestamp(),
        user_args.to_date.timestamp(),
        user_args.fpmm_created_from_date.timestamp(),
        user_args.fpmm_created_to_date.timestamp(),
    )
    parsed_output, _ = parse_user(rpc, user_args.creator, trades_json, mech_statistics)
    print(parsed_output)
