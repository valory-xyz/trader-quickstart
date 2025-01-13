# -*- coding: utf-8 -*-
"""Test run_service.py script using pytest for reliable automation."""

import re
import sys
import logging
import pexpect 
import os
import time
import pytest
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from termcolor import colored
from colorama import init
from web3 import Web3
from eth_account import Account
import requests
import docker
from dotenv import load_dotenv
from operate.constants import HEALTH_CHECK_URL
from operate.operate_types import Chain, LedgerType


# Initialize colorama and load environment
init()
load_dotenv()

STARTUP_WAIT = 10
SERVICE_INIT_WAIT = 60
CONTAINER_STOP_WAIT = 20

# Handle the distutils warning
os.environ['SETUPTOOLS_USE_DISTUTILS'] = 'stdlib'

def get_service_config(config_path: str) -> dict:
    """
    Get service-specific configuration.
    
    Args:
        config_path (str): Path to the config file
        
    Returns:
        dict: Dictionary containing service configuration with container name and health check URL
        
    Raises:
        ValueError: If no matching service configuration is found
    """
    # Service configuration mappings with aliases
    SERVICE_CONFIGS = {
        # Optimus service and variants
        "optimus": {
            "container_name": "optimus",
            "health_check_url": HEALTH_CHECK_URL,
        },
        "modius": {
            "container_name": "optimus", 
            "health_check_url": HEALTH_CHECK_URL,
        },
        # Traderpearl service and variants
        "traderpearl": {
            "container_name": "traderpearl",
            "health_check_url": HEALTH_CHECK_URL,
        }
    }
    
    # Additional name mappings
    SERVICE_ALIASES = {
        "predict_trader": "traderpearl"
    }
    
    # Convert config path to lowercase for case-insensitive matching
    config_path_lower = config_path.lower()
    
    # Check for direct service match first
    for service_name, config in SERVICE_CONFIGS.items():
        if service_name in config_path_lower:
            return config
            
    # Check aliases if no direct match found
    for alias, service_name in SERVICE_ALIASES.items():
        if alias in config_path_lower:
            return SERVICE_CONFIGS[service_name]
            
    raise ValueError(f"No matching service configuration found for {config_path}")

def check_docker_status(logger: logging.Logger, config_path: str) -> bool:
    """
    Check if Docker ABCI containers are running properly.
    Only checks containers ending with 'abci_0', ignoring Tendermint containers.
    Handles container names with format: {trimmed_service_name}{unique_id}_abci_0
    """
    service_config = get_service_config(config_path)
    container_base_name = service_config["container_name"]
    
    # Use filters with just "_abci_0" suffix to catch all ABCI containers
    abci_suffix = "_abci_0"
    
    max_retries = 3
    retry_delay = 20
    
    for attempt in range(max_retries):
        logger.info(f"Checking ABCI container status (attempt {attempt + 1}/{max_retries})")
        try:
            client = docker.from_env()
            
            # List all containers that have the ABCI suffix and start with the base name
            all_containers = client.containers.list(all=True)
            abci_containers = [c for c in all_containers 
                             if c.name.endswith(abci_suffix) and 
                             c.name.startswith(container_base_name)]
            
            running_containers = client.containers.list()
            running_abci = [c for c in running_containers 
                          if c.name.endswith(abci_suffix) and 
                          c.name.startswith(container_base_name)]
            
            if not abci_containers:
                logger.error(f"No ABCI container found with base name {container_base_name} (attempt {attempt + 1}/{max_retries})")
                if attempt == max_retries - 1:
                    return False
                logger.info(f"Waiting {retry_delay} seconds before retry...")
                time.sleep(retry_delay)
                continue
            
            # Should only be one ABCI container
            abci_container = abci_containers[0]
            logger.info(f"ABCI Container {abci_container.name} status: {abci_container.status}")
            
            if abci_container.status == "exited":
                inspect = client.api.inspect_container(abci_container.id)
                exit_code = inspect['State']['ExitCode']
                logger.error(f"ABCI Container {abci_container.name} exited with code {exit_code}")
                logs = abci_container.logs(tail=50).decode('utf-8')
                logger.error(f"ABCI Container logs:\n{logs}")
                
            elif abci_container.status == "restarting":
                logger.error(f"ABCI Container {abci_container.name} is restarting. Last logs:")
                logs = abci_container.logs(tail=50).decode('utf-8')
                logger.error(f"ABCI Container logs:\n{logs}")
            
            if not running_abci:
                if attempt == max_retries - 1:
                    return False
                logger.info(f"Waiting {retry_delay} seconds for ABCI container to start...")
                time.sleep(retry_delay)
                continue
            
            # Check if ABCI container is running
            if abci_container.status == "running":
                logger.info(f"ABCI Container {abci_container.name} is running")
                return True
            
            if attempt == max_retries - 1:
                return False
                
            logger.info(f"ABCI container not running, waiting {retry_delay} seconds...")
            time.sleep(retry_delay)
            
        except Exception as e:
            logger.error(f"Error checking Docker status: {str(e)}")
            if attempt == max_retries - 1:
                return False
            logger.info(f"Waiting {retry_delay} seconds before retry...")
            time.sleep(retry_delay)
    
    return False

