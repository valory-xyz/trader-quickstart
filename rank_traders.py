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
import sys
from argparse import ArgumentParser
from collections import defaultdict
from string import Template
from typing import Any

import requests
import trades
from trades import MarketAttribute, MarketState, wei_to_dai


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
            where: {
                type: Buy,
                fpmm_: {
                    creator: "${fpmm_creator}"
                    creationTimestamp_gte: "${fpmm_creationTimestamp_gte}",
                    creationTimestamp_lt: "${fpmm_creationTimestamp_lte}"
                },
                creationTimestamp_gte: "${creationTimestamp_gte}",
                creationTimestamp_lte: "${creationTimestamp_lte}"
                id_gt: "${id_gt}"
            }
            first: ${first}
            orderBy: id
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

ATTRIBUTE_CHOICES = {i.name: i for i in MarketAttribute}


def _parse_args() -> Any:
    """Parse the creator positional argument."""
    parser = ArgumentParser(description="Get trades on Omen for a Safe address.")
    parser.add_argument(
        "--from-date",
        type=datetime.datetime.fromisoformat,
        default=DEFAULT_FROM_DATE,
        help="Start date for trades (UTC) in YYYY-MM-DD:HH:mm:ss format",
    )
    parser.add_argument(
        "--to-date",
        type=datetime.datetime.fromisoformat,
        default=DEFAULT_TO_DATE,
        help="End date for trades (UTC) in YYYY-MM-DD:HH:mm:ss format",
    )
    parser.add_argument(
        "--fpmm-created-from-date",
        type=datetime.datetime.fromisoformat,
        default=DEFAULT_FROM_DATE,
        help="Start date for market open date (UTC) in YYYY-MM-DD:HH:mm:ss format",
    )
    parser.add_argument(
        "--fpmm-created-to-date",
        type=datetime.datetime.fromisoformat,
        default=DEFAULT_TO_DATE,
        help="End date for market open date (UTC) in YYYY-MM-DD:HH:mm:ss format",
    )
    parser.add_argument(
        "--sort-by",
        choices=list(MarketAttribute),
        default=MarketAttribute.ROI,
        type=MarketAttribute.argparse,
        help="Specify the market attribute for sorting.",
    )
    args = parser.parse_args()

    args.from_date = args.from_date.replace(tzinfo=datetime.timezone.utc)
    args.to_date = args.to_date.replace(tzinfo=datetime.timezone.utc)
    args.fpmm_created_from_date = args.fpmm_created_from_date.replace(
        tzinfo=datetime.timezone.utc
    )
    args.fpmm_created_to_date = args.fpmm_created_to_date.replace(
        tzinfo=datetime.timezone.utc
    )

    return args


def _to_content(q: str) -> dict[str, Any]:
    """Convert the given query string to payload content, i.e., add it under a `queries` key and convert it to bytes."""
    finalized_query = {
        "query": q,
        "variables": None,
        "extensions": {"headers": None},
    }
    return finalized_query


def _query_omen_xdai_subgraph(
    from_timestamp: float,
    to_timestamp: float,
    fpmm_from_timestamp: float,
    fpmm_to_timestamp: float,
) -> dict[str, Any]:
    """Query the subgraph."""
    url = "https://api.thegraph.com/subgraphs/name/protofire/omen-xdai"

    grouped_results = defaultdict(list)
    id_gt = ""

    while True:
        query = omen_xdai_trades_query.substitute(
            fpmm_creator=FPMM_CREATOR.lower(),
            creationTimestamp_gte=int(from_timestamp),
            creationTimestamp_lte=int(to_timestamp),
            fpmm_creationTimestamp_gte=int(fpmm_from_timestamp),
            fpmm_creationTimestamp_lte=int(fpmm_to_timestamp),
            first=QUERY_BATCH_SIZE,
            id_gt=id_gt,
        )
        content_json = _to_content(query)
        res = requests.post(url, headers=headers, json=content_json)
        result_json = res.json()
        user_trades = result_json.get("data", {}).get("fpmmTrades", [])

        if not user_trades:
            break

        for trade in user_trades:
            fpmm_id = trade.get("fpmm", {}).get("id")
            grouped_results[fpmm_id].append(trade)

        id_gt = user_trades[len(user_trades) - 1]["id"]

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


