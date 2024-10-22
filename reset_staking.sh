#!/bin/bash

# Check if --unattended flag is passed
attended=true
for arg in "$@"; do
  if [ "$arg" = "--unattended" ]; then
    attended=false
  fi
done
export ATTENDED=$attended

cd trader; poetry run python ../scripts/choose_staking.py --reset; cd ..