def check_service_health(logger: logging.Logger, config_path: str) -> tuple[bool, dict]:
    """Enhanced service health check with metrics."""
    service_config = get_service_config(config_path)
    health_check_url = service_config["health_check_url"]
    
    metrics = {
        'response_time': None,
        'status_code': None,
        'error': None,
        'successful_checks': 0,
        'total_checks': 0
    }
    
    start_monitoring = time.time()
    while time.time() - start_monitoring < 120:  # Run for 2 minutes
        try:
            metrics['total_checks'] += 1
            start_time = time.time()
            response = requests.get(health_check_url, timeout=10)
            metrics['response_time'] = time.time() - start_time
            metrics['status_code'] = response.status_code
            
            if response.status_code == 200:
                metrics['successful_checks'] += 1
                logger.info(f"Health check passed (response time: {metrics['response_time']:.2f}s)")
            else:
                logger.error(f"Health check failed - Status: {response.status_code}")
                return False, metrics
                
        except requests.exceptions.Timeout:
            metrics['error'] = 'timeout'
            logger.error("Health check timeout")
            return False, metrics
        except requests.exceptions.ConnectionError as e:
            metrics['error'] = 'connection_error'
            logger.error(f"Connection error: {str(e)}")
            return False, metrics
        except Exception as e:
            metrics['error'] = str(e)
            logger.error(f"Unexpected error in health check: {str(e)}")
            return False, metrics
            
        elapsed = time.time() - start_time
        if elapsed < 5:
            time.sleep(5 - elapsed)
    
    logger.info(f"Health check completed successfully - {metrics['successful_checks']} checks passed")
    return True, metrics    

def get_token_config():
    """Get token configurations for different chains"""
    return {
        "mode": {
            "USDC": {
                "address": "0xd988097fb8612cc24eeC14542bC03424c656005f",
                "decimals": 6
            },
            "OLAS": {
                "address": "your_olas_address",
                "decimals": 18
            }
        },
        "optimism": {
            "USDC": {
                "address": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
                "decimals": 6
            }
        },
        "base": {
            "USDC": {
                "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "decimals": 6
            }
        }
    }

