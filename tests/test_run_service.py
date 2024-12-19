# -*- coding: utf-8 -*-
"""Test run_service.py script using pexpect for reliable automation."""

import re
import sys
import logging
import pexpect
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from termcolor import colored
from colorama import init
from web3 import Web3
from eth_account import Account
import requests
import docker
from dotenv import load_dotenv

# Handle the distutils warning
os.environ['SETUPTOOLS_USE_DISTUTILS'] = 'stdlib'

# Initialize colorama
HEALTH_CHECK_URL = "http://127.0.0.1:8716/healthcheck"
init()
load_dotenv()

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


# Test Configuration
TEST_CONFIG = {
    "RPC_URL": os.getenv('RPC_URL', ''),
    "BACKUP_WALLET": os.getenv('BACKUP_WALLET', '0x4e9a8fE0e0499c58a53d3C2A2dE25aaCF9b925A8'),
    "TEST_PASSWORD": os.getenv('TEST_PASSWORD', ''),
    "PRIVATE_KEY": os.getenv('PRIVATE_KEY', ''),
    "STAKING_CHOICE": os.getenv('STAKING_CHOICE', '1')  # 1 for No Staking, 2 for Quickstart Beta - Hobbyist
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
    operate_folder = Path("/Users/siddi_404/Solulab/OLAS/middleware/quickstart/.operate")
    if operate_folder.exists():
        print(f"Removing existing .operate folder: {operate_folder}")
        try:
            # Kill any processes that might be using the directory
            os.system("pkill -f trader")
            os.system("pkill -f quickstart")
            time.sleep(2)  # Give processes time to terminate
            
            # Force close any file handles
            os.system(f"lsof +D {operate_folder} | awk '{{print $2}}' | tail -n +2 | xargs -r kill -9")
            time.sleep(1)
            
            # Remove read-only attributes and set full permissions recursively
            os.system(f"chmod -R 777 {operate_folder}")
            time.sleep(1)
            
            # Remove directory using multiple methods
            commands = [
                f"rm -rf {operate_folder}",
                f"find {operate_folder} -type f -delete",
                f"find {operate_folder} -type d -delete"
            ]
            
            for cmd in commands:
                os.system(cmd)
                time.sleep(1)
                if not operate_folder.exists():
                    break
                    
            if operate_folder.exists():
                print(f"Failed to delete directory using standard methods, attempting with sudo...")
                os.system(f"sudo rm -rf {operate_folder}")
                
            if operate_folder.exists():
                print("Warning: Directory still exists after all cleanup attempts")
                # List directory contents and permissions for debugging
                os.system(f"ls -la {operate_folder}")
                os.system(f"lsof +D {operate_folder}")
                
        except Exception as e:
            print(f"Error while cleaning up .operate folder: {str(e)}")

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

def stop_service(logger: logging.Logger) -> bool:
    """Stop the service and verify shutdown."""
    logger.info("Stopping service...")
    try:
        # Execute stop script
        stop_script = Path("./stop_service.sh")
        os.chmod(stop_script, 0o755)
        process = pexpect.spawn('bash ./stop_service.sh', encoding='utf-8', timeout=30)
        process.expect(pexpect.EOF)
        
        # Wait for service to fully stop
        time.sleep(5)
        
        # Check shutdown logs
        if not check_shutdown_logs(logger):
            return False
            
        # Verify docker containers are stopped
        client = docker.from_env()
        containers = client.containers.list(filters={"name": "traderpearl"})
        if len(containers) > 0:
            logger.error("Containers still running after stop_service.sh")
            return False
            
        logger.info("Service stopped successfully")
        return True
        
    except Exception as e:
        logger.error(f"Service stop failed: {str(e)}")
        return False

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

    test_results = {
        "service_logs": False,
        "docker_status": False,
        "health_check": False,
        "shutdown_logs": False
    }
    
    try:
        script_path = Path("./run_service.sh")
        os.chmod(script_path, 0o755)

        # Start the process with pexpect
        child = pexpect.spawn(
            'bash ./run_service.sh',
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
            logger.info("Initial setup completed successfully")
            
            # Wait for service to fully start
            time.sleep(5)
            
            # Test Case 1: Check Service Logs
            logger.info("Running Test Case 1: Service Logs Check")
            test_results["service_logs"] = check_service_logs(logger)
            
            # Test Case 2: Check Docker Status
            logger.info("Running Test Case 2: Docker Status Check")
            test_results["docker_status"] = check_docker_status(logger)
            
            # Test Case 3: Check Service Health
            logger.info("Running Test Case 3: Service Health Check")
            test_results["health_check"] = check_service_health(logger)
            
            # Stop the service
            logger.info("Stopping service for shutdown test...")
            test_results["shutdown_logs"] = stop_service(logger)
            
            # Log test results
            logger.info("\nTest Results:")
            for test_name, result in test_results.items():
                status = colored("PASSED", "green") if result else colored("FAILED", "red")
                logger.info(f"{test_name}: {status}")
                
            # Overall test result
            if all(test_results.values()):
                logger.info(colored("\nAll tests passed successfully!", "green"))
            else:
                logger.error(colored("\nSome tests failed!", "red"))
                
        else:
            logger.error(f"Test failed with exit status {child.exitstatus}")
            
    except Exception as e:
        logger.error(f"Test failed with error: {str(e)}")
    finally:
        logger.info(f"Test logs saved to: {log_file}")

if __name__ == "__main__":
    test_run_service()