def _group_trades_by_creator(trades_json: dict[str, Any]) -> dict[str, Any]:
    """Group trades by creator ID from the given JSON data."""

    fpmm_trades = trades_json["data"]["fpmmTrades"]
    trades_by_creator = defaultdict(list)

    for trade in fpmm_trades:
        _creator_id = trade["creator"]["id"]
        trades_by_creator[_creator_id].append(trade)

    _creator_to_trades = {
        creator_id: {"data": {"fpmmTrades": trades}}
        for creator_id, trades in trades_by_creator.items()
    }
    return _creator_to_trades


def _print_user_summary(
    creator_to_statistics: dict[str, Any],
    sort_by_attribute: MarketAttribute = MarketAttribute.ROI,
    state: MarketState = MarketState.CLOSED,
) -> None:
    """Prints user ranking."""

    sorted_users = sorted(
        creator_to_statistics.items(),
        key=lambda item: item[1][sort_by_attribute][state],
        reverse=True,
    )

    print("")
    title = f"User summary for {state} markets sorted by {sort_by_attribute}:"
    print()
    print("-" * len(title))
    print(title)
    print("-" * len(title))
    print("")

    titles = [
        "User ID".ljust(42),
        "Ntrades".rjust(8),
        "Nwins".rjust(8),
        "Nredem".rjust(8),
        "Investment".rjust(13),
        "Fees".rjust(13),
        "Earnings".rjust(13),
        "Net Earn.".rjust(13),
        "Redemptions".rjust(13),
        "ROI".rjust(9),
        "\n",
    ]

    output = "".join(titles)
    for user_id, statistics_table in sorted_users:
        values = [
            user_id,
            str(statistics_table[MarketAttribute.NUM_TRADES][state]).rjust(8),
            str(statistics_table[MarketAttribute.WINNER_TRADES][state]).rjust(8),
            str(statistics_table[MarketAttribute.NUM_REDEEMED][state]).rjust(8),
            wei_to_dai(statistics_table[MarketAttribute.INVESTMENT][state]).rjust(13),
            wei_to_dai(statistics_table[MarketAttribute.FEES][state]).rjust(13),
            wei_to_dai(statistics_table[MarketAttribute.EARNINGS][state]).rjust(13),
            wei_to_dai(statistics_table[MarketAttribute.NET_EARNINGS][state]).rjust(13),
            wei_to_dai(statistics_table[MarketAttribute.REDEMPTIONS][state]).rjust(13),
            f"{statistics_table[MarketAttribute.ROI][state] * 100.0:7.2f}%".rjust(9),
            "\n",
        ]
        output += "".join(values)

    print(output)


def _print_progress_bar(  # pylint: disable=too-many-arguments
    iteration: int,
    total: int,
    prefix: str = "Computing statistics:",
    suffix: str = "Complete",
    length: int = 50,
    fill: str = "#",
) -> None:
    """Prints the progress bar"""
    if len(fill) != 1:
        raise ValueError("Fill character must be a single character.")

    percent = ("{0:.1f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + "-" * (length - filled_length)
    progress_string = f"({iteration} of {total}) - {percent}%"
    sys.stdout.write("\r%s |%s| %s %s" % (prefix, bar, progress_string, suffix))
    sys.stdout.flush()


if __name__ == "__main__":
    print("Starting script")
    user_args = _parse_args()

    print("Querying Thegraph...")
    all_trades_json = _query_omen_xdai_subgraph(
        user_args.from_date.timestamp(),
        user_args.to_date.timestamp(),
        user_args.fpmm_created_from_date.timestamp(),
        user_args.fpmm_created_to_date.timestamp(),
    )
    print(f'Total trading transactions: {len(all_trades_json["data"]["fpmmTrades"])}')

    creator_to_trades = _group_trades_by_creator(all_trades_json)
    total_traders = len(creator_to_trades.items())
    print(f"Total traders: {total_traders}")

    creator_to_statistics = {}
    _print_progress_bar(0, total_traders)
    for i, (creator_id, trades_json_id) in enumerate(
        creator_to_trades.items(), start=1
    ):
        _, statistics_table_id = trades.parse_user(creator_id, trades_json_id)
        creator_to_statistics[creator_id] = statistics_table_id
        _print_progress_bar(i, total_traders)

    _print_user_summary(creator_to_statistics, user_args.sort_by)
