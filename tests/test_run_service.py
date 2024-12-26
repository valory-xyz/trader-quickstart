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
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from termcolor import colored
from colorama import init
from web3 import Web3
from eth_account import Account
import requests
import docker
from dotenv import load_dotenv
from operate.constants import HEALTH_CHECK_URL

# Initialize colorama and load environment
init()
load_dotenv()

STARTUP_WAIT = 10
SERVICE_INIT_WAIT = 60
CONTAINER_STOP_WAIT = 20

# Handle the distutils warning
os.environ['SETUPTOOLS_USE_DISTUTILS'] = 'stdlib'

# Required environment variables
REQUIRED_ENV_VARS = {
    "RPC_URL": "Ethereum RPC endpoint URL",
    "BACKUP_WALLET": "Backup wallet address",
    "TEST_PASSWORD": "Test password for authentication",
    "PRIVATE_KEY": "Private key for transactions",
    "STAKING_CHOICE": "Staking choice selection"
}

class PrerequisiteError(Exception):
    """Custom exception for prerequisite check failures."""
    pass

def check_prerequisites(logger: logging.Logger) -> None:
    """
    Check all prerequisites before running tests.
    Raises PrerequisiteError if any check fails.
    """
    logger.info(colored("Checking prerequisites...", "cyan"))
    
    # Check environment variables
    missing_vars = check_environment_variables(logger)
    if missing_vars:
        error_msg = "\nMissing required environment variables:\n"
        for var, description in missing_vars.items():
            error_msg += f"- {var}: {description}\n"
        error_msg += "\nPlease set these variables in your .env file before running tests."
        raise PrerequisiteError(error_msg)

    # Check Docker installation and service
    if not check_docker_running_status(logger):
        raise PrerequisiteError(
            "\nDocker is not properly installed or running.\n"
            "Please ensure that:\n"
            "1. Docker is installed (run 'docker --version')\n"
            "2. Docker daemon is running (run 'docker ps')\n"
            "3. Current user has permissions to run Docker commands"
        )

    logger.info(colored("✓ All prerequisites met", "green"))

def check_environment_variables(logger: logging.Logger) -> Dict[str, str]:
    """
    Enhanced check for environment variables:
    - Verifies .env file exists
    - Validates file is not empty
    - Checks all required variables are set
    - Validates URL format for RPC_URL
    - Validates address format for BACKUP_WALLET
    - Ensures values are not empty strings
    
    Returns a dictionary of missing/invalid variables and their descriptions.
    """
    missing_vars = {}
    env_file_path = Path('.env')

    # Check if .env file exists
    if not env_file_path.exists():
        logger.error(colored("✗ .env file not found", "red"))
        missing_vars['ENV_FILE'] = "Create a .env file in the project root directory"
        return missing_vars

    # Check if .env file is empty
    if env_file_path.stat().st_size == 0:
        logger.error(colored("✗ .env file is empty", "red"))
        missing_vars['ENV_FILE'] = "The .env file exists but is empty"
        return missing_vars

    # Read and parse .env file
    try:
        with open(env_file_path, 'r') as f:
            env_contents = f.read().strip()
        if not env_contents:
            logger.error(colored("✗ .env file contains no valid entries", "red"))
            missing_vars['ENV_FILE'] = "The .env file contains no valid entries"
            return missing_vars
    except Exception as e:
        logger.error(colored(f"✗ Error reading .env file: {str(e)}", "red"))
        missing_vars['ENV_FILE'] = f"Error reading .env file: {str(e)}"
        return missing_vars

    # Validate each required variable
    for var, description in REQUIRED_ENV_VARS.items():
        value = os.getenv(var)
        
        # Check if variable exists and is not empty
        if not value or value.strip() == '':
            logger.error(colored(f"✗ {var} is not set or is empty", "red"))
            missing_vars[var] = f"{description} (not set or empty)"
            continue

        # Specific validation for different variable types
        if var == 'RPC_URL':
            # Basic URL validation
            if not value.startswith(('http://', 'https://', 'ws://', 'wss://')):
                logger.error(colored(f"✗ {var} is not a valid URL format", "red"))
                missing_vars[var] = f"{description} (invalid URL format: {value})"
                continue
                
        elif var == 'BACKUP_WALLET':
            # Validate Ethereum address format
            if not re.match(r'^0x[a-fA-F0-9]{40}$', value):
                logger.error(colored(f"✗ {var} is not a valid Ethereum address", "red"))
                missing_vars[var] = f"{description} (invalid Ethereum address format: {value})"
                continue
                
        elif var == 'PRIVATE_KEY':
            # Validate private key format (hex string, usually 64 characters without 0x prefix)
            if not re.match(r'^[a-fA-F0-9]{64}$', value.strip('0x')):
                logger.error(colored(f"✗ {var} is not a valid private key format", "red"))
                missing_vars[var] = f"{description} (invalid private key format)"
                continue
                
        elif var == 'STAKING_CHOICE':
            # Validate staking choice is a number
            if not value.isdigit() or not (1 <= int(value) <= 3):
                logger.error(colored(f"✗ {var} must be a number between 1 and 3", "red"))
                missing_vars[var] = f"{description} (must be 1, 2, or 3)"
                continue
                
        elif var == 'TEST_PASSWORD':
            # Ensure password meets minimum requirements
            if len(value) < 6:
                logger.error(colored(f"✗ {var} is too short (minimum 8 characters)", "red"))
                missing_vars[var] = f"{description} (too short)"
                continue

        logger.info(colored(f"✓ {var} is properly set and validated", "green"))

    if not missing_vars:
        logger.info(colored("✓ All environment variables are properly set and validated", "green"))
    
    return missing_vars

