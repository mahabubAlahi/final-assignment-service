# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""This module contains the class to connect to a Betting contract."""

from typing import Dict

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi


PUBLIC_ID = PublicId.from_str("valory/betting:0.1.0")


class Betting(Contract):
    """The Betting contract."""

    contract_id = PUBLIC_ID

    @classmethod
    def match_keys(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
    ) -> JSONLike:
        """Get the match keys of the Betting contract."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        get_match_keys = getattr(contract_instance.functions, "matchKeys")  # noqa
        match_keys = get_match_keys().call()
        return dict(match_keys=match_keys)

    @classmethod
    def has_placed_bet(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        bettor: str,
        match_key: str,
    ) -> JSONLike:
        """Check whether the user already placed bet."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        has_placed_bet = contract_instance.functions.hasPlacedBet(bettor, match_key).call()
        return dict(data=has_placed_bet)
    
    @classmethod
    def is_valid_match_key(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        match_key: str,
    ) -> JSONLike:
        """Check whether the match key is valid."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        is_valid_key = contract_instance.functions.isValidMatchKey(match_key).call()
        return dict(data=is_valid_key)


    @classmethod
    def build_place_bet_tx(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        bettor: str,
        match_key: str,
    ) -> Dict[str, bytes]:
        """Build a place bet transaction."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI("placeBet", args=(bettor,match_key,))
        return {"data": bytes.fromhex(data[2:])}