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

"""Utilities to retrieve on-chain Mech events."""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, ClassVar, Dict

import requests
from tqdm import tqdm
from web3.datastructures import AttributeDict


SCRIPT_PATH = Path(__file__).resolve().parent
STORE_PATH = Path(SCRIPT_PATH, "..", ".trader_runner")
MECH_EVENTS_JSON_PATH = Path(STORE_PATH, "mech_events.json")
HTTP = "http://"
HTTPS = HTTP[:4] + "s" + HTTP[4:]
CID_PREFIX = "f01701220"
IPFS_ADDRESS = f"{HTTPS}gateway.autonolas.tech/ipfs/"
MECH_EVENTS_DB_VERSION = 3
DEFAULT_MECH_FEE = 10000000000000000
MECH_SUBGRAPH_URL = "https://api.studio.thegraph.com/query/57238/mech/0.0.2"
SUBGRAPH_HEADERS = {
    "Accept": "application/json, multipart/mixed",
    "Content-Type": "application/json",
}
QUERY_BATCH_SIZE = 1000
MECH_EVENTS_SUBGRAPH_QUERY = Template(
    """
    query {
        ${subgraph_event_set_name}(
            where: {
                sender: "${sender}"
                id_gt: "${id_gt}"
            }
            first: ${first}
            orderBy: id
            orderDirection: asc
            ) {
            id
            ipfsHash
            requestId
            sender
            transactionHash
            blockNumber
            blockTimestamp
        }
    }
    """
)


@dataclass
class MechBaseEvent:  # pylint: disable=too-many-instance-attributes
    """Base class for mech's on-chain event representation."""

    event_id: str
    sender: str
    transaction_hash: str
    ipfs_hash: str
    block_number: int
    block_timestamp: int
    ipfs_link: str
    ipfs_contents: Dict[str, Any]

    event_name: ClassVar[str]
    subgraph_event_name: ClassVar[str]

    def __init__(
        self,
        event_id: str,
        sender: str,
        ipfs_hash: str,
        transaction_hash: str,
        block_number: int,
        block_timestamp: int,
    ):  # pylint: disable=too-many-arguments
        """Initializes the MechBaseEvent"""
        self.event_id = event_id
        self.sender = sender
        self.ipfs_hash = ipfs_hash
        self.transaction_hash = transaction_hash
        self.block_number = block_number
        self.block_timestamp = block_timestamp
        self.ipfs_link = ""
        self.ipfs_contents = {}
        self._populate_ipfs_contents(ipfs_hash)

    def _populate_ipfs_contents(self, data: str) -> None:
        url = f"{IPFS_ADDRESS}{data}"
        for _url in [f"{url}/metadata.json", url]:
            try:
                response = requests.get(_url)
                response.raise_for_status()
                self.ipfs_contents = response.json()
                self.ipfs_link = _url
            except Exception:  # pylint: disable=broad-except
                continue


@dataclass
class MechRequest(MechBaseEvent):
    """A mech's on-chain response representation."""

    request_id: str
    fee: int

    event_name: ClassVar[str] = "Request"
    subgraph_event_name: ClassVar[str] = "request"

    def __init__(self, event: AttributeDict):
        """Initializes the MechRequest"""

        super().__init__(
            event_id=event["requestId"],
            sender=event["sender"],
            ipfs_hash=event["ipfsHash"],
            transaction_hash=event["transactionHash"],
            block_number=event["blockNumber"],
            block_timestamp=event["blockTimestamp"],
        )

        self.request_id = self.event_id
        # TODO This should be updated to extract the fee from the transaction.
        self.fee = DEFAULT_MECH_FEE


def _read_mech_events_data_from_file() -> Dict[str, Any]:
    """Read Mech events data from the JSON file."""
    try:
        with open(MECH_EVENTS_JSON_PATH, "r", encoding="utf-8") as file:
            mech_events_data = json.load(file)

        # Check if it is an old DB version
        if mech_events_data.get("db_version", 0) < MECH_EVENTS_DB_VERSION:
            current_time = time.strftime("%Y-%m-%d_%H-%M-%S")
            old_db_filename = f"mech_events.{current_time}.old.json"
            os.rename(MECH_EVENTS_JSON_PATH, Path(STORE_PATH, old_db_filename))
            mech_events_data = {}
            mech_events_data["db_version"] = MECH_EVENTS_DB_VERSION
    except FileNotFoundError:
        mech_events_data = {}
        mech_events_data["db_version"] = MECH_EVENTS_DB_VERSION
    return mech_events_data


