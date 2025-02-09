#!/bin/bash

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

# force utf mode for python, cause sometimes there are issues with local codepages
export PYTHONUTF8=1


cd trader
service_dir="trader_service"
build_dir=$(ls -d "$service_dir"/abci_build_???? 2>/dev/null || echo "$service_dir/abci_build")
poetry run autonomy deploy stop --build-dir "$build_dir"
cd ..
