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

"""This package contains round behaviours of BettingAbciApp."""
import asyncio
import json
from abc import ABC
from pathlib import Path
from tempfile import mkdtemp
from typing import Dict, Generator, Optional, Set, Type, cast

from packages.valory.contracts.betting.contract import Betting
from packages.valory.contracts.gnosis_safe.contract import (
    GnosisSafeContract,
    SafeOperation,
)
from packages.valory.contracts.multisend.contract import (
    MultiSendContract,
    MultiSendOperation,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.ledger_api import LedgerApiMessage
from packages.valory.skills.abstract_round_abci.base import AbstractRound
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.abstract_round_abci.io_.store import SupportedFiletype
from packages.valory.skills.betting_abci.models import (
    BettingSpecs,
    CoingeckoSpecs,
    Params,
    SharedState,
)
from packages.valory.skills.betting_abci.payloads import (
    DataPullPayload,
    DecisionMakingPayload,
    TxPreparationPayload,
)
from packages.valory.skills.betting_abci.rounds import (
    DataPullRound,
    DecisionMakingRound,
    Event,
    BettingAbciApp,
    SynchronizedData,
    TxPreparationRound,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
)
from packages.valory.skills.transaction_settlement_abci.rounds import TX_HASH_LENGTH


# Define some constants
ZERO_VALUE = 0
HTTP_OK = 200
GNOSIS_CHAIN_ID = "gnosis"
EMPTY_CALL_DATA = b"0x"
SAFE_GAS = 0
VALUE_KEY = "value"
TO_ADDRESS_KEY = "to_address"
METADATA_FILENAME = "metadata.json"


class BettingBaseBehaviour(BaseBehaviour, ABC):  # pylint: disable=too-many-ancestors
    """Base behaviour for the betting_abci behaviours."""

    @property
    def params(self) -> Params:
        """Return the params. Configs go here"""
        return cast(Params, super().params)

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data. This data is common to all agents"""
        return cast(SynchronizedData, super().synchronized_data)

    @property
    def local_state(self) -> SharedState:
        """Return the local state of this particular agent."""
        return cast(SharedState, self.context.state)

    @property
    def coingecko_specs(self) -> CoingeckoSpecs:
        """Get the Coingecko api specs."""
        return self.context.coingecko_specs
    
    @property
    def betting_specs(self) -> BettingSpecs:
        """Get the Betting api specs."""
        return self.context.betting_specs

    @property
    def metadata_filepath(self) -> str:
        """Get the temporary filepath to the metadata."""
        return str(Path(mkdtemp()) / METADATA_FILENAME)

    def get_sync_timestamp(self) -> float:
        """Get the synchronized time from Tendermint's last block."""
        now = cast(
            SharedState, self.context.state
        ).round_sequence.last_round_transition_timestamp.timestamp()

        return now


class DataPullBehaviour(BettingBaseBehaviour):  # pylint: disable=too-many-ancestors
    """This behaviours pulls betting result from API endpoints and reads the bet is already submit or not"""

    matching_round: Type[AbstractRound] = DataPullRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            sender = self.context.agent_address

            # This call receive the betting result from the API
            response = yield from self.get_betting_result_specs()
            self.context.logger.info(f"Betting result API value: {response}")

            # Store the betting result in IPFS
            betting_ipfs_hash = yield from self.send_betting_result_to_ipfs(response)

            has_placed_bet = yield from self.get_has_placed_bet()
            self.context.logger.info(f"Placed bet value from contract: {has_placed_bet}")

            # Prepare the payload to be shared with other agents
            # After consensus, all the agents will have the same betting_result, betting_ipfs_hash and has_placed_bet variables in their synchronized data
            payload = DataPullPayload(
                sender=sender,
                betting_result=response['result'],
                betting_ipfs_hash=betting_ipfs_hash,
                has_placed_bet=has_placed_bet[0],
            )

        # Send the payload to all agents and mark the behaviour as done
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def get_betting_result_specs(self) -> Generator[None, None, dict]:
        """Get betting result using ApiSpecs"""

        # Get the specs
        specs = self.betting_specs.get_spec()

        # Make the call
        raw_response = yield from self.get_http_response(**specs)

        # Process the response
        response = self.betting_specs.process_response(raw_response)

        self.context.logger.info(f"Got betting result from API: {response}")
        return response

    def send_betting_result_to_ipfs(self, data) -> Generator[None, None, Optional[str]]:
        """Store the betting result in IPFS"""
        betting_ipfs_hash = yield from self.send_to_ipfs(
            filename=self.metadata_filepath, obj=data, filetype=SupportedFiletype.JSON
        )
        self.context.logger.info(
            f"Betting result data stored in IPFS: https://gateway.autonolas.tech/ipfs/{betting_ipfs_hash}"
        )
        return betting_ipfs_hash

    def get_has_placed_bet(self) -> Generator[None, None, dict]:
        """Get the bet is already placed or not"""
        self.context.logger.info(
            f"Getting the bet is already placed or not for: {self.synchronized_data.safe_contract_address}"
        )

        # Use the contract api to interact with the Betting contract
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.betting_contract_address,
            contract_id=str(Betting.contract_id),
            contract_callable="has_placed_bet",
            chain_id=GNOSIS_CHAIN_ID,
            bettor=self.params.transfer_target_address,
            match_key=self.params.match_key,
        )

        # Check that the response is what we expect
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Error while retrieving the balance: {response_msg}"
            )
            return None

        response = response_msg.raw_transaction.body.get('data', None)

        # Ensure that the balance is not None
        if response is None:
            self.context.logger.error(
                f"Error while retrieving the betting placement result:  {response_msg}"
            )
            return None


        self.context.logger.info(
            f"Account {self.synchronized_data.safe_contract_address} betting placement result: {response}"
        )
        return response


