#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022-2023 Valory AG
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

"""This script sends the termination signal from a service owner to a service Safe."""

import argparse
import traceback
from web3 import Web3, HTTPProvider

TERMINATION_SIGNAL_WEI_AMOUNT = 0

def _send_termination_signal(private_key_path: str, recipient_address: str, rpc: str):
    try:
        with open(private_key_path, 'r') as key_file:
            private_key = key_file.read().strip()

        w3 = Web3(HTTPProvider(rpc))
        account = w3.eth.account.from_key(private_key)
        nonce = w3.eth.get_transaction_count(account.address)
        tx={
            'nonce': nonce,
            'to': recipient_address,
            'value': TERMINATION_SIGNAL_WEI_AMOUNT,
            'gas': 1000000,
            'gasPrice': w3.to_wei('5', 'gwei')
        }

        signed_tx = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        print(f"Termination signal sent. Transaction hash: {tx_hash.hex()}")
        print("Waiting for transaction receipt...")

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt['status'] == 1:
            print("Termination signal successfully mined.")
        else:
            print("Termination signal failed to be mined.")
            exit(1)

    except Exception as e:
        traceback.print_exc()
        print(f"An error occurred: {str(e)}")
        exit(1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Transfer 0 xDAI to a recipient address on the Gnosis chain.')
    parser.add_argument('private_key_path', type=str, help='Path to the file containing the Ethereum private key')
    parser.add_argument('recipient_address', type=str, help='Recipient address on the Gnosis chain')
    parser.add_argument('rpc', type=str, help='RPC for the Gnosis chain')
    args = parser.parse_args()
    _send_termination_signal(args.private_key_path, args.recipient_address, args.rpc)
