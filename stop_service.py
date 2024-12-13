# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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
"""Optimus Quickstart script."""
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
import sys

from operate.cli import OperateApp
from run_service import (
    print_title, OPERATE_HOME, load_local_config, get_service_template, print_section, get_service,
)


def main(service_name: str) -> None:
    """Stop service."""

    print_title(f"Stop {service_name} Quickstart")

    operate = OperateApp(home=OPERATE_HOME)
    operate.setup()

    # check if optimus was started before
    path = OPERATE_HOME / "local_config.json"
    if not path.exists():
        print("Nothing to clean. Exiting.")
        sys.exit(0)

    optimus_config = load_local_config()
    template = get_service_template(optimus_config)
    manager = operate.service_manager()
    service, _ = get_service(manager, template)
    manager.stop_service_locally(service_config_id=service.service_config_id, delete=True, use_docker=True)

    print()
    print_section(f"{service_name} service stopped")


if __name__ == "__main__":
    main(service_name="Trader")
