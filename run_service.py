# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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
"""Optimus Quickstart script."""

import textwrap
import warnings

import requests

warnings.filterwarnings("ignore", category=UserWarning)
import sys
import getpass
import os
import sys
import time
import typing as t
from dataclasses import dataclass
from pathlib import Path

from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi, Web3
from dotenv import load_dotenv
from halo import Halo
from termcolor import colored

from operate.account.user import UserAccount
from operate.cli import OperateApp
from operate.ledger.profiles import OLAS
from operate.resource import LocalResource, deserialize
from operate.services.manage import ServiceManager
from operate.services.service import Service, DUMMY_MULTISIG
from operate.operate_types import (
    LedgerType,
    ServiceTemplate,
    ConfigurationTemplate,
    FundRequirementsTemplate,
    OnChainState,
    ServiceEnvProvisionType,
)
from scripts.choose_staking import (
    ACTIVITY_CHECKER_ABI_PATH,
    IPFS_ADDRESS,
    NO_STAKING_PROGRAM_ID,
    NO_STAKING_PROGRAM_METADATA,
    STAKING_PROGRAMS,
    STAKING_TOKEN_INSTANCE_ABI_PATH,
    ZERO_ADDRESS,
    _get_abi,
    StakingVariables,
)

load_dotenv()

AGENT_ID = 14
OPERATIONAL_FUND_REQUIREMENT = 500_000_000_000_000_000
SAFETY_MARGIN = 100_000_000_000_000
STAKED_BONDING_TOKEN = "OLAS"
WARNING_ICON = colored('\u26A0', 'yellow')
OPERATE_HOME = Path.cwd() / ".operate"
DEFAULT_STAKING_CHAIN = "gnosis"
CHAIN_ID_TO_METADATA = {
    "gnosis": {
        "name": "Gnosis",
        "token": "xDAI",
        "operationalFundReq": OPERATIONAL_FUND_REQUIREMENT,  # fund for master wallet
        "gasParams": {
            # this means default values will be used
            "MAX_PRIORITY_FEE_PER_GAS": "",
            "MAX_FEE_PER_GAS": "",
        }
    },
}


@dataclass
class TraderConfig(LocalResource):
    """Local configuration."""

    path: Path
    gnosis_rpc: t.Optional[str] = None
    password_migrated: t.Optional[bool] = None
    staking_vars: t.Optional[StakingVariables] = None
    use_mech_marketplace: t.Optional[bool] = None
    principal_chain: t.Optional[str] = None

    @classmethod
    def from_json(cls, obj: t.Dict) -> "LocalResource":
        """Load LocalResource from json."""
        kwargs = {}
        for pname, ptype in cls.__annotations__.items():
            if pname.startswith("_"):
                continue

            # allow for optional types
            is_optional_type = t.get_origin(ptype) is t.Union and type(None) in t.get_args(ptype)
            value = obj.get(pname, None)
            if is_optional_type and value is None:
                continue

            kwargs[pname] = deserialize(obj=obj[pname], otype=ptype)
        return cls(**kwargs)

def print_box(text: str, margin: int = 1, character: str = '=') -> None:
    """Print text centered within a box."""

    lines = text.split('\n')
    text_length = max(len(line) for line in lines)
    length = text_length + 2 * margin

    border = character * length
    margin_str = ' ' * margin

    print(border)
    print(f"{margin_str}{text}{margin_str}")
    print(border)
    print()

def print_title(text: str) -> None:
    """Print title."""
    print()
    print_box(text, 4, '=')

def print_section(text: str) -> None:
    """Print section."""
    print_box(text, 1, '-')

def wei_to_unit(wei: int) -> float:
    """Convert Wei to unit."""
    return wei / 1e18

def wei_to_token(wei: int, token: str = "xDAI") -> str:
    """Convert Wei to token."""
    return f"{wei_to_unit(wei):.6f} {token}"

def ask_confirm_password() -> str:
    password = getpass.getpass("Please input your password (or press enter): ")
    confirm_password = getpass.getpass("Please confirm your password: ")

    if password == confirm_password:
        return password
    else:
        print("Passwords do not match. Terminating.")
        sys.exit(1)

def load_local_config() -> TraderConfig:
    """Load the local optimus configuration."""
    path = OPERATE_HOME / "local_config.json"
    if path.exists():
        trader_config = TraderConfig.load(path)
    else:
        trader_config = TraderConfig(path)

    return trader_config

