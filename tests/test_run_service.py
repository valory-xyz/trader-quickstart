# -*- coding: utf-8 -*-
"""Test run_service.py script using pytest for reliable automation."""

import re
import shutil
import sys
import logging
import pexpect
import os
import time
import pytest
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

# Initialize colorama and load environment
init()
load_dotenv()

# Handle the distutils warning
os.environ['SETUPTOOLS_USE_DISTUTILS'] = 'stdlib'

HEALTH_CHECK_URL = "http://127.0.0.1:8716/healthcheck"

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

def check_service_health(logger: logging.Logger) -> bool:
    """Check if the service is healthy."""
    try:
        response = requests.get(HEALTH_CHECK_URL)
        if response.status_code == 200:
            logger.info("Service health check passed")
            return True
        else:
            logger.error(f"Service health check failed with status code: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return False

def check_service_logs(logger: logging.Logger) -> bool:
    """Check service logs for critical errors."""
    try:
        client = docker.from_env()
        containers = client.containers.list(filters={"name": "traderpearl"})
        
        # Define patterns to ignore
        ignore_patterns = [
            "The same event 'Event.FETCH_ERROR'",
            "The kwargs={'mech_request_price'",
            "Slashing has not been enabled",
            "No stored bets file was detected",
            "WARNING"  # Ignore general warnings
        ]
        
        for container in containers:
            logs = container.logs().decode('utf-8')
            
            # Split logs into lines for better analysis
            log_lines = logs.split('\n')
            
            for line in log_lines:
                # Skip empty lines
                if not line.strip():
                    continue
                    
                # Check if line contains ERROR but isn't in ignore patterns
                if "ERROR" in line and not any(pattern in line for pattern in ignore_patterns):
                    logger.error(f"Found critical error in container {container.name}: {line}")
                    return False
                    
        logger.info("Service logs check passed")
        return True
        
    except Exception as e:
        logger.error(f"Error checking service logs: {str(e)}")
        return False

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

def cleanup_previous_run(logger: logging.Logger):
    """Clean up previous run artifacts."""
    operate_folder = Path("./.operate")  # Using relative path
    if operate_folder.exists():
        try:
            logger.info(f"Removing .operate folder")
            shutil.rmtree(operate_folder, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error while cleaning up .operate folder: {str(e)}")
            
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
    "PRIVATE_KEY": os.getenv('PRIVATE_KEY', ''),
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
        
        # Start the service
        cls.start_service()
        # Wait for service to fully start
        time.sleep(5)
        
    @classmethod
    def teardown_class(cls):
        """Cleanup after all tests"""
        try:
                # First stop the service
            cls.stop_service()
            
            # Wait for service to fully stop
            time.sleep(10)
            
            # Then clean up the folder
            cleanup_previous_run(cls.logger)
        except Exception as e:
            cls.logger.error(f"Error during cleanup: {str(e)}")
        
    @classmethod
    def start_service(cls):
        """Start the service and handle initial setup."""
        try:
            cls.logger.info("Starting run_service.py test")
            
            # Get current virtual environment path
            venv_path = os.environ.get('VIRTUAL_ENV')
            
            # Temporarily deactivate virtual environment
            if venv_path:
                temp_env = os.environ.copy()
                temp_env.pop('VIRTUAL_ENV', None)
                temp_env.pop('POETRY_ACTIVE', None)
                
                # Update PATH to remove the virtual environment
                paths = temp_env['PATH'].split(os.pathsep)
                paths = [p for p in paths if not p.startswith(venv_path)]
                temp_env['PATH'] = os.pathsep.join(paths)
            else:
                temp_env = os.environ
            
            # Start the process with pexpect
            cls.child = pexpect.spawn(
                'bash ./run_service.sh',
                encoding='utf-8',
                timeout=600,
                env=temp_env,
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
                time.sleep(30)
                
                # Verify Docker containers are running
                retries = 5
                while retries > 0:
                    if check_docker_status(cls.logger):
                        break
                    time.sleep(10)
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
        time.sleep(10)
        
    def test_01_service_logs(self):
        """Test service logs for errors"""
        self.logger.info("Testing service logs...")
        assert check_service_logs(self.logger) == True, "Service logs check failed"
        
    def test_02_docker_status(self):
        """Test Docker container status"""
        self.logger.info("Testing Docker container status...")
        assert check_docker_status(self.logger) == True, "Docker status check failed"
        
    def test_03_health_check(self):
        """Test service health endpoint"""
        self.logger.info("Testing service health...")
        assert check_service_health(self.logger) == True, "Health check failed"
        
    def test_04_shutdown_logs(self):
        """Test service shutdown logs"""
        self.logger.info("Testing shutdown logs...")
        assert check_shutdown_logs(self.logger) == True, "Shutdown logs check failed"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])