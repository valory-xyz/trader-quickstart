from pathlib import Path
from operate.cli import OperateApp
from operate.types import (
    LedgerType,
    ServiceTemplate,
    ConfigurationTemplate,
    FundRequirementsTemplate,
    OnChainUserParams,
)
from operate.account.user import UserAccount
import time
import sys
import getpass
import requests
from halo import Halo
from termcolor import colored

OLAS_BALANCE_REQUIRED_TO_BOND = 10_000_000_000_000_000_000
OLAS_BALANCE_REQUIRED_TO_STAKE = 10_000_000_000_000_000_000
XDAI_BALANCE_REQUIRED_TO_BOND = 10_000_000_000_000_000
SUGGESTED_TOP_UP_DEFAULT = 50_000_000_000_000_000
SUGGESTED_SAFE_TOP_UP_DEFAULT = 500_000_000_000_000_000
MASTER_WALLET_MIMIMUM_BALANCE = 1_000_000_000_000_000_000
WARNING_ICON = colored('\u26A0', 'yellow')
OPERATE_HOME = Path.cwd() / ".operate2"

TEMPLATE = ServiceTemplate(
    {
        "name": "trader_service",
        "hash": "bafybeicxdpkuk5z5zfbkso7v5pywf4v7chxvluyht7dtgalg6dnhl7ejoe",
        "image": "",
        "description": "trader service",
        "configuration": ConfigurationTemplate(
            {
                "rpc": "",
                "nft": "bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq",
                "agent_id": 14,
                "cost_of_bond": XDAI_BALANCE_REQUIRED_TO_BOND,
                "olas_cost_of_bond": OLAS_BALANCE_REQUIRED_TO_BOND,
                "olas_required_to_stake": OLAS_BALANCE_REQUIRED_TO_STAKE,
                "threshold": 1,
                "use_staking": False,
                "fund_requirements": FundRequirementsTemplate(
                    {
                        "agent": SUGGESTED_TOP_UP_DEFAULT,
                        "safe": SUGGESTED_SAFE_TOP_UP_DEFAULT,
                    }
                ),
            }
        ),
    }
)


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
    return f"{wei_to_unit(wei):.2f} {token}"


def ask_confirm_password() -> str:
    password = getpass.getpass("Please enter a password: ")
    confirm_password = getpass.getpass("Please confirm your password: ")

    if password == confirm_password:
        return password
    else:
        print("Passwords do not match. Terminating.")
        sys.exit(1)


def check_rpc(rpc_url: str) -> None:
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
        sys.exit(1)

    rcp_error_message = rpc_response.get("error", {}).get("message", "Exception processing RCP response")

    if rcp_error_message == "Exception processing RCP response":
        print("Error: The received RCP response is malformed. Please verify the RPC address and/or RCP behavior.")
        print("  Received response:")
        print("  ", rpc_response)
        print("")
        print("Terminating script.")
        sys.exit(1)
    elif rcp_error_message == "Out of requests":
        print("Error: The provided RCP is out of requests.")
        print("Terminating script.")
        sys.exit(1)
    elif rcp_error_message == "The method eth_newFilter does not exist/is not available":
        print("Error: The provided RPC does not support 'eth_newFilter'.")
        print("Terminating script.")
        sys.exit(1)
    
    spinner.succeed("RPC checks passed.")


def main() -> None:
    """Run service."""

    print_title("Trader Quickstart")
    print("This script will assist you in setting up and running the Trader service.")
    print()

    print_section("Set up local user account")
    app = OperateApp(
        home=OPERATE_HOME,
    )
    app.setup()

    if app.user_account is None:
        print("Creating a new local user account...")
        password = ask_confirm_password()
        UserAccount.new(
            password=password,
            path=app._path / "user.json",
        )
    else:
        password = getpass.getpass("Enter local user account password: ")
        if not app.user_account.is_valid(password=password):
            print("Invalid password!")
            sys.exit(1)

    app.password = password
    if not app.wallet_manager.exists(ledger_type=LedgerType.ETHEREUM):
        print("Creating the main wallet...")
        wallet, mnemonic = app.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        wallet.password = password
        print()
        print_box(f"Please save the mnemonic phrase for the main wallet:\n{', '.join(mnemonic)}", 0 , '-')
        input("Press enter to continue...")
    else:
        wallet = app.wallet_manager.load(ledger_type=LedgerType.ETHEREUM)

    manager = app.service_manager()

    service_path = app._services / TEMPLATE["hash"]
    if not service_path.exists():
        rpc_url = getpass.getpass("Please enter your RPC: ")
        TEMPLATE["configuration"]["rpc"] = rpc_url
        check_rpc(rpc_url=rpc_url)

    service = manager.create_or_load(
        hash=TEMPLATE["hash"],
        rpc=TEMPLATE["configuration"].get("rpc"),
        on_chain_user_params=OnChainUserParams.from_json(
            obj=TEMPLATE["configuration"],
        ),
    )

    ledger_api = wallet.ledger_api(
        service.ledger_config.chain,
        rpc=TEMPLATE["configuration"].get("rpc"),
    )

    print(f"Main wallet balance: {wei_to_token(ledger_api.get_balance(wallet.crypto.address))}")
    spinner = Halo(text=f"Please make sure main wallet {wallet.crypto.address} has at least {wei_to_token(MASTER_WALLET_MIMIMUM_BALANCE)}.", spinner="dots")
    spinner.start()

    while ledger_api.get_balance(wallet.crypto.address) < MASTER_WALLET_MIMIMUM_BALANCE:
        time.sleep(1)

    spinner.succeed(f"Main wallet updated balance: {wei_to_token(ledger_api.get_balance(wallet.crypto.address))}.")
    print()

    print_section("Set up the service in the Olas Protocol")

    manager.deploy_service_onchain(hash=service.hash)
    manager.stake_service_on_chain(hash=service.hash)
    manager.fund_service(hash=service.hash)

    print()
    print_section("Run the service")

    manager.deploy_service_locally(hash=service.hash)


if __name__ == "__main__":
    main()
