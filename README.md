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

Once the command has completed, i.e. the service is running, you can see the live logs with:

```bash
docker logs trader_abci_0 --follow
```

To stop your agent, use:

```bash
cd trader; poetry run autonomy deploy stop --build-dir trader_service/abci_build; cd .. 
```

## Observe your agents

1. Check out this handy app: https://predictions.oaksprout.repl.co/

2. Use the `trades` command to display information about placed trades by a given address:

    ```bash
    cd trader; poetry run python ../trades.py YOUR_SAFE_ADDRESS; cd ..
    ```

    Or restrict the search to specific dates by defining the "from" and "to" dates:
    ```bash
    cd trader; poetry run python ../trades.py YOUR_SAFE_ADDRESS --from-date 2023-08-15:03:50:00 --to-date 2023-08-20:13:45:00; cd ..
    ```

3. Use this command to investigate your agent's logs:

    ```bash
    cd trader; poetry run autonomy analyse logs --from-dir trader_service/abci_build/persistent_data/logs/ --agent aea_0 --reset-db; cd ..
    ```

    For example, inspect the state transitions using this command:

    ```bash
    cd trader; poetry run autonomy analyse logs --from-dir trader_service/abci_build/persistent_data/logs/ --agent aea_0 --fsm --reset-db; cd ..
    ```

    This will output the different state transitions of your agent per period, for example:

    ![Trader FSM transitions](images/trader_fsm_transitions.png)

    For more options on the above command run:

    ```bash
    cd trader; poetry run autonomy analyse logs --help; cd ..
    ```

    or take a look at the [command documentation](https://docs.autonolas.network/open-autonomy/advanced_reference/commands/autonomy_analyse/#autonomy-analyse-logs).

## Update between versions

Simply pull the latest script:

```bash
git pull origin
```

Remove the existing trader folder:

```bash
rm -rf trader
```

Then continue above with "Run the script".

## Advice for Mac users

In Docker Desktop make sure that in `Settings -> Advanced` the following boxes are ticked

![Docker Desktop settings](images/docker.png)

## Advice for Windows users

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
