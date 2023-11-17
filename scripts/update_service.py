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

"""This script updates the service."""

import argparse
import sys
import traceback
from pathlib import Path

from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto
from autonomy.chain.base import UnitType, registry_contracts
from autonomy.chain.mint import sort_service_dependency_metadata
from autonomy.chain.config import ChainType, ContractConfigs
from aea.crypto.base import Crypto, LedgerApi
from typing import List
from math import ceil
from autonomy.chain.constants import (
    AGENT_REGISTRY_CONTRACT,
    COMPONENT_REGISTRY_CONTRACT,
    REGISTRIES_MANAGER_CONTRACT,
    SERVICE_MANAGER_CONTRACT,
    SERVICE_REGISTRY_CONTRACT,
)
from autonomy.chain.metadata import NFTHashOrPath, publish_metadata
from aea.configurations.loader import load_configuration_object
from aea.configurations.data_types import PackageType
from aea.helpers.base import IPFSHash

from autonomy.configurations.base import PACKAGE_TYPE_TO_CONFIG_CLASS

from utils import send_tx_and_wait_for_receipt


def update_service(  # pylint: disable=too-many-arguments,too-many-locals
    ledger_api: LedgerApi,
    crypto: Crypto,
    service_id: int,
    nft: str,
    chain_type: ChainType,
    agent_ids: List[int],
    number_of_slots_per_agent: List[int],
    cost_of_bond_per_agent: List[int],
    threshold: int,
    token: str,
    directory: Path,
) -> None:
    """Publish component on-chain."""

    package = load_configuration_object(
        package_type=PackageType.SERVICE,
        directory=directory,
        package_type_config_class=PACKAGE_TYPE_TO_CONFIG_CLASS,
    )
    metadata_hash, _ = publish_metadata(
        package_id=package.package_id,
        package_path=directory,
        nft=IPFSHash(nft),
        description=package.description,
    )

    if len(agent_ids) == 0:
        raise ValueError("Please provide at least one agent id")

    if len(number_of_slots_per_agent) == 0:
        raise ValueError("Please for provide number of slots for agents")

    if len(cost_of_bond_per_agent) == 0:
        raise ValueError("Please for provide cost of bond for agents")

    if (
        len(agent_ids) != len(number_of_slots_per_agent)
        or len(agent_ids) != len(cost_of_bond_per_agent)
        or len(number_of_slots_per_agent) != len(cost_of_bond_per_agent)
    ):
        raise ValueError(
            "Make sure the number of agent ids, number of slots for agents and cost of bond for agents match"
        )

    if any(map(lambda x: x == 0, number_of_slots_per_agent)):
        raise ValueError("Number of slots cannot be zero")

    if any(map(lambda x: x == 0, cost_of_bond_per_agent)):
        raise ValueError("Cost of bond cannot be zero")

    number_of_agent_instances = sum(number_of_slots_per_agent)
    if threshold < (ceil((number_of_agent_instances * 2 + 1) / 3)):
        raise ValueError(
            "The threshold value should at least be greater than or equal to ceil((n * 2 + 1) / 3), "
            "n is total number of agent instances in the service"
        )

    (
        agent_ids,
        number_of_slots_per_agent,
        cost_of_bond_per_agent,
    ) = sort_service_dependency_metadata(
        agent_ids=agent_ids,
        number_of_slots_per_agents=number_of_slots_per_agent,
        cost_of_bond_per_agent=cost_of_bond_per_agent,
    )

    agent_params = [
        [n, c] for n, c in zip(number_of_slots_per_agent, cost_of_bond_per_agent)
    ]

    tx = registry_contracts.service_manager.get_update_transaction(
        ledger_api=ledger_api,
        contract_address=ContractConfigs.get(SERVICE_MANAGER_CONTRACT.name).contracts[
            chain_type
        ],
        service_id=service_id,
        sender=crypto.address,
        metadata_hash=metadata_hash,
        agent_ids=agent_ids,
        agent_params=agent_params,
        threshold=threshold,
        token=token,
        raise_on_try=True,
    )

    send_tx_and_wait_for_receipt(ledger_api, crypto, tx)


if __name__ == "__main__":
    try:
        print(f"  - Starting {Path(__file__).name} script...")

        parser = argparse.ArgumentParser(description="Update the service.")
        parser.add_argument(
            "owner_private_key_path",
            type=str,
            help="Path to the file containing the service owner's Ethereum private key",
        )
        parser.add_argument(
            "nft",
            type=str,
            help="The nft to be used.",
        )
        parser.add_argument(
            "agent_id",
            type=int,
            help="The service registry contract address.",
        )
        parser.add_argument(
            "service_id",
            type=int,
            help="The service id.",
        )
        parser.add_argument(
            "token",
            type=str,
            help="The token address to be used.",
        )
        parser.add_argument(
            "bond_amount",
            type=int,
            help="The bond amount.",
        )
        parser.add_argument(
            "directory",
            type=str,
            help="The directory of the service package.",
        )
        parser.add_argument("rpc", type=str, help="RPC for the Gnosis chain")
        args = parser.parse_args()
        ledger_api = EthereumApi(address=args.rpc)
        owner_crypto = EthereumCrypto(private_key_path=args.owner_private_key_path)
        update_service(
            ledger_api=ledger_api,
            crypto=owner_crypto,
            service_id=args.service_id,
            nft=args.nft,
            chain_type=ChainType.CUSTOM,
            agent_ids=[args.agent_id],
            number_of_slots_per_agent=[1],
            cost_of_bond_per_agent=[args.bond_amount],
            threshold=1,
            token=args.token,
            directory=Path(args.directory),
        )
        print(f"Service {args.service_id} updated successfully.")
    except Exception as e:  # pylint: disable=broad-except
        print(f"An error occurred while executing {Path(__file__).name}: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