def check_rpc(rpc_url: t.Optional[str] = None) -> True:
    if rpc_url is None:
        return False

    spinner = Halo(text=f"Checking RPC...", spinner="dots")
    spinner.start()

    rpc_data = {
        "jsonrpc": "2.0",
        "method": "eth_newFilter",
        "params": ["invalid"],
        "id": 1
    }

    try:
        response = requests.post(
            rpc_url,
            json=rpc_data,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        rpc_response = response.json()
    except Exception as e:
        print("Error: Failed to send RPC request:", e)
        return False

    rcp_error_message = rpc_response.get("error", {}).get("message", "Exception processing RCP response")

    if rcp_error_message == "Exception processing RCP response":
        print("Error: The received RCP response is malformed. Please verify the RPC address and/or RCP behavior.")
        print("  Received response:")
        print("  ", rpc_response)
        print("")
        print("Terminating script.")
        return False
    elif rcp_error_message == "Out of requests":
        print("Error: The provided RCP is out of requests.")
        print("Terminating script.")
        return False
    elif rcp_error_message == "The method eth_newFilter does not exist/is not available":
        print("Error: The provided RPC does not support 'eth_newFilter'.")
        print("Terminating script.")
        return False
    elif rcp_error_message == "invalid params":
        spinner.succeed("RPC checks passed.")
        return True

    print("Error: Unknown RCP error.")
    print("  Received response:")
    print("  ", rpc_response)
    print("")
    print("Terminating script.")
    return False

def _get_staking_token_contract(program_id: str, rpc: str, use_blockscout: bool = False) -> t.Any:
    w3 = Web3(Web3.HTTPProvider(rpc))
    staking_token_instance_address = STAKING_PROGRAMS.get(program_id)
    if use_blockscout:
        abi = _get_abi(staking_token_instance_address)
    else:
        abi = requests.get(STAKING_TOKEN_INSTANCE_ABI_PATH).json()['abi']
    contract = w3.eth.contract(address=staking_token_instance_address, abi=abi)

    if "getImplementation" in [func.fn_name for func in contract.all_functions()]:
        # It is a proxy contract
        implementation_address = contract.functions.getImplementation().call()
        if use_blockscout:
            abi = _get_abi(implementation_address)
        else:
            abi = requests.get(STAKING_TOKEN_INSTANCE_ABI_PATH).json()['abi']
        contract = w3.eth.contract(address=staking_token_instance_address, abi=abi)

    return contract

def _get_staking_contract_metadata(
    program_id: str, rpc: str, use_blockscout: bool = False
) -> t.Dict[str, str]:
    try:
        if program_id == NO_STAKING_PROGRAM_ID:
            return NO_STAKING_PROGRAM_METADATA

        staking_token_contract = _get_staking_token_contract(
            program_id=program_id, rpc=rpc, use_blockscout=use_blockscout
        )
        metadata_hash = staking_token_contract.functions.metadataHash().call()
        ipfs_address = IPFS_ADDRESS.format(hash=metadata_hash.hex())
        response = requests.get(ipfs_address)

        if response.status_code == 200:
            return response.json()

        raise Exception(  # pylint: disable=broad-except
            f"Failed to fetch data from {ipfs_address}: {response.status_code}"
        )
    except Exception:  # pylint: disable=broad-except
        return {
            "name": program_id,
            "description": program_id,
        }

def _get_staking_env_variables(  # pylint: disable=too-many-locals
    program_id: str, rpc: str, use_blockscout: bool = False
) -> StakingVariables:
    if program_id == NO_STAKING_PROGRAM_ID:
        return {
            "USE_STAKING": False,
            "STAKING_PROGRAM": NO_STAKING_PROGRAM_ID,
            "AGENT_ID": AGENT_ID,
            "CUSTOM_SERVICE_REGISTRY_ADDRESS": "0x9338b5153AE39BB89f50468E608eD9d764B755fD",
            "CUSTOM_SERVICE_REGISTRY_TOKEN_UTILITY_ADDRESS": "0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8",
            "MECH_CONTRACT_ADDRESS": "0x77af31De935740567Cf4fF1986D04B2c964A786a",
            "CUSTOM_OLAS_ADDRESS": ZERO_ADDRESS,
            "CUSTOM_STAKING_ADDRESS": "0x43fB32f25dce34EB76c78C7A42C8F40F84BCD237",  # Non-staking agents need to specify an arbitrary staking contract so that they can call getStakingState()
            "MECH_ACTIVITY_CHECKER_CONTRACT": ZERO_ADDRESS,
            "MIN_STAKING_BOND_OLAS": 1,
            "MIN_STAKING_DEPOSIT_OLAS": 1,
        }

    staking_token_instance_address = STAKING_PROGRAMS.get(program_id)
    staking_token_contract = _get_staking_token_contract(
        program_id=program_id, rpc=rpc, use_blockscout=use_blockscout
    )
    agent_id = staking_token_contract.functions.agentIds(0).call()
    service_registry = staking_token_contract.functions.serviceRegistry().call()
    staking_token = staking_token_contract.functions.stakingToken().call()
    service_registry_token_utility = (
        staking_token_contract.functions.serviceRegistryTokenUtility().call()
    )
    min_staking_deposit = staking_token_contract.functions.minStakingDeposit().call()
    min_staking_bond = min_staking_deposit

    if "activityChecker" in [
        func.fn_name for func in staking_token_contract.all_functions()
    ]:
        activity_checker = staking_token_contract.functions.activityChecker().call()

        if use_blockscout:
            abi = _get_abi(activity_checker)
        else:
            abi = requests.get(ACTIVITY_CHECKER_ABI_PATH).json()['abi']

        w3 = Web3(Web3.HTTPProvider(rpc))
        activity_checker_contract = w3.eth.contract(address=activity_checker, abi=abi)
        agent_mech = activity_checker_contract.functions.agentMech().call()
    else:
        activity_checker = ZERO_ADDRESS
        agent_mech = staking_token_contract.functions.agentMech().call()

    return StakingVariables({
        "USE_STAKING": program_id != NO_STAKING_PROGRAM_ID,
        "STAKING_PROGRAM": program_id,
        "AGENT_ID": agent_id,
        "CUSTOM_SERVICE_REGISTRY_ADDRESS": service_registry,
        "CUSTOM_SERVICE_REGISTRY_TOKEN_UTILITY_ADDRESS": service_registry_token_utility,
        "CUSTOM_OLAS_ADDRESS": staking_token,
        "CUSTOM_STAKING_ADDRESS": staking_token_instance_address,
        "MECH_ACTIVITY_CHECKER_CONTRACT": activity_checker,
        "MECH_CONTRACT_ADDRESS": agent_mech,
        "MIN_STAKING_BOND_OLAS": int(min_staking_bond),
        "MIN_STAKING_DEPOSIT_OLAS": int(min_staking_deposit),
    })

def configure_local_config() -> TraderConfig:
    """Configure local trader configuration."""
    path = OPERATE_HOME / "local_config.json"
    if path.exists():
        trader_config = TraderConfig.load(path)
    else:
        trader_config = TraderConfig(path)

    while not check_rpc(trader_config.gnosis_rpc):
        trader_config.gnosis_rpc = getpass.getpass("Enter a Gnosis RPC that supports eth_newFilter [hidden input]: ")

    trader_config.gnosis_rpc = trader_config.gnosis_rpc

    if trader_config.password_migrated is None:
        trader_config.password_migrated = False

    if trader_config.staking_vars is None:
        print_section("Please, select your staking program preference")
        ids = list(STAKING_PROGRAMS.keys())
        for index, key in enumerate(ids):
            metadata = _get_staking_contract_metadata(program_id=key, rpc=trader_config.gnosis_rpc)
            name = metadata["name"]
            description = metadata["description"]
            wrapped_description = textwrap.fill(
                description, width=80, initial_indent="   ", subsequent_indent="   "
            )
            print(f"{index + 1}) {name}\n{wrapped_description}\n")

        while True:
            try:
                choice = int(input(f"Enter your choice (1 - {len(ids)}): ")) - 1
                if not (0 <= choice < len(ids)):
                    raise ValueError
                program_id = ids[choice]
                break
            except ValueError:
                print(f"Please enter a valid option (1 - {len(ids)}).")

        print(f"Selected staking program: {program_id}")
        print()
        trader_config.staking_vars = _get_staking_env_variables(program_id, trader_config.gnosis_rpc)

    if trader_config.use_mech_marketplace is None:
        trader_config.use_mech_marketplace = True

    if trader_config.principal_chain is None:
        trader_config.principal_chain = DEFAULT_STAKING_CHAIN

    trader_config.store()
    return trader_config

def handle_password_migration(operate: OperateApp, config: TraderConfig) -> t.Optional[str]:
    """Handle password migration."""
    if not config.password_migrated:
        print("Add password...")
        old_password, new_password = "12345", ask_confirm_password()
        operate.user_account.update(old_password, new_password)
        if operate.wallet_manager.exists(LedgerType.ETHEREUM):
            operate.password = old_password
            wallet = operate.wallet_manager.load(LedgerType.ETHEREUM)
            wallet.crypto.dump(str(wallet.key_path), password=new_password)
            wallet.password = new_password
            wallet.store()

        config.password_migrated = True
        config.store()
        return new_password
    return None

def get_erc20_balance(ledger_api: LedgerApi, token: str, account: str) -> int:
    """Get ERC-20 token balance of an account."""
    web3 = t.cast(EthereumApi, ledger_api).api

    # ERC20 Token Standard Partial ABI
    erc20_abi = [
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "type": "function",
        }
    ]

    # Create contract instance
    contract = web3.eth.contract(address=web3.to_checksum_address(token), abi=erc20_abi)

    # Get the balance of the account
    balance = contract.functions.balanceOf(web3.to_checksum_address(account)).call()

    return balance

