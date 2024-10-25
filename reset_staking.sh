#!/bin/bash

# Check if --attended flag is passed
export ATTENDED=true
for arg in "$@"; do
  if [ "$arg" = "--attended=false" ]; then
    export ATTENDED=false
  fi
done

cd trader; poetry run python ../scripts/choose_staking.py --reset; cd ..