def check_docker_running_status(logger: logging.Logger) -> bool:
    """
    Check if Docker is installed and running using pexpect.
    Returns True if Docker is operational, False otherwise.
    """
    logger.info("Checking Docker status...")
    try:
        # Check Docker version
        child = pexpect.spawn('docker --version', encoding='utf-8')
        index = child.expect(['Docker version', pexpect.EOF, pexpect.TIMEOUT], timeout=5)
        if index != 0:
            logger.error(colored("✗ Docker is not installed", "red"))
            return False
        logger.info(colored("✓ Docker is installed", "green"))
        
        # Check if Docker daemon is running by trying to list containers
        child = pexpect.spawn('docker ps', encoding='utf-8')
        index = child.expect(['CONTAINER ID', pexpect.EOF, pexpect.TIMEOUT], timeout=5)
        if index != 0:
            logger.error(colored("✗ Docker daemon is not running", "red"))
            return False
            
        logger.info(colored("✓ Docker daemon is running", "green"))
        return True
        
    except Exception as e:
        logger.error(colored(f"✗ Docker check failed: {str(e)}", "red"))
        return False

def countdown_spinner(seconds: int, message: str, logger: logging.Logger):
    """Display a spinner with countdown."""
    spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    end_time = time.time() + seconds
    
    def spin():
        i = 0
        while time.time() < end_time:
            remaining = int(end_time - time.time())
            sys.stdout.write(f'\r{spinner[i]} {message} ({remaining}s remaining)')
            sys.stdout.flush()
            time.sleep(0.1)
            i = (i + 1) % len(spinner)
        sys.stdout.write('\r' + ' ' * (len(message) + 25) + '\r')
        sys.stdout.flush()
    
    spinner_thread = threading.Thread(target=spin)
    spinner_thread.start()
    time.sleep(seconds)
    spinner_thread.join()
    logger.info(f"Completed: {message}")

def check_docker_status(logger: logging.Logger) -> bool:
    """Check if Docker containers are running properly."""
    try:
        client = docker.from_env()
        containers = client.containers.list(filters={"name": "traderpearl"})
        
        if not containers:
            logger.error("No trader containers found")
            return False
            
        for container in containers:
            logger.info(f"Container {container.name} status: {container.status}")
            if container.status != 'running':
                logger.error(f"Container {container.name} is not running")
                return False
                
        logger.info("All trader containers are running")
        return True
        
    except Exception as e:
        logger.error(f"Error checking Docker status: {str(e)}")
        return False

def check_service_health(logger: logging.Logger) -> tuple[bool, dict]:
    """Enhanced service health check with metrics."""
    metrics = {
        'response_time': None,
        'status_code': None,
        'error': None
    }
    
    try:
        start_time = time.time()
        response = requests.get(HEALTH_CHECK_URL, timeout=10)
        metrics['response_time'] = time.time() - start_time
        metrics['status_code'] = response.status_code
        
        if response.status_code == 200:
            logger.info(f"Health check passed (response time: {metrics['response_time']:.2f}s)")
            return True, metrics
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

def check_shutdown_logs(logger: logging.Logger) -> bool:
    """Check shutdown logs for errors."""
    try:
        client = docker.from_env()
        containers = client.containers.list(filters={"name": "traderpearl"})
        
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