def get_service_template(config: TraderConfig) -> ServiceTemplate:
    """Get the service template"""
    return ServiceTemplate({
        "name": "Trader Agent",
        "hash": "bafybeifzqsbzidvhhiruhk7jf4v7tpxarvbatl72adq2omhxqgosul3uli",
        "description": "Trader agent for omen prediction markets",
        "image": "https://operate.olas.network/_next/image?url=%2Fimages%2Fprediction-agent.png&w=3840&q=75",
        "service_version": 'v0.18.7',
        "home_chain": config.principal_chain,
        "configurations": {
            config.principal_chain: ConfigurationTemplate({
                "staking_program_id": config.staking_vars["STAKING_PROGRAM"],
                "nft": "bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq",
                "rpc": config.gnosis_rpc,
                "agent_id": int(config.staking_vars["AGENT_ID"]),
                "threshold": 1,
                "use_staking": config.staking_vars["USE_STAKING"],
                'use_mech_marketplace': config.use_mech_marketplace,
                "cost_of_bond": int(config.staking_vars["MIN_STAKING_BOND_OLAS"]),
                "fund_requirements": FundRequirementsTemplate({
                    "agent": 100000000000000000,
                    "safe": 5000000000000000000,
                }),
            }),
        },
        "env_variables": {
            "GNOSIS_LEDGER_RPC": {
                'name': 'Gnosis ledger RPC',
                'description': '',
                'value': '',
                'provision_type': ServiceEnvProvisionType.COMPUTED,
            },
            'STAKING_CONTRACT_ADDRESS': {
                'name': 'Staking contract address',
                'description': '',
                'value': '',
                'provision_type': ServiceEnvProvisionType.COMPUTED,
            },
            'MECH_ACTIVITY_CHECKER_CONTRACT': {
                'name': 'Mech activity checker contract',
                'description': '',
                'value': '',
                'provision_type': ServiceEnvProvisionType.COMPUTED,
            },
            'MECH_CONTRACT_ADDRESS': {
                'name': 'Mech contract address',
                'description': '',
                'value': '',
                'provision_type': ServiceEnvProvisionType.COMPUTED,
            },
            'MECH_REQUEST_PRICE': {
                'name': 'Mech request price',
                'description': '',
                'value': '',
                'provision_type': ServiceEnvProvisionType.COMPUTED,
            },
            'USE_MECH_MARKETPLACE': {
                'name': 'Use Mech marketplace',
                'description': '',
                'value': '',
                'provision_type': ServiceEnvProvisionType.COMPUTED,
            },
            'REQUESTER_STAKING_INSTANCE_ADDRESS': {
                'name': 'Requester staking instance address',
                'description': '',
                'value': '',
                'provision_type': ServiceEnvProvisionType.COMPUTED,
            },
            'PRIORITY_MECH_ADDRESS': {
                'name': 'Priority Mech address',
                'description': '',
                'value': '',
                'provision_type': ServiceEnvProvisionType.COMPUTED,
            },
        },
    })

