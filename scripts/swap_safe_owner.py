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

"""This script swaps ownership of a Safe with a single owner."""

import argparse
import binascii
import sys
import traceback
import typing
from pathlib import Path

from aea.contracts.base import Contract
from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto
from hexbytes import HexBytes
from web3 import HTTPProvider, Web3

from packages.valory.contracts.gnosis_safe.contract import (
    GnosisSafeContract,
    SafeOperation,
)
from packages.valory.contracts.multisend.contract import (
    MultiSendContract,
    MultiSendOperation,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
    skill_input_hex_to_payload,
)


ContractType = typing.TypeVar("ContractType")


def load_contract(ctype: ContractType) -> ContractType:
    """Load contract."""
    *parts, _ = ctype.__module__.split(".")
    path = "/".join(parts)
    return Contract.from_dir(directory=path)


if __name__ == "__main__":
    try:
        print(f"  - Starting {Path(__file__).name} script...")

        parser = argparse.ArgumentParser(
            description="Swap ownership of a Safe with a single owner on the Gnosis chain."
        )
        parser.add_argument(
            "safe_address",
            type=str,
            help="Path to the file containing the Ethereum private key",
        )
        parser.add_argument(
            "current_owner_private_key_path",
            type=str,
            help="Path to the file containing the Ethereum private key",
        )
        parser.add_argument(
            "new_owner_address", type=str, help="Recipient address on the Gnosis chain"
        )
        parser.add_argument("rpc", type=str, help="RPC for the Gnosis chain")
        args = parser.parse_args()

        ledger_api = EthereumApi(address=args.rpc)
        current_owner_crypto: EthereumCrypto
        current_owner_crypto = EthereumCrypto(
            private_key_path=args.current_owner_private_key_path
        )
        owner_cryptos: list[EthereumCrypto] = [current_owner_crypto]

        owners = [
            ledger_api.api.to_checksum_address(owner_crypto.address)
            for owner_crypto in owner_cryptos
        ]

        owner_to_swap = owners[0]

        print(f"  - Safe address: {args.safe_address}")
        print(f"  - Current owner: {owner_to_swap}")
        print(f"  - New owner: {args.new_owner_address}")

        multisig_address = args.safe_address
        multisend_address = "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D"

        print("  - Loading contracts...")

        safe = load_contract(GnosisSafeContract)
        multisend = load_contract(MultiSendContract)

        print("  - Building Safe.swapOwner transaction...")

        multisend_txs = []

        txd = safe.get_swap_owner_data(
            ledger_api=ledger_api,
            contract_address=multisig_address,
            old_owner=ledger_api.api.to_checksum_address(owner_to_swap),
            new_owner=ledger_api.api.to_checksum_address(args.new_owner_address),
        ).get("data")
        multisend_txs.append(
            {
                "operation": MultiSendOperation.CALL,
                "to": multisig_address,
                "value": 0,
                "data": HexBytes(txd[2:]),
            }
        )

        multisend_txd = multisend.get_tx_data(  # type: ignore
            ledger_api=ledger_api,
            contract_address=multisend_address,
            multi_send_txs=multisend_txs,
        ).get("data")
        multisend_data = bytes.fromhex(multisend_txd[2:])

        safe_tx_hash = safe.get_raw_safe_transaction_hash(
            ledger_api=ledger_api,
            contract_address=multisig_address,
            to_address=multisend_address,
            value=0,
            data=multisend_data,
            safe_tx_gas=0,
            operation=SafeOperation.DELEGATE_CALL.value,
        ).get("tx_hash")[2:]

        payload_data = hash_payload_to_hex(
            safe_tx_hash=safe_tx_hash,
            ether_value=0,
            safe_tx_gas=0,
            to_address=multisend_address,
            data=multisend_data,
        )

        tx_params = skill_input_hex_to_payload(payload=payload_data)
        safe_tx_bytes = binascii.unhexlify(tx_params["safe_tx_hash"])
        owner_to_signature = {}

        print("  - Signing Safe.swapOwner transaction...")

        for owner_crypto in owner_cryptos:
            signature = owner_crypto.sign_message(
                message=safe_tx_bytes,
                is_deprecated_mode=True,
            )
            owner_to_signature[
                ledger_api.api.to_checksum_address(owner_crypto.address)
            ] = signature[2:]

        tx = safe.get_raw_safe_transaction(
            ledger_api=ledger_api,
            contract_address=multisig_address,
            sender_address=current_owner_crypto.address,
            owners=tuple(owners),  # type: ignore
            to_address=tx_params["to_address"],
            value=tx_params["ether_value"],
            data=tx_params["data"],
            safe_tx_gas=tx_params["safe_tx_gas"],
            signatures_by_owner=owner_to_signature,
            operation=SafeOperation.DELEGATE_CALL.value,
        )
        stx = current_owner_crypto.sign_transaction(tx)
        tx_digest = ledger_api.send_signed_transaction(stx)

        w3 = Web3(HTTPProvider(args.rpc))

        print(f"  - Safe.swapOwner transaction sent. Transaction hash: {tx_digest}")
        print("  - Waiting for transaction receipt...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_digest)

        if receipt["status"] == 1:
            print("  - Safe.swapOwner transaction successfully mined.")
            print(
                f"  - Safe owner successfully swapped from {owner_to_swap} to {args.new_owner_address}"
            )
        else:
            print("  - Safe.swapOwner transaction failed to be mined.")
            sys.exit(1)

    except Exception as e:  # pylint: disable=broad-except
        print(f"An error occurred while executing {Path(__file__).name}: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
