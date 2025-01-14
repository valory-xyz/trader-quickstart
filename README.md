# !!! DO NOT USE !!!

# OLAS Agents - Quickstart

A quickstart to run OLAS agents

## Compatible Systems

- Windows 10/11: WSL2 / Git BASH
- Mac ARM / Intel
- Linux
- Raspberry Pi 4

## System Requirements

Ensure your machine satisfies the requirements:

- Python `==3.10`
- [Poetry](https://python-poetry.org/docs/) `>=1.8.0`
- [Docker Compose](https://docs.docker.com/compose/install/)

## Resource Requirements

- You need native assets of the chain on which your agent will run in one of your wallets.
- You need an RPC of that chain for your agent instance. We recommend [Nodies RPC](https://www.nodies.app/).

## Run the Service

### For Non-Stakers

Clone this repository locally and execute:

```bash
chmod +x run_service.sh
./run_service.sh <agent_config.json>
```
where `agent_config.json` is the path to your agent configuration file. Check the `configs/` directory for available configurations of different agents.

#### Supported agents

| Agent | Config path | Docs |
| --- | --- | --- |
| Trader | `configs/config_predict_trader.json` | [Trader README](scripts/predict_trader/README.md) |
| Mech | `configs/config_mech.json` | [Mech README](https://github.com/valory-xyz/mech) |
| Optimus | `configs/config_optimus.json` | [Optimus README](https://github.com/valory-xyz/optimus) |
| Modius | `configs/config_modius.json` | [Modius README](https://github.com/valory-xyz/modius-quickstart) |
| Memeooorr | `configs/config_memeooorr.json` | [Memeooorr README](https://github.com/dvilelaf/meme-ooorr) |

Answer `1) No staking` when prompted:

```text
Please, select your staking program preference
```

### For Stakers

> :warning: **Warning** <br />
> The code within this repository is provided without any warranties. It is important to note that the code has not been audited for potential security vulnerabilities.
> Using this code could potentially lead to loss of funds, compromised data, or asset risk.
> Exercise caution and use this code at your own risk. Please refer to the [LICENSE](./LICENSE) file for details about the terms and conditions.

Each staking program has different OLAS requirements. The script will check that your owner address meets the minimum required OLAS on the required Chain.

Clone this repository locally and execute:

```bash
chmod +x run_service.sh
./run_service.sh
```

Select your preferred staking program when prompted (example):

```text
Please, select your staking program preference
----------------------------------------------
1) No staking
   Your Olas Predict agent will still actively participate in prediction
   markets, but it will not be staked within any staking program.

2) Quickstart Beta - Hobbyist
   The Quickstart Beta - Hobbyist staking contract offers 100 slots for
   operators running Olas Predict agents with the quickstart. It is designed as
   a step up from Coastal Staker Expeditions, requiring 100 OLAS for staking.
   The rewards are also more attractive than with Coastal Staker Expeditions.

3) Quickstart Beta - Expert
   The Quickstart Beta - Expert staking contract offers 20 slots for operators
   running Olas Predict agents with the quickstart. It is designed for
   professional agent operators, requiring 1000 OLAS for staking. The rewards
   are proportional to the Quickstart Beta - Hobbyist.

...
```

Find below a diagram of the possible status a service can be in the staking program:

![Staking FSM](images/staking_fsm.svg)

Services can become staked by invoking the `stake()` contract method, where service parameters and deposit amounts are verified. Staked services can call the `checkpoint()` method at regular intervals, ensuring liveness checks and calculating staking rewards. In case a service remains inactive beyond the specified `maxAllowedInactivity` time, it faces eviction from the staking program, ceasing to accrue additional rewards. Staked or evicted services can be unstaked by calling the `unstake()` contract method. They can do so after `minStakingDuration` has passed or if no more staking rewards are available.

 __Notes__:

- Staking is currently in a testing phase, so the number of agents that can be staked might be limited.
- Services are evicted after accumulating 2 consecutive checkpoints without meeting the activity threshold.  
- Currently, the minimum staking time is approximately 3 days. In particular, a service cannot be unstaked during the minimum staking period.
- Once a staking program is selected, you can reset your preference by stopping your agent by running `./stop_service.sh <agent_config.json>` and then running the command

  ``` bash
  ./reset_staking.sh  <agent_config.json>
  ```

  Keep in mind that your service must stay for `minStakingDuration` in a staking program (typically 3 days) before you can change to a new program.

### Service is Running

Once the command has completed, i.e. the service is running, you can see the live logs with:

```bash
docker logs <agent_name>_abci_0 --follow
```

To stop your agent, use:

```bash
./stop_service.sh <agent_config.json>
```

### Claim accrued OLAS

If your service is staked, you can claim accrued OLAS through the script

```bash
./claim_olas.sh <agent_config.json>
```

The accrued OLAS will be transferred to your service Safe without having to unstake your service.

### Backups

Agent runners are recommended to create a [backup](#backup-and-recovery) of the relevant secret key material.

<!-- 
TODO: support this
### Skip user prompts

You can optionally pass `--attended=false` or export the environment variable `ATTENDED=false` to skip asking for inputs from the user.
-->

## Update between versions

Simply pull the latest script:

```bash
git pull origin
```

Then continue above with [Run the script](https://github.com/valory-xyz/quickstart?tab=readme-ov-file#run-the-service).

## Change the password of your key files

> :warning: **Warning** <br />
> The code within this repository is provided without any warranties. It is important to note that the code has not been audited for potential security vulnerabilities.
>
> If you are updating the password for your key files, it is strongly advised to [create a backup](#backup-and-recovery) of the old configuration (located in the `./.operate` folder) before proceeding. This backup should be retained until you can verify that the changes are functioning as expected. For instance, run the service multiple times to ensure there are no issues with the new password before discarding the backup.

If you have started your script specifying a password to protect your key files, you can change it by running the following command:

```bash
./reset_password.sh
```

This will change the password in the following files:

- `.operate/user.json`
- `.operate/wallets/ethereum.txt`

## Advice for Mac users

In Docker Desktop make sure that in `Settings -> Advanced` the following boxes are ticked

![Docker Desktop settings](images/docker.png)

## Advice for Windows users using Git BASH

We provide some hints to have your Windows system ready to run the agent. The instructions below have been tested in Windows 11.

Execute the following steps in a PowerShell terminal:

1. Install [Git](https://git-scm.com/download/win) and Git Bash:

    ```bash
    winget install --id Git.Git -e --source winget
    ```

2. Install Python 3.10:

    ```bash
    winget install Python.Python.3.10
    ```

3. Close and re-open the PowerShell terminal.

4. Install [Poetry](https://python-poetry.org/docs/):

    ```bash
    curl.exe -sSL https://install.python-poetry.org | python -
    ```

5. Add Poetry to your user's path:

    ```bash
    $existingUserPath = (Get-Item -Path HKCU:\Environment).GetValue("PATH", $null, "DoNotExpandEnvironmentNames")

    $newUserPath = "$existingUserPath;$Env:APPDATA\Python\Scripts"

    [System.Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
    ```

6. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/):

    ```bash
    winget install -e --id Docker.DockerDesktop
    ```

7. Log out of your Windows session and then log back in.

8. Open [Docker Desktop](https://www.docker.com/products/docker-desktop/) and leave it opened in the background.

Now, open a Git Bash terminal and follow the instructions in the "[Run the script](#run-the-script)" section as well as the subsequent sections. You might need to install Microsoft Visual C++ 14.0 or greater.

## Backup and Recovery

When executed for the first time, the `run_service.sh` script creates a number of blockchain accounts:

- one EOA account will be used as the service owner and agent operator,
- one EOA account will be used for the agent, and
- one smart contract account corresponds to a [Safe](https://app.safe.global/) wallet with a single owner (the agent account).

The addresses and private keys of the EOA accounts (plus some additional configuration) are stored within the folder `.operate`. In order to avoid losing your assets, back up this folder in a safe place, and do not publish or share its contents with unauthorized parties.

You can gain access to the assets of your service as follows:

1. Ensure that your service is stopped by running `stop_service.sh`.
2. Ensure that you have a hot wallet (e.g., [MetaMask](https://metamask.io/)) installed and set up in your browser.
3. Import the two EOAs accounts using the private keys. In MetaMask, select "Add account or hardware wallet" &#8594; "Import account" &#8594; "Select Type: Private Key", and enter the private key of the owner/operator EOA account (located in `.operate/wallets/ethereum.txt`):
    <img src="images/metamask_import_private_key.png" alt="MetaMask import private key" style="width: 80%;">

4. Repeat the same process with the agent EOA account (private key located in `.operate/keys`).

Now, you have full access through the hot wallet to the EOAs addresses associated to your service and you can transfer their assets to any other address. You can also manage the assets of the service Safe through the DApp https://app.safe.global/, using the address located in the file `.operate/services/sc-.../config.json` against the `"multisig"` field.

## Terminate your on-chain service

If you wish to terminate your on-chain service (and receive back the staking/bonding funds to your owner/operator address in case your service is staked) execute:

```bash
./stop_service.sh <agent_config.json>
./terminate_on_chain_service.sh <agent_config.json>
```

## RPC-related Error Messages

When updating the service, you may need to re-run the script if you obtain any of the following error messages:

```Error: Service terminatation failed with following error; ChainTimeoutError(Timed out when waiting for transaction to go through)

Error: Service unbonding failed with following error; ChainTimeoutError(Timed out when waiting for transaction to go through)

Error: Component mint failed with following error; ChainTimeoutError(Timed out when waiting for transaction to go through)

Error: Service activation failed with following error; ChainTimeoutError(Timed out when waiting for transaction to go through)

Error: Service deployment failed with following error; ChainTimeoutError(Timed out when waiting for transaction to go through)

Error: Service terminatation failed with following error; ChainInteractionError({'code': -32010, 'message': 'AlreadyKnown'})
```

<!-- 
TODO: support this
## Build deployments without executing the service

The script builds both a Docker Compose deployment (on `./trader/trader_service/abci_build`) and a Kubernetes deployment (on `./trader/trader_service/abci_build_k8s`). Then, by default, the script will launch the local Docker Compose deployment. If you just want to build the deployment without executing the service (for example, if you are deploying to a custom Kubernetes cluster), then execute the script as

```bash
    ./run_service.sh --build-only
```
-->
