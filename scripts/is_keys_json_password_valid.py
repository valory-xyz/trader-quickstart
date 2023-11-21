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

"""Checks if the provided password is valid for a keys.json file."""

import argparse
import json
import tempfile
import traceback
from pathlib import Path

from aea.crypto.helpers import DecryptError, KeyIsIncorrect
from aea_ledger_ethereum.ethereum import EthereumCrypto


def _is_keys_json_password_valid(
    keys_json_path: Path, password: str, debug: bool
) -> bool:
    keys = json.load(keys_json_path.open("r"))

    with tempfile.TemporaryDirectory() as temp_dir:
        for idx, key in enumerate(keys):
            temp_file = Path(temp_dir, str(idx))
            temp_file.open("w+", encoding="utf-8").write(str(key["private_key"]))

            try:
                EthereumCrypto.load_private_key_from_path(
                    str(temp_file), password=password
                )
            except (
                DecryptError,
                json.decoder.JSONDecodeError,
                KeyIsIncorrect,
            ):
                if debug:
                    stack_trace = traceback.format_exc()
                    print(stack_trace)
                return False

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Checks if the provided password is valid for a keys.json file."
    )
    parser.add_argument("keys_json_path", type=str, help="Path to the keys.json file.")
    parser.add_argument(
        "--password",
        type=str,
        help="Password. If not provided, it assumes keys.json is not password-protected.",
    )
    parser.add_argument("--debug", action="store_true", help="Prints debug messages.")
    args = parser.parse_args()
    print(
        _is_keys_json_password_valid(
            Path(args.keys_json_path), args.password, args.debug
        )
    )
