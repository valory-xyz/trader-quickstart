# trader-quickstart

A quickstart for the trader agent for AI prediction markets on Gnosis at https://github.com/valory-xyz/trader

## System Requirements

Ensure your machine satisfies the requirements:

  - Python `== 3.10`
  - [Poetry](https://python-poetry.org/docs/) `>=1.4.0`
  - [Docker Engine](https://docs.docker.com/engine/install/)
  - [Docker Compose](https://docs.docker.com/compose/install/)

## Resource Requirements

- You need xDAI on Gnosis Chain in one of your wallets.
- You need an RPC for your agent instance. We recommend https://getblock.io/.


## Run the script

```bash
chmod +x run_service.sh
./run_service.sh
```

## Observe your agents:

1. Check out this handy app: https://prediction-agents.replit.app/

2. Use this command to investigate your agent's logs:

```bash
cd trader; poetry run autonomy analyse logs --from-dir trader_service/abci_build/persistent_data/logs/ --agent aea_0; cd ..
```

For more options on the above command run:
```bash
cd trader; poetry run autonomy analyse logs --help; cd ..
```
