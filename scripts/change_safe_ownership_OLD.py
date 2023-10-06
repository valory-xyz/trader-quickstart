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


import argparse
import json
from pathlib import Path
import traceback
from hexbytes import HexBytes
from web3 import Web3, HTTPProvider
from eth_account.messages import encode_defunct


SENTINEL_OWNER = Web3.to_checksum_address("0x0000000000000000000000000000000000000001")
NULL_ADDRESS: str = "0x" + "0" * 40



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Transfer 0 xDAI to a recipient address on the Gnosis chain.')
    parser.add_argument('safe_address', type=str, help='Path to the file containing the Ethereum private key')    
    parser.add_argument('current_owner_address', type=str, help='Path to the file containing the Ethereum private key')
    parser.add_argument('current_owner_private_key', type=str, help='Path to the file containing the Ethereum private key')    
    parser.add_argument('new_owner_address', type=str, help='Recipient address on the Gnosis chain')
    parser.add_argument('rpc', type=str, help='RPC for the Gnosis chain')
    args = parser.parse_args()

    try:
        json_file_path = Path(Path(__file__).parent, '..', 'contracts', 'GnosisSafe_V1_3_0.json')
        with open(json_file_path, 'r') as json_file:
            contract_data = json.load(json_file)
            abi = contract_data.get('abi', [])

        w3 = Web3(HTTPProvider(args.rpc))
        safe = w3.eth.contract(address=args.safe_address, abi=abi)


        data = safe.encodeABI(
             fn_name="swapOwner",
             args = [
                SENTINEL_OWNER,
                args.current_owner_address,
                args.new_owner_address
            ])

        print(data)
        print("!!!")        
        print(bytes.fromhex(data[2:]))
        print("!!!")        
        print(HexBytes(data[2:]))
        print("!!!")
        print(HexBytes(data))
        print("!!!")
        print(encode_defunct(w3.to_bytes(hexstr=data)))
        print("!!!!")

        signed_message1 = w3.eth.account.sign_message(encode_defunct(w3.to_bytes(hexstr=data)), private_key=args.current_owner_private_key)
        signature = hex(signed_message1.r) + hex(signed_message1.s)[2:] + hex(signed_message1.v + 4)[2:]
        r_bytes = signed_message1.r.to_bytes(32, byteorder='big')
        s_bytes = signed_message1.s.to_bytes(32, byteorder='big')
        v_bytes = signed_message1.v.to_bytes(1, byteorder='big')
        signature_bytes = r_bytes + s_bytes + v_bytes
        signatures = b"".join([r_bytes, s_bytes, v_bytes])

        # Send the tx to the Safe
        current_account = w3.eth.account.from_key(args.current_owner_private_key)
        nonce = w3.eth.get_transaction_count(current_account.address)
        tx = safe.functions.execTransaction(
            to = safe.address,
            value = w3.to_int(0),
            data = w3.to_bytes(hexstr=data),
            operation = 0,
            safeTxGas = 0,
            baseGas = 0,
            gasPrice = 0,
            gasToken = NULL_ADDRESS,
            refundReceiver = args.current_owner_address,
            signatures = signatures
        ).build_transaction({
            'nonce': nonce,
            'chainId': 100,
            'gas': 1000000,
            'gasPrice': w3.to_wei('5', 'gwei')
        })

        exit(1)
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=args.current_owner_private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)

        print(f"Swap Safe owners transaction sent. Transaction hash: {tx_hash.hex()}")
        print("Waiting for transaction receipt...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt['status'] == 1:
            print("Swap Safe owners transaction successfully mined.")
        else:
            print("Swap Safe owners transaction failed to be mined.")
            exit(1)

    except Exception as e:
        traceback.print_exc()
        print(f"An error occurred: {str(e)}")
        exit(1)
