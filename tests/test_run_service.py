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


# Initialize colorama and load environment
init()
load_dotenv()

STARTUP_WAIT = 10
SERVICE_INIT_WAIT = 60
CONTAINER_STOP_WAIT = 20

# Handle the distutils warning
os.environ['SETUPTOOLS_USE_DISTUTILS'] = 'stdlib'

def check_docker_status(logger: logging.Logger) -> bool:
    """Check if Docker containers are running properly."""
    max_retries = 3
    retry_delay = 20
    
    for attempt in range(max_retries):
        logger.info(f"Checking Docker status (attempt {attempt + 1}/{max_retries})")
        try:
            client = docker.from_env()
            
            # Check all containers, including stopped ones
            all_containers = client.containers.list(all=True, filters={"name": "traderpearl"})
            running_containers = client.containers.list(filters={"name": "traderpearl"})
            
            if not all_containers:
                logger.error(f"No trader containers found (attempt {attempt + 1}/{max_retries})")
                if attempt == max_retries - 1:
                    return False
                logger.info(f"Waiting {retry_delay} seconds before retry...")
                time.sleep(retry_delay)
                continue
            
            # Log status of all containers
            for container in all_containers:
                logger.info(f"Container {container.name} status: {container.status}")
                
                if container.status == "exited":
                    # Get exit code
                    inspect = client.api.inspect_container(container.id)
                    exit_code = inspect['State']['ExitCode']
                    logger.error(f"Container {container.name} exited with code {exit_code}")
                    
                    # Get last logs
                    logs = container.logs(tail=50).decode('utf-8')
                    logger.error(f"Container logs:\n{logs}")
                
                elif container.status == "restarting":
                    logger.error(f"Container {container.name} is restarting. Last logs:")
                    logs = container.logs(tail=50).decode('utf-8')
                    logger.error(f"Container logs:\n{logs}")
            
            # Check if all required containers are running
            if not running_containers:
                if attempt == max_retries - 1:
                    return False
                logger.info(f"Waiting {retry_delay} seconds for containers to start...")
                time.sleep(retry_delay)
                continue
            
            # Verify all running containers are actually running
            all_running = all(c.status == "running" for c in running_containers)
            if all_running:
                logger.info("All trader containers are running")
                return True
            
            if attempt == max_retries - 1:
                return False
                
            logger.info(f"Some containers not running, waiting {retry_delay} seconds...")
            time.sleep(retry_delay)
            
        except Exception as e:
            logger.error(f"Error checking Docker status: {str(e)}")
            if attempt == max_retries - 1:
                return False
            logger.info(f"Waiting {retry_delay} seconds before retry...")
            time.sleep(retry_delay)
    
    return False

