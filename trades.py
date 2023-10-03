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

"""This script queries the OMEN subgraph to obtain the trades of a given address."""

import datetime
import time
from argparse import ArgumentParser
from collections import defaultdict
from enum import Enum
from string import Template
from typing import Any

import requests


QUERY_BATCH_SIZE = 1000
DUST_THRESHOLD = 10000000000000
INVALID_ANSWER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
FPMM_CREATOR = "0x89c5cc945dd550bcffb72fe42bff002429f46fec"
DEFAULT_FROM_DATE = "1970-01-01T00:00:00"
DEFAULT_TO_DATE = "2038-01-19T03:14:07"


headers = {
    "Accept": "application/json, multipart/mixed",
    "Content-Type": "application/json",
}


omen_xdai_trades_query = Template(
    """
    {
        fpmmTrades(
            where: {type: Buy, creator: "${creator}" fpmm_: {creator: "${fpmm_creator}"} }
            first: ${first}
            skip: ${skip}
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
                skip: ${skip}
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

    def __str__(self) -> str:
        """Prints the market status."""
        return self.name.capitalize()


class MarketAttribute(Enum):
    """Market status"""

    NUM_TRADES = "Num. trades"
    WINNER_TRADES = "Winner trades"
    NUM_REDEEMED = "Num. redeemed"
    INVESTMENT = "Invested"
    FEES = "Fees"
    EARNINGS = "Earnings"
    NET_EARNINGS = "Net earnings"
    REDEMPTIONS = "Redeemed"
    ROI = "ROI"

    def __str__(self) -> str:
        """Prints the market status."""
        return self.value


STATS_TABLE_COLS = list(MarketState) + ["TOTAL"]
STATS_TABLE_ROWS = list(MarketAttribute)


def _parse_args() -> Any:
    """Parse the creator positional argument."""
    parser = ArgumentParser(description="Get trades on Omen for a Safe address.")
    parser.add_argument("creator")
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
    args = parser.parse_args()

    args.from_date = args.from_date.replace(tzinfo=datetime.timezone.utc)
    args.to_date = args.to_date.replace(tzinfo=datetime.timezone.utc)

    return args


def _to_content(q: str) -> dict[str, Any]:
    """Convert the given query string to payload content, i.e., add it under a `queries` key and convert it to bytes."""
    finalized_query = {
        "query": q,
        "variables": None,
        "extensions": {"headers": None},
    }
    return finalized_query


def _query_omen_xdai_subgraph(creator: str) -> dict[str, Any]:
    """Query the subgraph."""
    url = "https://api.thegraph.com/subgraphs/name/protofire/omen-xdai"

    grouped_results = defaultdict(list)
    skip = 0

    while True:
        query = omen_xdai_trades_query.substitute(
            creator=creator.lower(),
            fpmm_creator=FPMM_CREATOR.lower(),
            first=QUERY_BATCH_SIZE,
            skip=skip,
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

        skip += QUERY_BATCH_SIZE

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


def _query_conditional_tokens_gc_subgraph(creator: str) -> dict[str, Any]:
    """Query the subgraph."""
    url = "https://api.thegraph.com/subgraphs/name/gnosis/conditional-tokens-gc"

    all_results: dict[str, Any] = {"data": {"user": {"userPositions": []}}}
    skip = 0
    while True:
        query = conditional_tokens_gc_user_query.substitute(
            id=creator.lower(), first=QUERY_BATCH_SIZE, skip=skip
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
            skip += QUERY_BATCH_SIZE
        else:
            break

    if len(all_results["data"]["user"]["userPositions"]) == 0:
        return {"data": {"user": None}}

    return all_results


def _wei_to_dai(wei: int) -> str:
    dai = wei / 10**18
    formatted_dai = "{:.2f}".format(dai)
    return f"{formatted_dai} DAI"


def _is_redeemed(user_json: dict[str, Any], fpmmTrade: dict[str, Any]) -> bool:
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


def _compute_roi(investment: int, net_earnings: int) -> float:
    if investment != 0:
        roi = (net_earnings / investment) * 100.0
    else:
        roi = 0.0

    return roi


def _compute_totals(table: dict[Any, dict[Any, Any]]) -> None:
    for row in table.keys():
        total = sum(table[row][c] for c in table[row])
        table[row]["TOTAL"] = total

    for col in STATS_TABLE_COLS:
        table[MarketAttribute.NET_EARNINGS][col] = (
            table[MarketAttribute.EARNINGS][col]
            - table[MarketAttribute.FEES][col]
            - table[MarketAttribute.INVESTMENT][col]
        )
        table[MarketAttribute.ROI][col] = _compute_roi(
            table[MarketAttribute.INVESTMENT][col],
            table[MarketAttribute.NET_EARNINGS][col],
        )


def _format_table(table: dict[Any, dict[Any, Any]]) -> str:
    column_width = 14

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
        f"{MarketAttribute.INVESTMENT:<{column_width}}"
        + "".join(
            [
                f"{_wei_to_dai(table[MarketAttribute.INVESTMENT][c]):>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.FEES:<{column_width}}"
        + "".join(
            [
                f"{_wei_to_dai(table[MarketAttribute.FEES][c]):>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.EARNINGS:<{column_width}}"
        + "".join(
            [
                f"{_wei_to_dai(table[MarketAttribute.EARNINGS][c]):>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.NET_EARNINGS:<{column_width}}"
        + "".join(
            [
                f"{_wei_to_dai(table[MarketAttribute.NET_EARNINGS][c]):>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.REDEMPTIONS:<{column_width}}"
        + "".join(
            [
                f"{_wei_to_dai(table[MarketAttribute.REDEMPTIONS][c]):>{column_width}}"
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )
    table_str += (
        f"{MarketAttribute.ROI:<{column_width}}"
        + "".join(
            [
                f"{table[MarketAttribute.ROI][c]:>{column_width-4}.2f} %  "
                for c in STATS_TABLE_COLS
            ]
        )
        + "\n"
    )

    return table_str


def _parse_response(  # pylint: disable=too-many-locals,too-many-statements
    trades_json: dict[str, Any],
    user_json: dict[str, Any],
    from_timestamp: float,
    to_timestamp: float,
) -> str:
    """Parse the trades from the response."""

    statistics_table = {
        row: {col: 0 for col in STATS_TABLE_COLS} for row in STATS_TABLE_ROWS
    }

    output = "------\n"
    output += "Trades\n"
    output += "------\n"

    filtered_trades = [
        fpmmTrade
        for fpmmTrade in trades_json["data"]["fpmmTrades"]
        if from_timestamp <= float(fpmmTrade["creationTimestamp"]) <= to_timestamp
    ]

    for fpmmTrade in filtered_trades:
        try:
            collateral_amount = int(fpmmTrade["collateralAmount"])
            outcome_index = int(fpmmTrade["outcomeIndex"])
            fee_amount = int(fpmmTrade["feeAmount"])
            outcomes_tokens_traded = int(fpmmTrade["outcomeTokensTraded"])
            creation_timestamp = float(fpmmTrade["creationTimestamp"])

            fpmm = fpmmTrade["fpmm"]
            answer_finalized_timestamp = fpmm["answerFinalizedTimestamp"]
            is_pending_arbitration = fpmm["isPendingArbitration"]
            opening_timestamp = fpmm["openingTimestamp"]

            output += f'      Question: {fpmmTrade["title"]}\n'
            output += f'    Market URL: https://aiomen.eth.limo/#/{fpmm["id"]}\n'

            creation_timestamp_utc = datetime.datetime.fromtimestamp(
                creation_timestamp, tz=datetime.timezone.utc
            )
            output += f'    Trade date: {creation_timestamp_utc.strftime("%Y-%m-%d %H:%M:%S %Z")}\n'

            market_status = MarketState.CLOSED
            if fpmm["currentAnswer"] is None and time.time() >= float(
                opening_timestamp
            ):
                market_status = MarketState.PENDING
            elif fpmm["currentAnswer"] is None:
                market_status = MarketState.OPEN
            elif is_pending_arbitration:
                market_status = MarketState.ARBITRATING
            elif time.time() < float(answer_finalized_timestamp):
                market_status = MarketState.FINALIZING

            statistics_table[MarketAttribute.NUM_TRADES][market_status] += 1
            statistics_table[MarketAttribute.INVESTMENT][
                market_status
            ] += collateral_amount
            statistics_table[MarketAttribute.FEES][market_status] += fee_amount

            output += f" Market status: {market_status}\n"
            output += f"        Bought: {_wei_to_dai(collateral_amount)} for {_wei_to_dai(outcomes_tokens_traded)} {fpmm['outcomes'][outcome_index]!r} tokens\n"
            output += f"           Fee: {_wei_to_dai(fee_amount)}\n"
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
                    output += f"      Earnings: {_wei_to_dai(earnings)}\n"
                elif outcome_index == current_answer:
                    earnings = outcomes_tokens_traded
                    output += f"  Final answer: {fpmm['outcomes'][current_answer]!r} - Congrats! The trade was for the winner answer.\n"
                    output += f"      Earnings: {_wei_to_dai(earnings)}\n"
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

                statistics_table[MarketAttribute.EARNINGS][market_status] += earnings

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

    _compute_totals(statistics_table)
    output += _format_table(statistics_table)

    return output


if __name__ == "__main__":
    user_args = _parse_args()
    _trades_json = _query_omen_xdai_subgraph(user_args.creator)
    _user_json = _query_conditional_tokens_gc_subgraph(user_args.creator)
    parsed = _parse_response(
        _trades_json,
        _user_json,
        user_args.from_date.timestamp(),
        user_args.to_date.timestamp(),
    )
    print(parsed)