def handle_xDAIfunding(output: str, logger: logging.Logger) -> str:
    """Handle funding requirement."""
    pattern = r"Please make sure master EOA (0x[a-fA-F0-9]{40}) has at least (\d+\.\d+) xDAI"
    match = re.search(pattern, output)
    
    if match:
        wallet_address = match.group(1)
        required_amount = float(match.group(2))
        logger.info(f"Funding requirement detected - Address: {wallet_address}, Amount: {required_amount} xDAI")
        
        try:
            w3 = Web3(Web3.HTTPProvider(TEST_CONFIG["RPC_URL"]))
            account = Account.from_key(TEST_CONFIG["PRIVATE_KEY"])
            amount_wei = w3.to_wei(required_amount, 'ether')
            
            tx = {
                'from': account.address,
                'to': wallet_address,
                'value': amount_wei,
                'gas': 21000,
                'gasPrice': w3.eth.gas_price,
                'nonce': w3.eth.get_transaction_count(account.address),
            }
            
            signed_tx = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt['status'] == 1:
                logger.info(f"Successfully funded {required_amount} xDAI to {wallet_address}")
                return ""
                
        except Exception as e:
            logger.error(f"Failed to fund wallet: {str(e)}")
            raise
    
    return ""

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
    
    logger = logging.getLogger('test_runner')
    logger.setLevel(logging.DEBUG)
    
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

# Test Configuration
TEST_CONFIG = {
    "RPC_URL": os.getenv('RPC_URL'),
    "BACKUP_WALLET": os.getenv('BACKUP_WALLET', '0x4e9a8fE0e0499c58a53d3C2A2dE25aaCF9b925A8'),
    "TEST_PASSWORD": os.getenv('TEST_PASSWORD'),
    "PRIVATE_KEY": os.getenv('PRIVATE_KEY'),
    "STAKING_CHOICE": os.getenv('STAKING_CHOICE')
}

# Expected prompts and their responses
PROMPTS = {
    r"eth_newFilter \[hidden input\]": TEST_CONFIG["RPC_URL"],
    "input your password": TEST_CONFIG["TEST_PASSWORD"],
    "confirm your password": TEST_CONFIG["TEST_PASSWORD"],
    "Enter your choice": TEST_CONFIG["STAKING_CHOICE"],
    "backup owner": TEST_CONFIG["BACKUP_WALLET"],
    "Press enter to continue": "\n",
    "press enter": "\n",
    "Please make sure master EOA.*has at least.*xDAI": handle_xDAIfunding,
    r"Enter local user account password \[hidden input\]": TEST_CONFIG["TEST_PASSWORD"]
}