def handle_erc20_funding(output: str, logger: logging.Logger, rpc_url: str) -> str:
    """Handle funding requirement using Tenderly API for ERC20 tokens."""
    pattern = r"\[(optimistic|base|mode)\].*Please make sure Master (?:EOA|Safe) (0x[a-fA-F0-9]{40}) has at least ([0-9.]+) ([A-Z]+)"
    logger.info(f"Funding with RPC : {rpc_url}")
    match = re.search(pattern, output)
    if match:
        chain = match.group(1)
        wallet_address = match.group(2)
        required_amount = float(match.group(3))
        token_symbol = match.group(4)

        # Map chain identifier to config key
        chain_map = {
            "optimistic": "optimism",
            "base": "base",
            "mode": "mode"
        }
        chain_key = chain_map.get(chain, "mode")  # Default to mode if chain not found
        
        token_configs = get_token_config()
        if chain_key not in token_configs or token_symbol not in token_configs[chain_key]:
            raise Exception(f"Token {token_symbol} not configured for chain {chain_key}")
            
        token_config = token_configs[chain_key][token_symbol]
        token_address = token_config["address"]
        decimals = token_config["decimals"]
        
        try:
            amount_in_units = int(required_amount * (10 ** decimals))
            amount_hex = hex(amount_in_units)
            
            headers = {"Content-Type": "application/json"}
            payload = {
                "jsonrpc": "2.0",
                "method": "tenderly_setErc20Balance",
                "params": [token_address, wallet_address, amount_hex],
                "id": "1"
            }
            
            logger.info(f"Funding {required_amount} {token_symbol} on {chain_key} chain")
            response = requests.post(rpc_url, headers=headers, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                if 'error' in result:
                    raise Exception(f"Tenderly API error: {result['error']}")
                    
                logger.info(f"Successfully funded {required_amount} {token_symbol} to {wallet_address} on {chain_key} chain")
                
                try:
                    w3 = Web3(Web3.HTTPProvider(rpc_url))
                    erc20_abi = [
                        {
                            "constant": True,
                            "inputs": [{"name": "_owner", "type": "address"}],
                            "name": "balanceOf",
                            "outputs": [{"name": "balance", "type": "uint256"}],
                            "type": "function"
                        }
                    ]
                    token_contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=erc20_abi)
                    new_balance = token_contract.functions.balanceOf(wallet_address).call()
                    logger.info(f"New balance: {new_balance / (10 ** decimals)} {token_symbol}")
                except Exception as e:
                    logger.warning(f"Could not verify balance: {str(e)}")
                
                return ""
            else:
                error_msg = f"Tenderly API request failed with status {response.status_code}"
                if response.text:
                    error_msg += f". Response: {response.text}"
                raise Exception(error_msg)
                
        except Exception as e:
            logger.error(f"Failed to fund {token_symbol}: {str(e)}")
            raise
    
    return ""

def handle_native_funding(output: str, logger: logging.Logger, rpc_url: str, config_type: str = "") -> str:
    """Handle funding requirement using Tenderly API for native tokens."""
    patterns = [
        r"Please make sure Master EOA (0x[a-fA-F0-9]{40}) has at least (\d+\.\d+) (?:ETH|xDAI)",
        r"Please make sure Master Safe (0x[a-fA-F0-9]{40}) has at least (\d+\.\d+) (?:ETH|xDAI)"
    ]

    logger.info(f"Funding with RPC : {rpc_url}")
    
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            wallet_address = match.group(1)
            required_amount = float(match.group(2))
            wallet_type = "EOA" if "EOA" in pattern else "Safe"
            
            if "modius" in config_type.lower():
                original_amount = required_amount
                required_amount = 0.6
                logger.info(f"Modius detected: Increasing funding from {original_amount} ETH to {required_amount} ETH for gas buffer")
            if "optimus" in config_type.lower():
                original_amount = required_amount
                required_amount = 100
                logger.info(f"Optimus detected: Increasing funding from {original_amount} ETH to {required_amount} ETH for gas buffer")
            
            try:
                w3 = Web3(Web3.HTTPProvider(rpc_url))
                amount_wei = w3.to_wei(required_amount, 'ether')
                amount_hex = hex(amount_wei)
                
                headers = {"Content-Type": "application/json"}
                payload = {
                    "jsonrpc": "2.0",
                    "method": "tenderly_addBalance",
                    "params": [wallet_address, amount_hex],
                    "id": "1"
                }
                
                response = requests.post(rpc_url, headers=headers, json=payload)
                
                if response.status_code == 200:
                    result = response.json()
                    if 'error' in result:
                        raise Exception(f"Tenderly API error: {result['error']}")
                        
                    chain_id = w3.eth.chain_id
                    chain = Chain.from_id(chain_id)
                    token_name = "ETH" if chain.ledger_type == LedgerType.ETHEREUM else "xDAI"
                    
                    logger.info(f"Successfully funded {required_amount} {token_name} to {wallet_type} {wallet_address}")

                    if "optimus" in config_type.lower():
                        logger.info("Adding additional delay for Optimus safe creation...")
                        time.sleep(5)

                    new_balance = w3.eth.get_balance(wallet_address)
                    logger.info(f"New balance: {w3.from_wei(new_balance, 'ether')} {token_name}")
                    return ""
                else:
                    raise Exception(f"Tenderly API request failed with status {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Failed to fund {wallet_type}: {str(e)}")
                raise
    
    return ""

