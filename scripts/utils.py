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

"""This package contains utils for working with the staking contract."""

import typing

from aea.contracts.base import Contract
from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto
from eth_typing import HexStr

from packages.valory.contracts.erc20.contract import (
    ERC20,
)
from packages.valory.contracts.service_staking_token.contract import (
    ServiceStakingTokenContract,
)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ZERO_ETH = 0

ContractType = typing.TypeVar("ContractType")

GAS_PARAMS = {
    "maxFeePerGas": 30_000_000_000,
    "maxPriorityFeePerGas": 3_000_000_000,
    "gas": 500_000,
}


def load_contract(ctype: ContractType) -> ContractType:
    """Load contract."""
    *parts, _ = ctype.__module__.split(".")
    path = "/".join(parts)
    return Contract.from_dir(directory=path)


def get_approval_tx(
    ledger_api: EthereumApi,
    token: str,
    spender: str,
    amount: int,
) -> typing.Dict[str, typing.Any]:
    """Get approval tx"""
    approval_tx_data = erc20.build_approval_tx(
        ledger_api,
        token,
        spender,
        amount,
    ).pop("data")
    approval_tx = {
        "data": approval_tx_data,
        "to": token,
        "value": ZERO_ETH,
    }
    return approval_tx


def get_balances(
    ledger_api: EthereumApi,
    token: str,
    owner: str,
) -> typing.Tuple[int, int]:
    """Returns the native and token balance of owner."""
    balances = erc20.check_balance(ledger_api, token, owner)
    token_balance, native_balance = balances.pop("token"), balances.pop("wallet")
    return token_balance, native_balance


def get_allowance(
    ledger_api: EthereumApi,
    token: str,
    owner: str,
    spender: str,
) -> int:
    """Returns the allowance of owner for spender."""
    allowance = erc20.get_allowance(ledger_api, token, owner, spender).pop("data")
    return allowance


def get_stake_txs(
    ledger_api: EthereumApi,
    service_id: int,
    service_registry_address: str,
    staking_contract_address: str,
) -> typing.List:
    """Stake the service"""
    # 1. approve the service to make use of the

    # we make use of the ERC20 contract to build the approval transaction
    # since it has the same interface as ERC721
    # we use the ZERO_ADDRESS as the contract address since we don't do any contract interaction here,
    # we are simply encoding
    approval_tx = get_approval_tx(
        erc20, service_registry_address, staking_contract_address, service_id
    )

    # 2. stake the service
    stake_tx_data = staking_contract.build_stake_tx(
        ledger_api, staking_contract_address, service_id
    ).pop("data")
    stake_tx = {
        "data": stake_tx_data,
        "to": staking_contract_address,
        "value": ZERO_ETH,
    }
    return [approval_tx, stake_tx]


def get_unstake_txs(
    ledger_api: EthereumApi, service_id: int, staking_contract_address: str
) -> typing.List:
    """Get unstake txs"""

    unstake_tx_data = staking_contract.build_unstake_tx(
        ledger_api, staking_contract_address, service_id
    ).pop("data")
    unstake_tx = {
        "data": unstake_tx_data,
        "to": staking_contract_address,
        "value": ZERO_ETH,
    }

    return [unstake_tx]


def get_available_rewards(
    ledger_api: EthereumApi, staking_contract_address: str
) -> int:
    """Get available rewards."""
    rewards = staking_contract.available_rewards(
        ledger_api, staking_contract_address
    ).pop("data")
    return rewards


def is_service_staked(
    ledger_api: EthereumApi, service_id: int, staking_contract_address: str
) -> bool:
    """Check if service is staked."""
    is_staked = staking_contract.is_service_staked(
        ledger_api, staking_contract_address, service_id
    ).pop("data")
    return is_staked


def get_next_checkpoint_ts(
    ledger_api: EthereumApi, service_id: int, staking_contract_address: str
) -> int:
    """Check if service is staked."""
    checkpoint_ts = staking_contract.get_next_checkpoint_ts(
        ledger_api, staking_contract_address, service_id
    ).pop("data")
    return checkpoint_ts


def get_staking_rewards(
    ledger_api: EthereumApi, service_id: int, staking_contract_address: str
) -> int:
    """Check if service is staked."""
    rewards = staking_contract.get_staking_rewards(
        ledger_api, staking_contract_address, service_id
    ).pop("data")
    return rewards


def send_tx(
    ledger_api: EthereumApi,
    crypto: EthereumCrypto,
    raw_tx: typing.Dict[str, typing.Any],
) -> str:
    """Send transaction."""
    raw_tx = {
        **raw_tx,
        **GAS_PARAMS,
        "from": crypto.address,
        "nonce": ledger_api.api.eth.get_transaction_count(crypto.address),
        "chainId": ledger_api.api.eth.chain_id,
    }
    signed_tx = crypto.sign_transaction(raw_tx)
    tx_digest = typing.cast(
        str, ledger_api.send_signed_transaction(signed_tx, raise_on_try=True)
    )
    return tx_digest


def send_tx_and_wait_for_receipt(
    ledger_api: EthereumApi,
    crypto: EthereumCrypto,
    raw_tx: typing.Dict[str, typing.Any],
) -> typing.Dict[str, typing.Any]:
    """Send transaction and wait for receipt."""
    tx_digest = HexStr(send_tx(ledger_api, crypto, raw_tx))
    receipt = ledger_api.api.eth.wait_for_transaction_receipt(tx_digest)
    if receipt["status"] != 1:
        raise ValueError("Transaction failed. Receipt:", receipt)
    return receipt


staking_contract = typing.cast(
    typing.Type[ServiceStakingTokenContract], load_contract(ServiceStakingTokenContract)
)
erc20 = typing.cast(typing.Type[ERC20], load_contract(ERC20))
