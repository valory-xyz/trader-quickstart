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

from argparse import ArgumentParser
from string import Template
from typing import Any

import requests


headers = {
    "Accept": "application/json, multipart/mixed",
    "Content-Type": "application/json",
}


omen_xdai_trades_query = Template(
    """
    {
        fpmmTrades(
            where: {type: Buy, creator: "${creator}"}
            first: 1000
            skip: 0
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
        user(id: "${creator}") {
            userPositions {
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


def parse_arg() -> str:
    """Parse the creator positional argument."""
    parser = ArgumentParser()
    parser.add_argument("creator")
    args = parser.parse_args()
    return args.creator


def to_content(q: str) -> dict[str, Any]:
    """Convert the given query string to payload content, i.e., add it under a `queries` key and convert it to bytes."""
    finalized_query = {
        "query": q,
        "variables": None,
        "extensions": {"headers": None},
    }
    return finalized_query


def query_omen_xdai_subgraph() -> dict[str, Any]:
    """Query the subgraph."""
    query = omen_xdai_trades_query.substitute(creator=creator.lower())
    content_json = to_content(query)
    url = "https://api.thegraph.com/subgraphs/name/protofire/omen-xdai"
    res = requests.post(url, headers=headers, json=content_json)
    return res.json()


def query_conditional_tokens_gc_subgraph() -> dict[str, Any]:
    """Query the subgraph."""
    query = conditional_tokens_gc_user_query.substitute(creator=creator.lower())
    content_json = to_content(query)
    url = "https://api.thegraph.com/subgraphs/name/gnosis/conditional-tokens-gc"
    res = requests.post(url, headers=headers, json=content_json)
    return res.json()


def _wei_to_dai(wei: int) -> str:
    dai = wei / 10**18
    formatted_dai = "{:.4f}".format(dai)
    return f"{formatted_dai} DAI"


def _is_redeemed(user_json: dict[str, Any], condition_id: str) -> bool:
    user_positions = user_json["data"]["user"]["userPositions"]

    for position in user_positions:
        position_condition_ids = position["position"]["conditionIds"]
        balance = int(position["balance"])

        if condition_id in position_condition_ids and balance == 0:
            return True

    return False


def parse_response(  # pylint: disable=too-many-locals
    trades_json: dict[str, Any], user_json: dict[str, Any]
) -> str:
    """Parse the trades from the response."""
    output = "------\n"
    output += "Trades\n"
    output += "------\n"

    total_collateral_amount = 0
    total_fee_amount = 0
    total_earnings = 0
    total_redeemed = 0
    total_pending_finalization = 0
    for fpmmTrade in trades_json["data"]["fpmmTrades"]:
        try:
            collateral_amount = int(fpmmTrade["collateralAmount"])
            total_collateral_amount += collateral_amount
            outcome_index = int(fpmmTrade["outcomeIndex"])
            fee_amount = int(fpmmTrade["feeAmount"])
            total_fee_amount += fee_amount
            outcomes_tokens_traded = int(fpmmTrade["outcomeTokensTraded"])

            fpmm = fpmmTrade["fpmm"]
            answer_finalized_timestamp = fpmm["answerFinalizedTimestamp"]
            is_pending_arbitration = fpmm["isPendingArbitration"]
            condition_id = fpmm["condition"]["id"]

            output += f'Market:   https://aiomen.eth.limo/#/{fpmm["id"]}\n'
            output += f'Question: {fpmmTrade["title"]}\n'
            output += f"Bought:   {_wei_to_dai(collateral_amount)} for {_wei_to_dai(outcomes_tokens_traded)} {fpmm['outcomes'][outcome_index]!r} tokens\n"
            output += f"Fee:      {_wei_to_dai(fee_amount)}\n"

            if answer_finalized_timestamp is not None and not is_pending_arbitration:
                current_answer = int(fpmm["currentAnswer"], 16)
                if outcome_index == current_answer:
                    earnings = outcomes_tokens_traded
                else:
                    earnings = 0

                output += f"Earnings: {_wei_to_dai(earnings)}\n"
                total_earnings += earnings
                redeemed = _is_redeemed(user_json, condition_id)
                output += f"Redeemed: {redeemed}\n"

                if redeemed:
                    total_redeemed += earnings
            else:
                output += "Market not yet finalized.\n"
                total_pending_finalization += 1

            output += "\n"
        except TypeError:
            output += "ERROR RETRIEVING TRADE INFORMATION.\n"

    output += "-------\n"
    output += "Summary\n"
    output += "-------\n"

    output += f'Num. trades: {len(trades_json["data"]["fpmmTrades"])} ({total_pending_finalization} pending finalization)\n'
    output += f"Invested:    {_wei_to_dai(total_collateral_amount)}\n"
    output += f"Fees:        {_wei_to_dai(total_fee_amount)}\n"
    output += f"Earnings:    {_wei_to_dai(total_earnings)} (net earnings {_wei_to_dai(total_earnings-total_fee_amount-total_collateral_amount)})\n"
    output += f"Redeemed:    {_wei_to_dai(total_redeemed)}\n"

    return output


if __name__ == "__main__":
    creator = parse_arg()
    _trades_json = query_omen_xdai_subgraph()
    _user_json = query_conditional_tokens_gc_subgraph()
    parsed = parse_response(_trades_json, _user_json)
    print(parsed)