def create_funding_handler(rpc_url: str, config_type: str):
    """Create a funding handler with the specified RPC URL and config type."""
    def handler(output: str, logger: logging.Logger) -> str:
        return handle_native_funding(output, logger, rpc_url, config_type)
    return handler

def create_token_funding_handler(rpc_url: str):
    """Create a token funding handler with the specified RPC URL."""
    def handler(output: str, logger: logging.Logger) -> str:
        return handle_erc20_funding(output, logger, rpc_url)
    return handler


def check_shutdown_logs(logger: logging.Logger, config_path: str) -> bool:
    """Check shutdown logs for errors."""
    try:
        client = docker.from_env()
        service_config = get_service_config(config_path)
        container_name = service_config["container_name"]
        
        containers = client.containers.list(filters={"name": container_name})
        
        for container in containers:
            logs = container.logs().decode('utf-8')
            if "Error during shutdown" in logs or "Failed to gracefully stop" in logs:
                logger.error(f"Found shutdown errors in container {container.name} logs")
                return False
                
        logger.info("Shutdown logs check passed")
        return True
    except Exception as e:
        logger.error(f"Error checking shutdown logs: {str(e)}")
        return False

def ensure_service_stopped(config_path: str, temp_dir: str, logger: logging.Logger) -> bool:
    """
    Stop service only if it exists, with verification.
    Returns True if service is confirmed stopped (or wasn't running).
    """
    try:
        # First check if Docker daemon is running
        try:
            client = docker.from_env()
            client.ping()
        except Exception as docker_err:
            logger.error(f"Docker daemon not accessible: {str(docker_err)}")
            logger.error("Please ensure Docker is running before starting the tests")
            raise RuntimeError("Docker daemon not running or not accessible. Please start Docker first.") from docker_err

        service_config = get_service_config(config_path)
        container_name = service_config["container_name"]
        
        # Check if service is running
        containers = client.containers.list(filters={"name": container_name})
        if not containers:
            logger.info("No running service found, skipping stop")
            return True
            
        logger.info(f"Found {len(containers)} running containers, stopping service")
        
        # Single attempt with proper force stop
        process = pexpect.spawn(
            f'bash ./stop_service.sh {config_path}',
            encoding='utf-8',
            timeout=30,
            cwd=temp_dir
        )
        process.expect(pexpect.EOF)
        time.sleep(CONTAINER_STOP_WAIT)
        
        # Check if any containers are still running
        remaining_containers = client.containers.list(filters={"name": container_name})
        if remaining_containers:
            logger.info("Some containers still running after stop_service, forcing stop...")
            for container in remaining_containers:
                try:
                    container.stop(timeout=30)
                    container.remove(force=True)
                except Exception as container_err:
                    logger.error(f"Error forcing container stop: {str(container_err)}")
                    return False
        
        return True
        
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"Error stopping service: {str(e)}")
        return False
    