MINIMUM_WRITE_FILE_DELAY = 20
last_write_time = 0.0


def _write_mech_events_data_to_file(
    mech_events_data: Dict[str, Any], force_write: bool = False
) -> None:
    global last_write_time  # pylint: disable=global-statement
    now = time.time()

    if force_write or (now - last_write_time) >= MINIMUM_WRITE_FILE_DELAY:
        with open(MECH_EVENTS_JSON_PATH, "w", encoding="utf-8") as file:
            json.dump(mech_events_data, file, indent=2)
        last_write_time = now


def _query_mech_events_subgraph(
    sender: str, event_cls: type[MechBaseEvent]
) -> dict[str, Any]:
    """Query the subgraph."""

    subgraph_event_set_name = f"{event_cls.subgraph_event_name}s"
    all_results: dict[str, Any] = {"data": {subgraph_event_set_name: []}}
    id_gt = ""
    while True:
        query = MECH_EVENTS_SUBGRAPH_QUERY.substitute(
            subgraph_event_set_name=subgraph_event_set_name,
            sender=sender,
            id_gt=id_gt,
            first=QUERY_BATCH_SIZE,
        )
        response = requests.post(
            MECH_SUBGRAPH_URL,
            headers=SUBGRAPH_HEADERS,
            json={"query": query},
            timeout=300,
        )
        result_json = response.json()
        events = result_json.get("data", {}).get(subgraph_event_set_name, [])

        if not events:
            break

        all_results["data"][subgraph_event_set_name].extend(events)
        id_gt = events[len(events) - 1]["id"]

    return all_results


# pylint: disable=too-many-locals
def _update_mech_events_db(
    sender: str,
    event_cls: type[MechBaseEvent],
) -> None:
    """Get the mech Events database."""

    print(
        f"Updating the local Mech events database. This may take a while.\n"
        f"             Event: {event_cls.event_name}\n"
        f"    Sender address: {sender}"
    )

    try:
        # Query the subgraph
        query = _query_mech_events_subgraph(sender, event_cls)
        subgraph_data = query["data"]

        # Read the current Mech events database
        mech_events_data = _read_mech_events_data_from_file()
        stored_events = mech_events_data.setdefault(sender, {}).setdefault(
            event_cls.event_name, {}
        )

        subgraph_event_set_name = f"{event_cls.subgraph_event_name}s"
        for subgraph_event in tqdm(
            subgraph_data[subgraph_event_set_name],
            miniters=1,
            desc="        Processing",
        ):
            if subgraph_event[
                "requestId"
            ] not in stored_events or not stored_events.get(
                subgraph_event["requestId"], {}
            ).get(
                "ipfs_contents"
            ):
                mech_event = event_cls(subgraph_event)  # type: ignore
                stored_events[mech_event.event_id] = mech_event.__dict__

                _write_mech_events_data_to_file(mech_events_data=mech_events_data)

        _write_mech_events_data_to_file(
            mech_events_data=mech_events_data, force_write=True
        )

    except KeyboardInterrupt:
        print(
            "\n"
            "WARNING: The update of the local Mech events database was cancelled. "
            "Therefore, the Mech calls and costs might not be reflected accurately. "
            "You may attempt to rerun this script to retry synchronizing the database."
        )
        input("Press Enter to continue...")
    except Exception:  # pylint: disable=broad-except
        print(
            "WARNING: An error occurred while updating the local Mech events database. "
            "Therefore, the Mech calls and costs might not be reflected accurately. "
            "You may attempt to rerun this script to retry synchronizing the database."
        )
        input("Press Enter to continue...")

    print("")


def _get_mech_events(sender: str, event_cls: type[MechBaseEvent]) -> Dict[str, Any]:
    """Updates the local database of Mech events and returns the Mech events."""

    _update_mech_events_db(sender, event_cls)
    mech_events_data = _read_mech_events_data_from_file()
    sender_data = mech_events_data.get(sender, {})
    return sender_data.get(event_cls.event_name, {})


def get_mech_requests(sender: str) -> Dict[str, Any]:
    """Returns the Mech requests."""

    return _get_mech_events(sender, MechRequest)