def get_service(manager: ServiceManager, template: ServiceTemplate) -> t.Tuple[Service, bool]:
    is_update = False
    if len(manager.json) > 0:
        old_hash = manager.json[0]["hash"]
        if old_hash == template["hash"]:
            print(f'Loading service {template["hash"]}')
            service = manager.load(
                service_config_id=manager.json[0]["service_config_id"],
            )
        else:
            print(f"Updating service from {old_hash} to " + template["hash"])
            service = manager.update(
                service_config_id=manager.json[0]["service_config_id"],
                service_template=template,
            )
            is_update = True
    else:
        print(f'Creating service {template["hash"]}')
        service = manager.load_or_create(
            hash=template["hash"],
            service_template=template,
        )

    return service, is_update


def main(service_name: str) -> None:
    """Run service."""

    print_title(f"{service_name} Quickstart")
    print(f"This script will assist you in setting up and running the {service_name} service.")
    print()

    operate = OperateApp(home=OPERATE_HOME)
    operate.setup()

    config = configure_local_config()
    template = get_service_template(config)
    manager = operate.service_manager()
    service, is_service_update = get_service(manager, template)
    password = None

    if operate.user_account is None:
        print_section("Set up local user account")
        print("Creating a new local user account...")
        password = ask_confirm_password()
        UserAccount.new(
            password=password,
            path=operate._path / "user.json",
        )
        config.password_migrated = True
        config.store()
    else:
        password = handle_password_migration(operate, config)
        while password is None:
            password = getpass.getpass("\nEnter local user account password [hidden input]: ")
            if operate.user_account.is_valid(password=password):
                break
            password = None
            print("Invalid password!")

    operate.password = password
    if not operate.wallet_manager.exists(ledger_type=LedgerType.ETHEREUM):
        print("Creating the main wallet...")
        wallet, mnemonic = operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        wallet.password = password
        print()
        print_box(f"Please save the mnemonic phrase for the main wallet:\n{', '.join(mnemonic)}", 0, '-')
        input("Press enter to continue...")
    else:
        wallet = operate.wallet_manager.load(ledger_type=LedgerType.ETHEREUM)

    manager = operate.service_manager()
    config = load_local_config()

    for chain_name, chain_config in service.chain_configs.items():
        chain_metadata = CHAIN_ID_TO_METADATA[chain_name]
        token: str = chain_metadata["token"]

        if chain_config.ledger_config.rpc is not None:
            os.environ["CUSTOM_CHAIN_RPC"] = chain_config.ledger_config.rpc
            os.environ["OPEN_AUTONOMY_SUBGRAPH_URL"] = "https://subgraph.autonolas.tech/subgraphs/name/autonolas-staging"

        service_state: OnChainState = manager._get_on_chain_state(service, chain_name)

        chain = chain_config.ledger_config.chain
        ledger_api = wallet.ledger_api(
            chain=chain,
            rpc=chain_config.ledger_config.rpc,
        )
        
        balance_str = wei_to_token(ledger_api.get_balance(wallet.crypto.address), token)

        print(f"[{chain_name}] Main wallet balance: {balance_str}",)
        safe_exists = wallet.safes.get(chain) is not None

        operational_fund_req = chain_metadata.get("operationalFundReq")
        agent_fund_requirement = chain_config.chain_data.user_params.fund_requirements.agent
        safe_fund_requirement = chain_config.chain_data.user_params.fund_requirements.safe
        if is_service_update:
            agent_fund_requirement *= 2
            safe_fund_requirement *= 2

        safety_margin = SAFETY_MARGIN if service_state == OnChainState.NON_EXISTENT else 0
        if chain_config.chain_data.multisig != DUMMY_MULTISIG:
            safe_fund_requirement -= ledger_api.get_balance(chain_config.chain_data.multisig)
        if len(service.keys) > 0:
            agent_fund_requirement -= ledger_api.get_balance(service.keys[0].address)

        required_balance = operational_fund_req + agent_fund_requirement + safe_fund_requirement
        if required_balance > ledger_api.get_balance(wallet.crypto.address):
            required_balance += safety_margin

            print(
                f"[{chain_name}] Please make sure main wallet {wallet.crypto.address} has at least {wei_to_token(required_balance, token)}",
            )
            spinner = Halo(
                text=f"[{chain_name}] Waiting for {wei_to_token(required_balance - ledger_api.get_balance(wallet.crypto.address), token)}...",
                spinner="dots"
            )
            spinner.start()

            while ledger_api.get_balance(wallet.crypto.address) < required_balance:
                time.sleep(1)

            spinner.succeed(f"[{chain_name}] Main wallet updated balance: {wei_to_token(ledger_api.get_balance(wallet.crypto.address), token)}.")

        if not safe_exists:
            print(f"[{chain_name}] Creating Safe")
            ledger_type = LedgerType.ETHEREUM
            wallet_manager = operate.wallet_manager
            wallet = wallet_manager.load(ledger_type=ledger_type)
            backup_owner=input("Please input your backup owner (leave empty to skip): ")

            wallet.create_safe(
                chain=chain,
                rpc=chain_config.ledger_config.rpc,
                backup_owner=None if backup_owner == "" else backup_owner,
            )

        print_section(f"[{chain_name}] Set up the service in the Olas Protocol")

        safe_address = wallet.safes[chain]
        top_up = agent_fund_requirement + safe_fund_requirement + safety_margin

        if top_up > 0:
            print(
                f"[{chain_name}] Ensuring address {safe_address} has at least {wei_to_token(top_up, token)}."
            )
            spinner = Halo(
                text=f"[{chain_name}] Transfering {wei_to_token(top_up - ledger_api.get_balance(safe_address), token)} to safe...",
                spinner="dots",
            )
            spinner.start()

            while ledger_api.get_balance(safe_address) < top_up:
                print(f"[{chain_name}] Funding Safe")
                wallet.transfer(
                    to=t.cast(str, wallet.safes[chain]),
                    amount=int(top_up - ledger_api.get_balance(safe_address)),
                    chain=chain,
                    from_safe=False,
                    rpc=chain_config.ledger_config.rpc,
                )
                time.sleep(1)

            spinner.succeed(f"[{chain_name}] Safe updated balance: {wei_to_token(ledger_api.get_balance(safe_address), token)}.")

        if chain_config.chain_data.user_params.use_staking:
            olas_address = config.staking_vars["CUSTOM_OLAS_ADDRESS"]
            if service_state in (
                OnChainState.NON_EXISTENT,
                OnChainState.PRE_REGISTRATION,
            ):
                required_olas = (
                    config.staking_vars["MIN_STAKING_BOND_OLAS"]
                    + config.staking_vars["MIN_STAKING_BOND_OLAS"]
                )
            elif service_state == OnChainState.ACTIVE_REGISTRATION:
                required_olas = config.staking_vars["MIN_STAKING_BOND_OLAS"]
            else:
                required_olas = 0

            if required_olas > 0:
                print(f"[{chain_name}] Please make sure address {safe_address} has at least {wei_to_token(required_olas, STAKED_BONDING_TOKEN)}")

                spinner = Halo(
                    text=f"[{chain_name}] Waiting for {wei_to_token(required_olas - get_erc20_balance(ledger_api, olas_address, safe_address), STAKED_BONDING_TOKEN)}...",
                    spinner="dots",
                )
                spinner.start()
                while get_erc20_balance(ledger_api, olas_address, safe_address) < required_olas:
                    time.sleep(1)

                balance = get_erc20_balance(ledger_api, olas_address, safe_address) / 10 ** 18
                spinner.succeed(f"[{chain_name}] Safe updated balance: {balance} {STAKED_BONDING_TOKEN}")

    print_section(f"Deploying on-chain service on {chain_name}")
    print_box("PLEASE, DO NOT INTERRUPT THIS PROCESS.")
    print("Cancelling the on-chain service update prematurely could lead to an inconsistent state of the Safe or the on-chain service state, which may require manual intervention to resolve.")
    manager.deploy_service_onchain_from_safe(service_config_id=service.service_config_id)

    print_section("Funding the service")
    manager.fund_service(service_config_id=service.service_config_id)
    print()

    print_section("Deploying the service")
    manager.deploy_service_locally(service_config_id=service.service_config_id, use_docker=True)

    print()
    print_section(f"Starting the {service_name} service")


if __name__ == "__main__":
    main(service_name="Trader")