class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors."""
    def format(self, record):
        is_input = getattr(record, 'is_input', False)
        is_expect = getattr(record, 'is_expect', False)
        
        if is_input:
            record.msg = colored(record.msg, 'yellow')
        elif is_expect:
            record.msg = colored(record.msg, 'cyan')
        else:
            record.msg = colored(record.msg, 'green')
        
        return super().format(record)

def setup_logging(log_file: Optional[Path] = None) -> logging.Logger:
    """Set up logging configuration."""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Get the logger
    logger = logging.getLogger('test_runner')
    
    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    logger.setLevel(logging.DEBUG)
    
    # Only add console handler if none exists
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_formatter = ColoredFormatter(
        '%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    if log_file:
        log_path = logs_dir / log_file
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger

def get_config_files():
    """Dynamically get all JSON config files from configs directory."""
    config_dir = Path("configs")
    if not config_dir.exists():
        raise FileNotFoundError("configs directory not found")
        
    config_files = list(config_dir.glob("*.json"))
    if not config_files:
        raise FileNotFoundError("No JSON config files found in configs directory")
    
    logger = logging.getLogger('test_runner')
    logger.info(f"Found config files: {[f.name for f in config_files]}")
    
    return [str(f) for f in config_files]

def validate_backup_owner(backup_owner: str) -> str:
    """Validate and normalize backup owner address."""
    if not isinstance(backup_owner, str):
        raise ValueError("Backup owner must be a string")
    if not Web3.is_address(backup_owner):
        raise ValueError(f"Invalid backup owner address: {backup_owner}")
    return Web3.to_checksum_address(backup_owner)

def get_base_config() -> dict:
    """Get base configuration common to all services."""
    base_config = {
        "TEST_PASSWORD": os.getenv('TEST_PASSWORD', 'test'),
        "BACKUP_WALLET": validate_backup_owner("0x802D8097eC1D49808F3c2c866020442891adde57"),
        "STAKING_CHOICE": '1'
    }
    
    # Common prompts used across all services
    base_prompts = {
        r"input your password": base_config["TEST_PASSWORD"] + "\n",
        r"confirm your password": base_config["TEST_PASSWORD"] + "\n",
        r"Enter your choice": base_config["STAKING_CHOICE"] + "\n",
        r"backup owner \(leave empty to skip\)": base_config["BACKUP_WALLET"] + "\n",  # Escape parentheses
        r"Press enter to continue": "\n",
        r"press enter": "\n",
        r"Enter local user account password \[hidden input\]": base_config["TEST_PASSWORD"] + "\n",
        r"Please enter": "\n",
    }
    
    return {"config": base_config, "prompts": base_prompts}

def get_config_specific_settings(config_path: str) -> dict:
    """Get config specific prompts and test settings."""
    # Get base configuration
    base = get_base_config()
    base_config = base["config"]
    prompts = base["prompts"].copy()
    
    if "modius" in config_path.lower():
        # Modius specific settings
        test_config = {
            **base_config,  # Include base config
            "RPC_URL": os.getenv('MODIUS_RPC_URL'),
        }

        # Add Modius-specific prompts
        prompts.update({
                r"eth_newFilter \[hidden input\]": test_config["RPC_URL"] + "\n",
                r"Please make sure Master (EOA|Safe) .*has at least.*(?:ETH|xDAI)": 
                    lambda output, logger: create_funding_handler(test_config["RPC_URL"], "modius")(output, logger),
                r"Please make sure Master (?:EOA|Safe) .*has at least.*(?:USDC|OLAS)":
                    lambda output, logger: create_token_funding_handler(test_config["RPC_URL"])(output, logger)
        })
        
    elif "optimus" in config_path.lower():
        # Optimus settings with multiple RPCs
        test_config = {
            **base_config,  # Include base config
            "MODIUS_RPC_URL": os.getenv('MODIUS_RPC_URL'),
            "OPTIMISM_RPC_URL": os.getenv('OPTIMISM_RPC_URL'),
            "BASE_RPC_URL": os.getenv('BASE_RPC_URL'),
        }

        def get_chain_rpc(output: str, logger: logging.Logger) -> str:
            """Get RPC URL based on chain prefix in the output."""
            if "[mode]" in output:
                logger.info("Using Mode RPC URL")
                return test_config["MODIUS_RPC_URL"]
            elif "[base]" in output:
                logger.info("Using Base RPC URL")
                return test_config["BASE_RPC_URL"]
            elif "[optimistic]" in output:
                logger.info("Using Optimism RPC URL")
                return test_config["OPTIMISM_RPC_URL"]
            else:
                logger.info("Using Mode RPC URL as default")
                return test_config["MODIUS_RPC_URL"]

        prompts.update({
            r"Enter a Mode RPC that supports eth_newFilter \[hidden input\]": test_config["MODIUS_RPC_URL"] + "\n",
            r"Enter a Optimism RPC that supports eth_newFilter \[hidden input\]": test_config["OPTIMISM_RPC_URL"] + "\n",
            r"Enter a Base RPC that supports eth_newFilter \[hidden input\]": test_config["BASE_RPC_URL"] + "\n",
            r"\[(?:optimistic|base|mode)\].*Please make sure Master (EOA|Safe) .*has at least.*(?:ETH|xDAI)": 
                lambda output, logger: create_funding_handler(get_chain_rpc(output, logger), "optimus")(output, logger),
            r"\[(?:optimistic|base|mode)\].*Please make sure Master (?:EOA|Safe) .*has at least.*(?:USDC|OLAS)":
                lambda output, logger: create_token_funding_handler(get_chain_rpc(output, logger))(output, logger)
        })
        
    else:
        # Default PredictTrader settings
        test_config = {
            **base_config,  # Include base config
            "RPC_URL": os.getenv('GNOSIS_RPC_URL', '')
        }

        # Add PredictTrader-specific prompts
        prompts.update({
            r"eth_newFilter \[hidden input\]": test_config["RPC_URL"] + "\n",
            r"Please make sure Master (EOA|Safe) .*has at least.*(?:ETH|xDAI)": 
                lambda output, logger: create_funding_handler(test_config["RPC_URL"], "predict_trader")(output, logger)
        })

    return {"prompts": prompts, "test_config": test_config}

def cleanup_directory(path: str, logger: logging.Logger) -> bool:
    """
    Platform-agnostic directory cleanup.
    """
    def remove_readonly(func, path, _):
        os.chmod(path, 0o666)
        func(path)

    try:
        if os.path.exists(path):
            shutil.rmtree(path, onerror=remove_readonly)
            return True
        return True
    except Exception as e:
        logger.debug(f"Cleanup failed: {e}")
        return False

class BaseTestService:
    """Base test service class containing core test logic."""
    config_path = None
    config_settings = None
    logger = None
    child = None
    temp_dir = None
    original_cwd = None
    temp_env = None
    _setup_complete = False

    @classmethod
    def setup_class(cls):
        """Setup for all tests"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        cls.log_file = Path(f'test_run_service_{timestamp}.log')
        cls.logger = setup_logging(cls.log_file)
        
        # Load config specific settings
        cls.config_settings = get_config_specific_settings(cls.config_path)
        cls.logger.info(f"Loaded settings for config: {cls.config_path}")
        
        # Create temporary directory and store original path
        cls.original_cwd = os.getcwd()
        cls.temp_dir = tempfile.TemporaryDirectory(prefix='operate_test_')
        cls.logger.info(f"Created temporary directory: {cls.temp_dir.name}")
        
        # Define exclusion patterns
        exclude_patterns = [
            '.git',              # Git directory
            '.pytest_cache',     # Pytest cache
            '__pycache__',      # Python cache
            '*.pyc',            # Python compiled files
            'logs',             # Log files
            '*.log',            # Log files
            '.env'              # Environment files
        ]
        
        def ignore_patterns(path, names):
            return set(n for n in names if any(p in n or any(p.endswith(n) for p in exclude_patterns) for p in exclude_patterns))
        
        # Copy project files to temp directory
        shutil.copytree(cls.original_cwd, cls.temp_dir.name, dirs_exist_ok=True, ignore=ignore_patterns)
        
        # Copy .git directory if it exists
        git_dir = Path(cls.original_cwd) / '.git'
        if git_dir.exists():
            shutil.copytree(git_dir, Path(cls.temp_dir.name) / '.git', symlinks=True)    
            
        # Switch to temporary directory
        os.chdir(cls.temp_dir.name)
        cls.logger.info(f"Changed working directory to: {cls.temp_dir.name}")
        
        # Setup environment
        cls._setup_environment()
        
        # Start the service
        cls.start_service()
        time.sleep(STARTUP_WAIT)
        
        cls._setup_complete = True

    @classmethod
    def _setup_environment(cls):
        """Setup environment for tests"""
        cls.logger.info("Setting up test environment...")
        
        venv_path = os.environ.get('VIRTUAL_ENV')
        
        cls.temp_env = os.environ.copy()
        cls.temp_env.pop('VIRTUAL_ENV', None)
        cls.temp_env.pop('POETRY_ACTIVE', None)
        
        if venv_path:
            if os.name == 'nt':  # Windows
                site_packages = Path(venv_path) / 'Lib' / 'site-packages'
            else:  # Unix-like
                site_packages = list(Path(venv_path).glob('lib/python*/site-packages'))[0]
                
            pythonpath = cls.temp_env.get('PYTHONPATH', '')
            cls.temp_env['PYTHONPATH'] = f"{site_packages}:{pythonpath}" if pythonpath else str(site_packages)
            
            paths = cls.temp_env['PATH'].split(os.pathsep)
            paths = [p for p in paths if not p.startswith(str(venv_path))]
            cls.temp_env['PATH'] = os.pathsep.join(paths)
        else:
            cls.logger.warning("No virtualenv detected")
            
        cls.logger.info("Environment setup completed")

    @classmethod
    def teardown_class(cls):
        """Cleanup after all tests"""
        try:
            cls.logger.info("Starting test cleanup...")
            
            # Always try to stop the service first
            try:
                cls.stop_service()
                time.sleep(CONTAINER_STOP_WAIT)
                
                # Verify all containers are stopped
                client = docker.from_env()
                service_config = get_service_config(cls.config_path)
                container_name = service_config["container_name"]
                containers = client.containers.list(filters={"name": container_name})
                
                if containers:
                    cls.logger.warning("Found running containers after stop_service, forcing removal...")
                    for container in containers:
                        container.stop(timeout=30)
                        container.remove()
            except Exception as e:
                cls.logger.error(f"Error stopping service: {str(e)}")
            
            # Clean up resources
            os.chdir(cls.original_cwd)
            if cls.temp_dir:
                temp_dir_path = cls.temp_dir.name
                cleanup_directory(temp_dir_path, cls.logger)
            cls.logger.info("Cleanup completed")
            cls._setup_complete = False
            
        except Exception as e:
            cls.logger.error(f"Error during cleanup: {str(e)}")

    @classmethod
    def start_service(cls):
        """Start the service and handle initial setup."""
        try:
            cls.logger.info(f"Starting run_service.py test with config: {cls.config_path}")
            
            # Basic spawn with consistent environment
            cls.child = pexpect.spawn(
                f'bash ./run_service.sh {cls.config_path}',
                encoding='utf-8',
                timeout=600,
                env=cls.temp_env,
                cwd="."
            )
            
            # Redirect pexpect logging to debug level only
            cls.child.logfile = sys.stdout  # Disable direct stdout logging
            try:
                while True:
                    patterns = list(cls.config_settings["prompts"].keys())
                    index = cls.child.expect(patterns, timeout=600)
                    pattern = patterns[index]
                    response = cls.config_settings["prompts"][pattern]
                
                    cls.logger.info(f"Matched prompt: {pattern}", extra={'is_expect': True})

                    if callable(response):
                        output = cls.child.before + cls.child.after
                        response = response(output, cls.logger)
                    
                    # Ensure consistent line endings
                    if not response.endswith('\n'):
                        response += '\n' 


                    # Special handling for backup owner
                    if "backup owner" in pattern.lower():
                        time.sleep(1)  # Small delay before
                        cls.child.sendline(response)
                        time.sleep(1)  # Small delay after
                    else:
                        if "password" in pattern.lower():
                            cls.logger.info("Sending: [HIDDEN]", extra={'is_input': True})
                        elif "eth_newfilter" in pattern.lower():
                            cls.logger.info("Sending: [HIDDEN RPC URL]", extra={'is_input': True})
                        else:
                            cls.logger.info(f"Sending: {response}", extra={'is_input': True})
                        cls.child.sendline(response)
                    
                    # Small delay between inputs
                    time.sleep(0.5)
                    
            except pexpect.EOF:
                cls.logger.info("Initial setup completed")
                time.sleep(SERVICE_INIT_WAIT)


                retries = 5
                while retries > 0:
                    if check_docker_status(cls.logger, cls.config_path):
                        break
                    time.sleep(CONTAINER_STOP_WAIT)
                    retries -= 1

                if retries == 0:
                    service_config = get_service_config(cls.config_path)
                    container_name = service_config["container_name"]
                    raise Exception(f"{container_name} containers failed to start")
                    
            except Exception as e:
                cls.logger.error(f"Error in setup: {str(e)}")
                raise
                
        except Exception as e:
            cls.logger.error(f"Service start failed: {str(e)}")
            raise

    @classmethod
    def stop_service(cls):
        """Stop the service ensuring we're in temp directory"""
        cls.logger.info("Stopping service...")
        if hasattr(cls, 'temp_dir') and cls.temp_dir:
            stop_dir = cls.temp_dir.name
        else:
            stop_dir = os.getcwd()
            
        process = pexpect.spawn(
            f'bash ./stop_service.sh {cls.config_path}', 
            encoding='utf-8', 
            timeout=30,
            cwd=stop_dir  # Explicitly set working directory for stop_service
        )
        process.expect(pexpect.EOF)
        time.sleep(0)

    def test_health_check(self):
        """Test service health endpoint"""
        self.logger.info("Testing service health...")
        status, metrics = check_service_health(self.logger, self.config_path)
        self.logger.info(f"Health check metrics: {metrics}")
        assert status == True, f"Health check failed with metrics: {metrics}"
            
    def test_shutdown_logs(self):
        """Test service shutdown logs"""
        try:
            self.logger.info("Testing shutdown logs...")
            self.stop_service()
            time.sleep(CONTAINER_STOP_WAIT)
            
            client = docker.from_env()
            service_config = get_service_config(self.config_path)
            container_name = service_config["container_name"]
            
            containers = client.containers.list(filters={"name": container_name})
            assert len(containers) == 0, f"Containers with name {container_name} are still running"
            assert check_shutdown_logs(self.logger, self.config_path) == True, "Shutdown logs check failed"
        finally:
            if self._setup_complete:
                self.teardown_class()

