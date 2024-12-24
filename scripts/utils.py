# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""This package contains utils for working with the staking contract."""

import json
import sys
from pathlib import Path
from operate.cli import OperateApp
from operate.constants import OPERATE_HOME
from operate.quickstart.run_service import configure_local_config, get_service
from operate.services.service import Service


def get_subgraph_api_key() -> str:
    """Get subgraph api key."""
    subgraph_api_key_path = OPERATE_HOME / "subgraph_api_key.txt"
    if subgraph_api_key_path.exists():
        return subgraph_api_key_path.read_text()
    
    subgraph_api_key = input("Please enter your subgraph api key: ")
    subgraph_api_key_path.write_text(subgraph_api_key)
    return subgraph_api_key 


def get_service_from_config(config_path: Path) -> Service:
    """Get service safe."""
    if not config_path.exists():
        print("No trader agent config found!")
        sys.exit(1)

    with open(config_path, "r") as config_file:
        template = json.load(config_file)
    
    operate = OperateApp()
    manager = operate.service_manager()
    configure_local_config(template)
    return get_service(manager, template)
