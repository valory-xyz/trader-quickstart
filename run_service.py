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

from scripts.choose_staking import NO_STAKING_PROGRAM_ID, STAKING_PROGRAMS, _get_staking_contract_metadata, get_staking_env_variables, _prompt_select_staking_program
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
from aea_ledger_ethereum import EthereumApi
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

load_dotenv()

SUGGESTED_TOP_UP_DEFAULT = 500_000_000_000_000_000
COST_OF_BOND = 10_000_000_000_000_000
MONTHLY_GAS_ESTIMATE = 10_000_000_000_000_000_000
SAFETY_MARGIN = 100_000_000_000_000
STAKED_BONDING_TOKEN = "OLAS"
AGENT_ID = 14
WARNING_ICON = colored('\u26A0', 'yellow')
OPERATE_HOME = Path.cwd() / ".operate"
DEFAULT_STAKING_CHAIN = "gnosis"
CHAIN_ID_TO_METADATA = {
    "gnosis": {
        "name": "Gnosis",
        "token": "xDAI",
        "operationalFundReq": SUGGESTED_TOP_UP_DEFAULT,  # fund for master wallet
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
    use_staking: t.Optional[bool] = None
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

    if trader_config.use_staking is None:
        print("Please, select your staking program preference")
        print("----------------------------------------------")
        ids = list(STAKING_PROGRAMS.keys())
        for index, key in enumerate(ids):
            metadata = _get_staking_contract_metadata(program_id=key)
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
        trader_config.use_staking = program_id == NO_STAKING_PROGRAM_ID
        for key, value in get_staking_env_variables(program_id).items():
            os.environ[key] = value

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
        "service_version": 'v0.21.1',
        "home_chain": config.principal_chain,
        "configurations": {
            config.principal_chain: ConfigurationTemplate({
                "staking_program_id": NO_STAKING_PROGRAM_ID,  # will be overwritten by user response
                "nft": "bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq",
                "rpc": config.gnosis_rpc,
                "agent_id": AGENT_ID,
                "threshold": 1,
                "use_staking": config.use_staking,
                'use_mech_marketplace': config.use_mech_marketplace,
                "cost_of_bond": COST_OF_BOND,
                'monthly_gas_estimate': MONTHLY_GAS_ESTIMATE,
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

def get_service(manager: ServiceManager, template: ServiceTemplate) -> Service:
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
    else:
        print(f'Creating service {template["hash"]}')
        service = manager.load_or_create(
            hash=template["hash"],
            service_template=template,
        )

    return service


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
    service = get_service(manager, template)
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
            password = getpass.getpass("Enter local user account password: ")
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

        service_exists = manager._get_on_chain_state(service, chain_name) != OnChainState.NON_EXISTENT

        chain = chain_config.ledger_config.chain
        ledger_api = wallet.ledger_api(
            chain=chain,
            rpc=chain_config.ledger_config.rpc,
        )
        
        balance_str = wei_to_token(ledger_api.get_balance(wallet.crypto.address), token)

        print(f"[{chain_name}] Main wallet balance: {balance_str}",)
        safe_exists = wallet.safes.get(chain) is not None

        agent_fund_requirement = chain_config.chain_data.user_params.fund_requirements.agent
        safe_fund_requirement = chain_config.chain_data.user_params.fund_requirements.safe
        operational_fund_req = chain_metadata.get("operationalFundReq")
        safety_margin = 0 if service_exists else 100_000_000_000_000

        operational_fund_req -= ledger_api.get_balance(wallet.crypto.address)
        if chain_config.chain_data.multisig != DUMMY_MULTISIG:
            safe_fund_requirement -= ledger_api.get_balance(chain_config.chain_data.multisig)
        if len(service.keys) > 0:
            agent_fund_requirement -= ledger_api.get_balance(service.keys[0].address)

        required_balance = operational_fund_req + agent_fund_requirement + safe_fund_requirement
        if required_balance > ledger_api.get_balance(wallet.crypto.address):
            required_balance += safety_margin
            required_balance = (required_balance // 10**12) * 10**12

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
                f"[{chain_name}] Please make sure address {safe_address} has at least {wei_to_token(top_up, token)}."
            )
            spinner = Halo(
                text=f"[{chain_name}] Waiting for {wei_to_token(top_up - ledger_api.get_balance(safe_address), token)}...",
                spinner="dots",
            )
            spinner.start()

            while ledger_api.get_balance(safe_address) < top_up:
                print(f"[{chain_name}] Funding Safe")
                wallet.transfer(
                    to=t.cast(str, wallet.safes[chain]),
                    amount=int(top_up),
                    chain=chain,
                    from_safe=False,
                    rpc=chain_config.ledger_config.rpc,
                )
                time.sleep(1)

            spinner.succeed(f"[{chain_name}] Safe updated balance: {wei_to_token(ledger_api.get_balance(safe_address), token)}.")

        if chain_config.chain_data.user_params.use_staking and not service_exists:
            print(f"[{chain_name}] Please make sure address {safe_address} has at least {wei_to_token(COST_OF_BOND, STAKED_BONDING_TOKEN)}")

            spinner = Halo(
                text=f"[{chain_name}] Waiting for {STAKED_BONDING_TOKEN}...",
                spinner="dots",
            )
            spinner.start()
            olas_address = OLAS[chain]
            while get_erc20_balance(ledger_api, olas_address, safe_address) < COST_OF_BOND:
                time.sleep(1)

            balance = get_erc20_balance(ledger_api, olas_address, safe_address) / 10 ** 18
            spinner.succeed(f"[{chain_name}] Safe updated balance: {balance} {STAKED_BONDING_TOKEN}")

    print_section(f"Deploying on-chain service {chain_config.chain_data.token} on {chain_name}")
    print()
    print_box("PLEASE, DO NOT INTERRUPT THIS PROCESS.")
    print()
    print("Cancelling the on-chain service update prematurely could lead to an inconsistent state of the Safe or the on-chain service state, which may require manual intervention to resolve.")
    print()
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
