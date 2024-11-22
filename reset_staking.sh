#!/bin/bash

# force utf mode for python, cause sometimes there are issues with local codepages
export PYTHONUTF8=1


# Check if --attended flag is passed
export ATTENDED=true
for arg in "$@"; do
  if [ "$arg" = "--attended=false" ]; then
    export ATTENDED=false
  fi
done

cd trader; poetry run python ../scripts/choose_staking.py --reset; cd ..
