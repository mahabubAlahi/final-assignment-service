## Betting Service

This service will work based on the common betting strategy called odds comparison or value betting. It will usually aggregate football match odds from multiple websites, apply custom logic to analyze them and decide where and how to place a bet.

- `Custom Betting Odds API`
  - It is a simple Node.js application built using the Express framework. The API serves predefined betting odds for football matches and allows users to query match odds and check if a specific bet has the highest odds.
    - Features
       - Endpoint to retrieve betting odds for specific matches.
    - API endpoint for Getting Match Odds
       - URL: `/api/odd`
       - Method: GET
       - Query Parameters:
         - opponent1 (required): Name of the first opponent.
         - opponent2 (required): Name of the second opponent.
         - bet_against (required): The specific bet to check for the highest odds.
       - Description: Fetches the betting odds for a specific match and checks if the specified bet has the highest odds.
       - Response:
         - Success:
            ```JS
            {
                "execStatus": true,
                "msg": "Successfully get the odds!",
                "data": {
                    "match": {
                        "PORTUGAL": 3.5,
                        "SWITZERLAND": 2.0,
                        "DRAW": 2.2
                    },
                    "result": true
                }
            }
            ```
    - Github Repository Link: [Simple betting api](https://github.com/mahabubAlahi/simple-betting-api.git)
    - Deployed in AWS EC2:- `http://3.84.150.52:3009`

- `Betting Smart Contract`
  - This smart contract allows users to place bets on predefined matches and check their betting status. It also provides functionality for the contract owner to add new match keys.
  - Features
    - Predefined Match Keys:
      - The contract owner can initialize and add match keys.
    - Place Bets:
      - Users can place bets on predefined matches by sending Ether.
    - Check Betting Status:
      - Users can verify if they have placed a bet on a specific match.
  -  Github Repository Link: [Betting smart contract](https://github.com/mahabubAlahi/betting-contract.git)

- This betting service has two main skills, It also has a contract, agent and service file named.
   - betting_abci
   - betting_chained_abci
   - betting contract
   - betting_agent
   - betting_service

- State transition of `betting_abci` skill
  - States
     - Start States:
         - **DataPullRound**:- In this round, it pulls betting result from the `Custom Betting Odds API`, store the betting result in the IPFS, and check whether the predefined user already place the bet in the `Betting Smart Contract`. Finally it stores `betting_result`, `betting_ipfs_hash`, `has_placed_bet` in the payload.
     - Intermediate States:
         - **DecisionMakingRound**:- It generally takes a decision whether the bet should be placed on the `Betting Smart Contract` based on the previous round's value. If the betting result is `True` and the user has not placed the bet yet, it returns `TRANSACT` event, otherwise it returns `DONE` event.
         - **TxPreparationRound**:- In this round, depending on the timestamp's last number, it will make a native transaction, a betting transaction or both.
      - Final States:
         - **FinishedDecisionMakingRound**
         - **FinishedTxPreparationRound**
      - Default Start State
         - **DataPullRound**: The state where the application begins its execution.
      - Final States
        The application reaches completion in either of the following states:
        - **FinishedDecisionMakingRound**
        - **FinishedTxPreparationRound**
- State Transitions
The transition_func defines how the application transitions between states based on events:
  - DataPullRound:
     - **DONE**: Transition to DecisionMakingRound.
     - **NO_MAJORITY or ROUND_TIMEOUT**: Remain in DataPullRound.
  - DecisionMakingRound:
    - **DONE**: Transition to FinishedDecisionMakingRound.
    - **ERROR**: Transition to FinishedDecisionMakingRound.
    - **NO_MAJORITY or ROUND_TIMEOUT**: Remain in 
  - DecisionMakingRound.
    - **TRANSACT**: Transition to TxPreparationRound.
  - TxPreparationRound:
    - **DONE**: Transition to FinishedTxPreparationRound.
    - **NO_MAJORITY or ROUND_TIMEOUT**: Remain in TxPreparationRound.


## System requirements

- Python `>=3.10`
- [Tendermint](https://docs.tendermint.com/v0.34/introduction/install.html) `==0.34.19`
- [IPFS node](https://docs.ipfs.io/install/command-line/#official-distributions) `==0.6.0`
- [Pip](https://pip.pypa.io/en/stable/installation/)
- [Poetry](https://python-poetry.org/)
- [Docker Engine](https://docs.docker.com/engine/install/)
- [Docker Compose](https://docs.docker.com/compose/install/)
- [Set Docker permissions so you can run containers as non-root user](https://docs.docker.com/engine/install/linux-postinstall/)


## Run you own agent

### Get the code

1. Clone this repo:

    ```
    git clone git@github.com:mahabubAlahi/final-assignment-service.git
    ```

2. Create the virtual environment:

    ```
    cd final-assignment-service
    poetry shell
    poetry install
    ```

3. Sync packages:

    ```
    autonomy packages sync --update-packages
    ```

### Prepare the data

1. Prepare a keys.json file containing wallet address and the private key for each of the four agents.

    ```
    autonomy generate-key ethereum -n 4
    ```

2. Prepare a `ethereum_private_key.txt` file containing one of the private keys from `keys.json`. Ensure that there is no newline at the end.

3. Deploy two [Safes on Gnosis](https://app.safe.global/welcome) (it's free) and set your agent addresses as signers. Set the signature threshold to 1 out of 4 for one of them and and to 3 out of 4 for the other. This way we can use the single-signer one for testing without running all the agents, and leave the other safe for running the whole service.

4. Create a [Tenderly](https://tenderly.co/) account and from your dashboard create a fork of Gnosis chain (virtual testnet).

5. From Tenderly, fund your agents and Safe with some xDAI and OLAS (`0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f`).

6. Make a copy of the env file:

    ```
    cp sample.env .env
    ```

7. Fill in the required environment variables in .env. These variables are:
- `ALL_PARTICIPANTS`: a list of your agent addresses. This will vary depending on whether you are running a single agent (`run_agent.sh` script) or the whole 4-agent service (`run_service.sh`)
- `GNOSIS_LEDGER_RPC`: set it to your Tenderly fork Admin RPC.
- `COINGECKO_API_KEY`: you will need to get a free [Coingecko](https://www.coingecko.com/) API key.
- `TRANSFER_TARGET_ADDRESS`: any random address to send funds to, can be any of the agents for example.
- `SAFE_CONTRACT_ADDRESS_SINGLE`: the 1 out of 4 agents Safe address.
- `SAFE_CONTRACT_ADDRESS`: the 3 out of 4 Safe address.


### Run a single agent locally

1. Verify that `ALL_PARTICIPANTS` in `.env` contains only 1 address.

2. Run the agent:

    ```
    bash run_agent.sh
    ```

### Run the service (4 agents) via Docker Compose deployment

1. Verify that `ALL_PARTICIPANTS` in `.env` contains 4 address.

2. Check that Docker is running:

    ```
    docker
    ```

3. Run the service:

    ```
    bash run_service.sh
    ```

4. Look at the service logs for one of the agents (on another terminal):

    ```
    docker logs -f bettingservice_abci_0
    ```