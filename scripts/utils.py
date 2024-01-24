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
from datetime import datetime
import time

from aea.contracts.base import Contract
from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto
from eth_typing import HexStr

from packages.valory.contracts.erc20.contract import (
    ERC20,
)
from packages.valory.contracts.service_staking_token.contract import (
    ServiceStakingTokenContract,
)
from autonomy.chain.tx import (
    TxSettler,
    should_retry,
    should_reprice,
)
from requests.exceptions import ConnectionError as RequestsConnectionError
from autonomy.chain.exceptions import (
    ChainInteractionError,
    ChainTimeoutError,
    RPCError,
    TxBuildError,
)
from autonomy.chain.config import ChainType

from packages.valory.skills.staking_abci.rounds import StakingState


DEFAULT_ON_CHAIN_INTERACT_TIMEOUT = 120.0
DEFAULT_ON_CHAIN_INTERACT_RETRIES = 10
DEFAULT_ON_CHAIN_INTERACT_SLEEP = 6.0


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
        ledger_api, service_registry_address, staking_contract_address, service_id
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
    service_staking_state = staking_contract.get_service_staking_state(
        ledger_api, staking_contract_address, service_id
    ).pop("data")

    # TODO Use is_staked = service_staking_state == StakingState.STAKED or service_staking_state == StakingState.EVICTED
    is_staked = (service_staking_state == 1 or service_staking_state == 2)
    return is_staked


def is_service_evicted(
    ledger_api: EthereumApi, service_id: int, staking_contract_address: str
) -> bool:
    """Check if service is staked."""
    service_staking_state = staking_contract.get_service_staking_state(
        ledger_api, staking_contract_address, service_id
    ).pop("data")

    is_evicted = service_staking_state == StakingState.EVICTED
    return is_evicted


def get_next_checkpoint_ts(
    ledger_api: EthereumApi, staking_contract_address: str
) -> int:
    """Check if service is staked."""
    checkpoint_ts = staking_contract.get_next_checkpoint_ts(
        ledger_api, staking_contract_address
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


def get_liveness_period(
    ledger_api: EthereumApi, staking_contract_address: str
) -> int:
    """Get the liveness period."""
    liveness_period = staking_contract.get_liveness_period(
        ledger_api, staking_contract_address
    ).pop("data")
    return liveness_period


def get_min_staking_duration(
    ledger_api: EthereumApi, staking_contract_address: str
) -> int:
    """Get the liveness period."""
    min_staking_duration = staking_contract.get_min_staking_duration(
        ledger_api, staking_contract_address
    ).pop("data")
    return min_staking_duration


def get_service_info(
    ledger_api: EthereumApi, service_id: int, staking_contract_address: str
) -> typing.List:
    """Get the service info."""
    info = staking_contract.get_service_info(
        ledger_api, staking_contract_address, service_id
    ).pop("data")
    return info


def get_price_with_retries(
    ledger_api: EthereumApi, staking_contract_address: str, retries: int = 5
) -> int:
    """Get the price with retries."""
    for i in range(retries):
        try:
            price = staking_contract.try_get_gas_pricing(ledger_api, staking_contract_address)
            return price
        except Exception as e:
            print(e)
            continue
    raise ValueError("Failed to get price after retries")


def get_available_staking_slots(
    ledger_api: EthereumApi, staking_contract_address: str
) -> int:
    """Get available staking slots"""
    max_num_services = staking_contract.max_num_services(
        ledger_api, staking_contract_address).pop("data")

    service_ids = staking_contract.get_service_ids(
        ledger_api, staking_contract_address).pop("data")

    return max_num_services - len(service_ids)


def send_tx(
    ledger_api: EthereumApi,
    crypto: EthereumCrypto,
    raw_tx: typing.Dict[str, typing.Any],
    timeout: float = DEFAULT_ON_CHAIN_INTERACT_TIMEOUT,
    max_retries: int = DEFAULT_ON_CHAIN_INTERACT_RETRIES,
    sleep: float = DEFAULT_ON_CHAIN_INTERACT_SLEEP,
) -> str:
    """Send transaction."""
    tx_dict = {
        **raw_tx,
        **GAS_PARAMS,
        "from": crypto.address,
        "nonce": ledger_api.api.eth.get_transaction_count(crypto.address),
        "chainId": ledger_api.api.eth.chain_id,
    }
    gas_params = ledger_api.try_get_gas_pricing()
    if gas_params is not None:
        tx_dict.update(gas_params)

    tx_settler = TxSettler(ledger_api, crypto, ChainType.CUSTOM)
    retries = 0
    tx_digest = None
    already_known = False
    deadline = datetime.now().timestamp() + timeout
    while retries < max_retries and deadline >= datetime.now().timestamp():
        retries += 1
        try:
            if not already_known:
                tx_signed = crypto.sign_transaction(transaction=tx_dict)
                tx_digest = ledger_api.send_signed_transaction(
                    tx_signed=tx_signed,
                    raise_on_try=True,
                )
            tx_receipt = ledger_api.api.eth.get_transaction_receipt(
                typing.cast(str, tx_digest)
            )
            if tx_receipt is not None:
                return tx_receipt
        except RequestsConnectionError as e:
            raise RPCError("Cannot connect to the given RPC") from e
        except Exception as e:  # pylint: disable=broad-except
            error = str(e)
            if tx_settler._already_known(error):
                already_known = True
                continue  # pragma: nocover
            if not should_retry(error):
                raise ChainInteractionError(error) from e
            if should_reprice(error):
                print("Repricing the transaction...")
                tx_dict = tx_settler._repice(typing.cast(typing.Dict, tx_dict))
                continue
            print(f"Error occurred when interacting with chain: {e}; ")
            print(f"will retry in {sleep}...")
            time.sleep(sleep)
    raise ChainTimeoutError("Timed out when waiting for transaction to go through")


def send_tx_and_wait_for_receipt(
    ledger_api: EthereumApi,
    crypto: EthereumCrypto,
    raw_tx: typing.Dict[str, typing.Any],
) -> typing.Dict[str, typing.Any]:
    """Send transaction and wait for receipt."""
    receipt = HexStr(send_tx(ledger_api, crypto, raw_tx))
    if receipt["status"] != 1:
        raise ValueError("Transaction failed. Receipt:", receipt)
    return receipt


staking_contract = typing.cast(
    typing.Type[ServiceStakingTokenContract], load_contract(ServiceStakingTokenContract)
)
erc20 = typing.cast(typing.Type[ERC20], load_contract(ERC20))
