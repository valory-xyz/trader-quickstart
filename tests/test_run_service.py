# -*- coding: utf-8 -*-
"""Test run_service.py script using pexpect for reliable automation."""

import re
import sys
import logging
import pexpect
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from termcolor import colored
from colorama import init
from web3 import Web3
from eth_account import Account
import requests
import docker
# Initialize colorama
HEALTH_CHECK_URL = "http://127.0.0.1:8716/healthcheck"
init()


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


# Test Configuration
TEST_CONFIG = {
    "RPC_URL": "https://virtual.gnosis.rpc.tenderly.co/d33f24ed-3a9e-4df1-91c5-0a7786f335ad",
    "BACKUP_WALLET": "0x4e9a8fE0e0499c58a53d3C2A2dE25aaCF9b925A8",
    "TEST_PASSWORD": "secret",
    "PRIVATE_KEY": "4a3f2ffe454858623239c7030ae9c7066efe993b212ffab992db84b07f2177e9",
    "STAKING_CHOICE": "1"  # 1 for No Staking, 2 for Quickstart Beta - Hobbyist
}

# Expected prompts and their responses
PROMPTS = {
    "eth_newFilter \[hidden input\]": TEST_CONFIG["RPC_URL"],
    "input your password": TEST_CONFIG["TEST_PASSWORD"],
    "confirm your password": TEST_CONFIG["TEST_PASSWORD"],
    "Enter your choice": TEST_CONFIG["STAKING_CHOICE"],
    "backup owner": TEST_CONFIG["BACKUP_WALLET"],
    "Press enter to continue": "\n",
    "press enter": "\n",
    "Please make sure master EOA.*has at least.*xDAI": handle_xDAIfunding,  # Updated pattern
    "Enter local user account password \[hidden input\]": TEST_CONFIG["TEST_PASSWORD"]  # Added new password prompt

}

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

def cleanup_previous_run():
    """Clean up previous run artifacts."""
    operate_folder = Path("../.operate")
    if operate_folder.exists():
        print(f"Removing existing .operate folder: {operate_folder}")
        shutil.rmtree(operate_folder)

def setup_logging(log_file: Optional[Path] = None) -> logging.Logger:
    """Set up logging configuration."""
    # Create logs directory if it doesn't exist
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
        # Put the log file in the logs directory
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

def test_run_service():
    """Test running the run_service.py script using pexpect."""
    
    # Cleanup previous run artifacts
    cleanup_previous_run()
    
    # Setup logging
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = Path(f'test_run_service_{timestamp}.log')
    logger = setup_logging(log_file)
    
    logger.info("Starting run_service.py test")
    logger.info(f"Log file: logs/{log_file}")

    
    try:
        script_path = Path("./run_service.sh")
        os.chmod(script_path, 0o755)

        # Start the process with pexpect
        child = pexpect.spawn(
            'bash ./run_service.sh',  # Use bash explicitly
            encoding='utf-8',
            timeout=600,
            cwd="."
        )
        
        # Enable logging of the interaction
        child.logfile = sys.stdout
        
        # Handle the interaction
        while True:
            try:
                patterns = list(PROMPTS.keys())
                index = child.expect(patterns, timeout=600)
                pattern = patterns[index]
                response = PROMPTS[pattern]
                
                # Log the interaction
                logger.info(f"Matched prompt: {pattern}", extra={'is_expect': True})
                
                # Handle response based on type
                if callable(response):
                    output = child.before + child.after
                    response = response(output, logger)
                
                if "password" in pattern.lower():
                    logger.info("Sending: [HIDDEN]", extra={'is_input': True})
                else:
                    logger.info(f"Sending: {response}", extra={'is_input': True})
                
                # Send the response
                child.sendline(response)
                
            except pexpect.EOF:
                logger.info("Process completed")
                break
            except pexpect.TIMEOUT:
                logger.error("Timeout waiting for prompt")
                break
            except Exception as e:
                logger.error(f"Error handling prompt: {str(e)}")
                break
        
        # Get the exit status
        child.close()
        if child.exitstatus == 0:
            logger.info("Test completed successfully")
            # Check Docker status
            if not check_docker_status(logger):
                raise Exception("Docker container check failed")
                
            # Check service health
            if not check_service_health(logger):
                raise Exception("Service health check failed")
                
            logger.info("All checks passed successfully")
        else:
            logger.error(f"Test failed with exit status {child.exitstatus}")
            
    except Exception as e:
        logger.error(f"Test failed with error: {str(e)}")
    finally:
        logger.info(f"Test logs saved to: {log_file}")

if __name__ == "__main__":
    test_run_service()