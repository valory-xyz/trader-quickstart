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

"""Changes the key files password of the trader store."""

import argparse
import json
import tempfile
from pathlib import Path

from aea.crypto.helpers import DecryptError
from aea_ledger_ethereum.ethereum import EthereumCrypto


def _change_keys_json_password(
    keys_json_path: Path, pkey_txt_path: Path, current_password: str, new_password: str
) -> None:
    keys_json_reencrypeted = []
    keys = json.load(keys_json_path.open("r"))

    with tempfile.TemporaryDirectory() as temp_dir:
        for idx, key in enumerate(keys):
            temp_file = Path(temp_dir, str(idx))
            temp_file.open("w+", encoding="utf-8").write(str(key["private_key"]))
            try:
                crypto = EthereumCrypto.load_private_key_from_path(
                    str(temp_file), password=current_password
                )

                private_key_reencrypted = crypto.encrypt(new_password)
                keys_json_reencrypeted.append(
                    {
                        "address": crypto.address,
                        "private_key": f"{json.dumps(private_key_reencrypted)}",
                    }
                )
                json.dump(keys_json_reencrypeted, keys_json_path.open("w+"), indent=2)
                print(f"Changed password {keys_json_path}")

                json.dump(private_key_reencrypted, pkey_txt_path.open("w+"))
                print(f"Ovewritten {keys_json_path}")
            except DecryptError:
                print("Bad password provided.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Change key files password.")
    parser.add_argument(
        "store_path", type=str, help="Path to the trader store directory."
    )
    parser.add_argument("current_password", type=str, help="Current password.")
    parser.add_argument("new_password", type=str, help="New password.")
    args = parser.parse_args()

    for json_file, pkey_file in (("keys", "agent_pkey"), ("operator_keys", "operator_pkey")):
        filepaths = (Path(args.store_path, file) for file in (f"{json_file}.json", f"{pkey_file}.txt"))
        _change_keys_json_password(
            *filepaths,
            args.current_password,
            args.new_password,
        )
