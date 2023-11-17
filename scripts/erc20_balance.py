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

"""This script prints the wxDAI balance of an address in WEI."""

import sys

from web3 import Web3, HTTPProvider

WXDAI_CONTRACT_ADDRESS = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"
WXDAI_ABI_PATH = "../contracts/wxdai.json"


def get_balance() -> int:
    """Get the wxDAI balance of an address in WEI."""
    w3 = Web3(HTTPProvider(rpc))
    contract_instance = w3.eth.contract(address=token, abi=abi)
    return contract_instance.functions.balanceOf(w3.to_checksum_address(address)).call()


def read_abi() -> str:
    """Read and return the wxDAI contract's ABI."""
    with open(WXDAI_ABI_PATH) as f:
        return f.read()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise ValueError("Expected the address and the rpc as positional arguments.")
    else:
        token = sys.argv[1]
        address = sys.argv[2]
        rpc = sys.argv[3]
        abi = read_abi()
        print(get_balance())