class TestAgentService:
    """Test class that runs tests for all configs."""
    
    logger = setup_logging(Path(f'test_run_service_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'))

    @pytest.fixture(autouse=True)
    def setup(self, request):
        """Setup for each test case."""
        config_path = request.param
        temp_dir = None

        try:
            # Create a temporary directory for stop_service
            temp_dir = tempfile.TemporaryDirectory(prefix='operate_test_')
            
            # Copy necessary files to temp directory
            shutil.copytree('.', temp_dir.name, dirs_exist_ok=True, 
                            ignore=shutil.ignore_patterns('.git', '.pytest_cache', '__pycache__', 
                                                    '*.pyc', 'logs', '*.log', '.env'))
            
            # First ensure any existing service is stopped
            if not ensure_service_stopped(config_path, temp_dir.name, self.logger):
                raise RuntimeError("Failed to stop existing service")
            
            self.test_class = type(
                f'TestService_{Path(config_path).stem}',
                (BaseTestService,),
                {'config_path': config_path}
            )
            self.test_class.setup_class()
            yield
            if self.test_class._setup_complete:
                self.test_class.teardown_class()
                
        finally:
            # Clean up the temporary directory
            if temp_dir:
                temp_dir_path = temp_dir.name
                try:
                    temp_dir.cleanup()
                except Exception:
                    self.logger.warning("Built-in cleanup failed, trying custom cleanup...")
                    cleanup_directory(temp_dir_path, self.logger)

    @pytest.mark.parametrize('setup', get_config_files(), indirect=True, ids=lambda x: Path(x).stem)
    def test_agent_full_suite(self, setup):
        """Run all tests for each config."""
        test_instance = self.test_class()
        
        # Run health check
        test_instance.test_health_check()
        
        # Run shutdown logs test
        test_instance.test_shutdown_logs()

if __name__ == "__main__":
    pytest.main(["-v", __file__, "-s", "--log-cli-level=INFO"])