def check_service_health(logger: logging.Logger) -> tuple[bool, dict]:
    """Enhanced service health check with metrics. Any failure results in overall failure."""
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
            response = requests.get(HEALTH_CHECK_URL, timeout=10)
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
            
        # Wait for remaining time in 5-second interval
        elapsed = time.time() - start_time
        if elapsed < 5:
            time.sleep(5 - elapsed)
    
    # If we got here, all checks passed
    logger.info(f"Health check completed successfully - {metrics['successful_checks']} checks passed")
    return True, metrics

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
    """Handle funding requirement using Tenderly API."""
    pattern = r"Please make sure master EOA (0x[a-fA-F0-9]{40}) has at least (\d+\.\d+) xDAI"
    match = re.search(pattern, output)
    
    if match:
        wallet_address = match.group(1)
        required_amount = float(match.group(2))
        logger.info(f"Funding requirement detected - Address: {wallet_address}, Amount: {required_amount} xDAI")
        
        try:
            # Convert amount to Wei (hex)
            w3 = Web3(Web3.HTTPProvider(TEST_CONFIG["RPC_URL"]))
            amount_wei = w3.to_wei(required_amount, 'ether')
            amount_hex = hex(amount_wei)
            
            # Prepare Tenderly API request
            headers = {
                "Content-Type": "application/json"
            }
            
            payload = {
                "jsonrpc": "2.0",
                "method": "tenderly_addBalance",
                "params": [
                    wallet_address,
                    amount_hex
                ],
                "id": "1"
            }
            
            # Make request to Tenderly RPC
            response = requests.post(TEST_CONFIG["RPC_URL"], headers=headers, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                if 'error' in result:
                    raise Exception(f"Tenderly API error: {result['error']}")
                    
                logger.info(f"Successfully funded {required_amount} xDAI to {wallet_address} using Tenderly API")
                # Verify balance
                new_balance = w3.eth.get_balance(wallet_address)
                logger.info(f"New balance: {w3.from_wei(new_balance, 'ether')} xDAI")
                return ""
            else:
                raise Exception(f"Tenderly API request failed with status {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to fund wallet using Tenderly API: {str(e)}")
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
    "RPC_URL": os.getenv('RPC_URL', ''),
    "BACKUP_WALLET": os.getenv('BACKUP_WALLET', '0x4e9a8fE0e0499c58a53d3C2A2dE25aaCF9b925A8'),
    "TEST_PASSWORD": os.getenv('TEST_PASSWORD', ''),
    "STAKING_CHOICE": os.getenv('STAKING_CHOICE', '1')
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
        # Wait for service to fully start
        time.sleep(STARTUP_WAIT)

    @classmethod
    def _setup_environment(cls):
        """Setup environment for tests"""
        cls.logger.info("Setting up test environment...")

        venv_path = os.environ.get('VIRTUAL_ENV')
        
        # Create a clean environment without virtualenv variables
        cls.temp_env = os.environ.copy()
        cls.temp_env.pop('VIRTUAL_ENV', None)
        cls.temp_env.pop('POETRY_ACTIVE', None)
        
        if venv_path:
            # Get site-packages path
            if os.name == 'nt':  # Windows
                site_packages = Path(venv_path) / 'Lib' / 'site-packages'
            else:  # Unix-like
                site_packages = list(Path(venv_path).glob('lib/python*/site-packages'))[0]
                
            # Add site-packages to PYTHONPATH
            pythonpath = cls.temp_env.get('PYTHONPATH', '')
            cls.temp_env['PYTHONPATH'] = f"{site_packages}:{pythonpath}" if pythonpath else str(site_packages)
            
            # Remove virtualenv path from PATH
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
                'bash ./run_service.sh configs/config_predict_trader.json',
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
                
                # Add delay to ensure services are up
                time.sleep(SERVICE_INIT_WAIT)
                
                # Verify Docker containers are running
                retries = 5
                while retries > 0:
                    if check_docker_status(cls.logger):
                        break
                    time.sleep(CONTAINER_STOP_WAIT)
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
        process = pexpect.spawn('bash ./stop_service.sh configs/config_predict_trader.json', encoding='utf-8', timeout=30)
        process.expect(pexpect.EOF)
        time.sleep(30)      
        
    def test_01_health_check(self):
        """Test service health endpoint"""
        self.logger.info("Testing service health...")
        status, metrics = check_service_health(self.logger)
        
        # Log the metrics for debugging/monitoring
        self.logger.info(f"Health check metrics: {metrics}")
        
        assert status == True, f"Health check failed with metrics: {metrics}"
            
    def test_02_shutdown_logs(self):
        """Test service shutdown logs"""
        self.logger.info("Testing shutdown logs...")
        # First stop the service
        self.stop_service()
        # Wait for containers to stop
        time.sleep(30)
        # Verify containers are stopped
        client = docker.from_env()
        containers = client.containers.list(filters={"name": "traderpearl"})
        assert len(containers) == 0, "Containers are still running"
        # Now check the logs
        assert check_shutdown_logs(self.logger) == True, "Shutdown logs check failed"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])