class DecisionMakingBehaviour(
    BettingBaseBehaviour
):  # pylint: disable=too-many-ancestors
    """DecisionMakingBehaviour"""

    matching_round: Type[AbstractRound] = DecisionMakingRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            sender = self.context.agent_address

            # Make a decision: either transact or not
            event = self.get_next_event()

            self.context.logger.info(
                f"Event value: {event}"
            )
            payload = DecisionMakingPayload(sender=sender, event=event)

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def get_next_event(self) -> str:
        """Get the next event: decide whether ot transact or not based on some data."""

        # This method showcases how to make decisions based on conditions.

        # Get the betting result we get in the previous round
        betting_result = self.synchronized_data.betting_result

        # Similarly, get user already placed the bet result we get in the previous round
        has_placed_bet = self.synchronized_data.has_placed_bet

        # If the betting result is True and the user has not placed the bet yet, we transact
        if betting_result and not has_placed_bet:
            self.context.logger.info("Betting result is true and the user has not placed the bet yet. Transacting.")
            return Event.TRANSACT.value
        else:
            # Otherwise we send the DONE event
            self.context.logger.info("Either betting result is False or the user has already placed the bet. Not transacting.")
            return Event.DONE.value


class TxPreparationBehaviour(
    BettingBaseBehaviour
):  # pylint: disable=too-many-ancestors
    """TxPreparationBehaviour"""

    matching_round: Type[AbstractRound] = TxPreparationRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            sender = self.context.agent_address

            # Get the transaction hash
            tx_hash = yield from self.get_tx_hash()

            payload = TxPreparationPayload(
                sender=sender, tx_submitter=self.auto_behaviour_id(), tx_hash=tx_hash
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def get_tx_hash(self) -> Generator[None, None, Optional[str]]:
        """Get the transaction hash"""

        # Here want to showcase how to prepare different types of transactions.
        # Depending on the timestamp's last number, we will make a native transaction,
        # an betting transaction or both.

        # All transactions need to be sent from the Safe controlled by the agents.

        # Again, make a decision based on the timestamp (on its last number)
        now = int(self.get_sync_timestamp())
        self.context.logger.info(f"Timestamp is {now}")
        last_number = int(str(now)[-1])

        # Betting transaction (Safe -> Betting contract)
        if last_number in [0, 1, 2, 3, 4, 5, 6]:
            self.context.logger.info("Preparing a betting transaction")
            tx_hash = yield from self.get_place_bet_safe_tx_hash()
            return tx_hash
        # Multisend transaction (both native and betting)
        else:
            self.context.logger.info("Preparing a multisend transaction")
            tx_hash = yield from self.get_multisend_safe_tx_hash()
            return tx_hash

    def get_native_transfer_data(self) -> Dict:
        """Get the native transaction data"""
        # Send 1 wei to the recipient
        data = {VALUE_KEY: 1, TO_ADDRESS_KEY: self.params.transfer_target_address}
        self.context.logger.info(f"Native transfer data is {data}")
        return data

    def get_place_bet_safe_tx_hash(self) -> Generator[None, None, Optional[str]]:
        """Prepare a Betting safe transaction"""

        # Transaction data
        data_hex = yield from self.get_place_bet_data()

        # Check for errors
        if data_hex is None:
            return None

        # Prepare safe transaction
        safe_tx_hash = yield from self._build_safe_tx_hash(
            to_address=self.params.betting_contract_address, data=bytes.fromhex(data_hex),
            value=self.params.betting_amount
        )

        self.context.logger.info(f"Betting transaction hash is {safe_tx_hash}")

        return safe_tx_hash

    def get_place_bet_data(self) -> Generator[None, None, Optional[str]]:
        """Get the betting placement transaction data"""

        self.context.logger.info("Preparing betting placement transaction")

        # Use the contract api to interact with the Betting contract
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.betting_contract_address,
            contract_id=str(Betting.contract_id),
            contract_callable="build_place_bet_tx",
            match_key=self.params.match_key,
            bettor=self.params.transfer_target_address,
            chain_id=GNOSIS_CHAIN_ID,
        )

        # Check that the response is what we expect
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Error while retrieving the betting transaction: {response_msg}"
            )
            return None

        data_bytes: Optional[bytes] = response_msg.raw_transaction.body.get(
            "data", None
        )

        # Ensure that the data is not None
        if data_bytes is None:
            self.context.logger.error(
                f"Error while preparing the transaction: {response_msg}"
            )
            return None

        data_hex = data_bytes.hex()
        self.context.logger.info(f"Betting transaction data is {data_hex}")
        return data_hex

    def get_multisend_safe_tx_hash(self) -> Generator[None, None, Optional[str]]:
        """Get a multisend transaction hash"""
        # Step 1: we prepare a list of transactions
        # Step 2: we pack all the transactions in a single one using the mulstisend contract
        # Step 3: we wrap the multisend call inside a Safe call, as always

        multi_send_txs = []

        # Native transfer
        native_transfer_data = self.get_native_transfer_data()
        multi_send_txs.append(
            {
                "operation": MultiSendOperation.CALL,
                "to": self.params.transfer_target_address,
                "value": native_transfer_data[VALUE_KEY],
                # No data key in this transaction, since it is a native transfer
            }
        )

        # Betting transaction
        place_bet_data_hex = yield from self.get_place_bet_data()

        if place_bet_data_hex is None:
            return None

        multi_send_txs.append(
            {
                "operation": MultiSendOperation.CALL,
                "to": self.params.betting_contract_address,
                "value": self.params.betting_amount,
                "data": bytes.fromhex(place_bet_data_hex),
            }
        )

        # Multisend call
        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.multisend_address,
            contract_id=str(MultiSendContract.contract_id),
            contract_callable="get_tx_data",
            multi_send_txs=multi_send_txs,
            chain_id=GNOSIS_CHAIN_ID,
        )

        # Check for errors
        if (
            contract_api_msg.performative
            != ContractApiMessage.Performative.RAW_TRANSACTION
        ):
            self.context.logger.error(
                f"Could not get Multisend tx hash. "
                f"Expected: {ContractApiMessage.Performative.RAW_TRANSACTION.value}, "
                f"Actual: {contract_api_msg.performative.value}"
            )
            return None

        # Extract the multisend data and strip the 0x
        multisend_data = cast(str, contract_api_msg.raw_transaction.body["data"])[2:]
        self.context.logger.info(f"Multisend data is {multisend_data}")

        # Prepare the Safe transaction
        safe_tx_hash = yield from self._build_safe_tx_hash(
            to_address=self.params.multisend_address,
            value=ZERO_VALUE,  # the safe is not moving any native value into the multisend
            data=bytes.fromhex(multisend_data),
            operation=SafeOperation.DELEGATE_CALL.value,  # we are delegating the call to the multisend contract
        )
        return safe_tx_hash

    def _build_safe_tx_hash(
        self,
        to_address: str,
        value: int = ZERO_VALUE,
        data: bytes = EMPTY_CALL_DATA,
        operation: int = SafeOperation.CALL.value,
    ) -> Generator[None, None, Optional[str]]:
        """Prepares and returns the safe tx hash for a multisend tx."""

        self.context.logger.info(
            f"Preparing Safe transaction [{self.synchronized_data.safe_contract_address}]"
        )

        # Prepare the safe transaction
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=to_address,
            value=value,
            data=data,
            safe_tx_gas=SAFE_GAS,
            chain_id=GNOSIS_CHAIN_ID,
            operation=operation,
        )

        # Check for errors
        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.error(
                "Couldn't get safe tx hash. Expected response performative "
                f"{ContractApiMessage.Performative.STATE.value!r}, "  # type: ignore
                f"received {response_msg.performative.value!r}: {response_msg}."
            )
            return None

        # Extract the hash and check it has the correct length
        tx_hash: Optional[str] = response_msg.state.body.get("tx_hash", None)

        if tx_hash is None or len(tx_hash) != TX_HASH_LENGTH:
            self.context.logger.error(
                "Something went wrong while trying to get the safe transaction hash. "
                f"Invalid hash {tx_hash!r} was returned."
            )
            return None

        # Transaction to hex
        tx_hash = tx_hash[2:]  # strip the 0x

        safe_tx_hash = hash_payload_to_hex(
            safe_tx_hash=tx_hash,
            ether_value=value,
            safe_tx_gas=SAFE_GAS,
            to_address=to_address,
            data=data,
            operation=operation,
        )

        self.context.logger.info(f"Safe transaction hash is {safe_tx_hash}")

        return safe_tx_hash


class BettingRoundBehaviour(AbstractRoundBehaviour):
    """BettingRoundBehaviour"""

    initial_behaviour_cls = DataPullBehaviour
    abci_app_cls = BettingAbciApp  # type: ignore
    behaviours: Set[Type[BaseBehaviour]] = [  # type: ignore
        DataPullBehaviour,
        DecisionMakingBehaviour,
        TxPreparationBehaviour,
    ]