class TestService:
    @classmethod
    def setup_class(cls):
        """Setup for all tests"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        cls.log_file = Path(f'test_run_service_{timestamp}.log')
        cls.logger = setup_logging(cls.log_file)

        # Check prerequisites before proceeding
        try:
            check_prerequisites(cls.logger)
        except PrerequisiteError as e:
            cls.logger.error(str(e))
            sys.exit(1)
        
        # Create temporary directory and store original path
        cls.original_cwd = os.getcwd()
        cls.temp_dir = tempfile.TemporaryDirectory(prefix='operate_test_')
        
        # Copy the entire project directory structure to temp directory
        cls.logger.info(f"Copying project files to temporary directory: {cls.temp_dir.name}")
        
        # Exclude patterns for files/directories we don't want to copy
        exclude_patterns = [
            '.git',              # Git directory - we'll copy this separately
            '.pytest_cache',     # Pytest cache
            '__pycache__',       # Python cache
            '*.pyc',            # Python compiled files
            '.operate',          # Operate directory
            'logs',             # Log files
            '*.log',            # Log files
            '.env'              # Environment files
        ]
        
        def ignore_patterns(path, names):
            return set(n for n in names if any(p in n or any(p.endswith(n) for p in exclude_patterns) for p in exclude_patterns))
        
        # First copy everything except excluded patterns
        shutil.copytree(cls.original_cwd, cls.temp_dir.name, dirs_exist_ok=True, ignore=ignore_patterns)
        
        # Then copy .git directory
        git_dir = Path(cls.original_cwd) / '.git'
        if git_dir.exists():
            shutil.copytree(git_dir, Path(cls.temp_dir.name) / '.git', symlinks=True)    
            
        # Switch to temporary directory
        os.chdir(cls.temp_dir.name)
        
        # Setup environment
        cls._setup_environment()
        
        # Start the service
        cls.start_service()
        # Wait for service to fully start with spinner
        cls.logger.info("Waiting for initial startup...")
        countdown_spinner(STARTUP_WAIT, "Waiting for initial startup", cls.logger)

    @classmethod
    def _setup_environment(cls):
        """Setup environment for tests"""
        cls.logger.info("Setting up test environment...")

        venv_path = os.environ.get('VIRTUAL_ENV')
        
        # Temporarily deactivate virtual environment
        if venv_path:
            cls.temp_env = os.environ.copy()
            cls.temp_env.pop('VIRTUAL_ENV', None)
            cls.temp_env.pop('POETRY_ACTIVE', None)
            
            # Update PATH to remove the virtual environment
            paths = cls.temp_env['PATH'].split(os.pathsep)
            paths = [p for p in paths if not p.startswith(venv_path)]
            cls.temp_env['PATH'] = os.pathsep.join(paths)
        else:
            cls.temp_env = os.environ

        cls.logger.info("Environment setup completed")

    @classmethod
    def teardown_class(cls):
        """Cleanup after all tests"""
        try:
            cls.logger.info("Starting test cleanup...")
            os.chdir(cls.original_cwd)
            cls.temp_dir.cleanup()
            cls.logger.info("Cleanup completed successfully")
        except Exception as e:
            cls.logger.error(f"Error during cleanup: {str(e)}")
            
    @classmethod
    def start_service(cls):
        """Start the service and handle initial setup."""
        try:
            cls.logger.info("Starting run_service.py test")
            
            # Start the process with pexpect
            cls.child = pexpect.spawn(
                'bash ./run_service.sh',
                encoding='utf-8',
                timeout=600,
                env=cls.temp_env,
                cwd="."
            )
            
            cls.child.logfile = sys.stdout
            
            # Handle the interaction
            try:
                while True:
                    patterns = list(PROMPTS.keys())
                    index = cls.child.expect(patterns, timeout=600)
                    pattern = patterns[index]
                    response = PROMPTS[pattern]
                
                    cls.logger.info(f"Matched prompt: {pattern}", extra={'is_expect': True})

                    if callable(response):
                        output = cls.child.before + cls.child.after
                        response = response(output, cls.logger)

                    if "password" in pattern.lower():
                        cls.logger.info("Sending: [HIDDEN]", extra={'is_input': True})
                    else:
                        cls.logger.info(f"Sending: {response}", extra={'is_input': True})
                    
                    cls.child.sendline(response)
                    
            except pexpect.EOF:
                cls.logger.info("Initial setup completed")
                
                # Add delay with spinner to ensure services are up
                countdown_spinner(SERVICE_INIT_WAIT, "Waiting for services to initialize", cls.logger)
                
                # Verify Docker containers are running
                retries = 5
                while retries > 0:
                    if check_docker_status(cls.logger):
                        break
                    countdown_spinner(CONTAINER_STOP_WAIT, f"Waiting for containers (attempt {6-retries}/5)", cls.logger)
                    retries -= 1
                
                if retries == 0:
                    raise Exception("Docker containers failed to start")
                    
            except Exception as e:
                cls.logger.error(f"Error in setup: {str(e)}")
                raise
                
        except Exception as e:
            cls.logger.error(f"Service start failed: {str(e)}")
            raise
            
    @classmethod
    def stop_service(cls):
        """Stop the service"""
        cls.logger.info("Stopping service...")
        process = pexpect.spawn('bash ./stop_service.sh', encoding='utf-8', timeout=30)
        process.expect(pexpect.EOF)
        countdown_spinner(CONTAINER_STOP_WAIT, "Waiting for service to stop", cls.logger)
        
    def test_01_docker_status(self):
        """Test Docker container status"""
        self.logger.info("Testing Docker container status...")
        assert check_docker_status(self.logger), (
            "Docker containers are not running correctly. "
            "Check docker ps output for more details."
        )
        
    def test_02_health_check(self):
        """Test service health endpoint"""
        self.logger.info("Testing service health...")
        status, metrics = check_service_health(self.logger)
        
        # Log the metrics for debugging/monitoring
        self.logger.info(f"Health check metrics: {metrics}")
        
        assert status == True, f"Health check failed with metrics: {metrics}"
            
    def test_03_shutdown_logs(self):
        """Test service shutdown logs"""
        self.logger.info("Testing shutdown logs...")
        # First stop the service
        self.stop_service()
        # Wait for containers to stop with spinner
        countdown_spinner(CONTAINER_STOP_WAIT, "Waiting for containers to stop", self.logger)
        # Verify containers are stopped
        client = docker.from_env()
        containers = client.containers.list(filters={"name": "traderpearl"})
        assert len(containers) == 0, "Containers are still running"
        # Now check the logs
        assert check_shutdown_logs(self.logger) == True, "Shutdown logs check failed"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
    