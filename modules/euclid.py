# modules/euclid_swap.py

import asyncio
import json
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from web3 import Web3
from web3.types import TxParams

from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import Networks, TokenAmount
from libs.eth_async.utils.utils import randfloat
from utils.logs_decorator import controller_log
from utils.retry import async_retry
from utils.browser import Browser
from utils.db_api.models import Wallet


EUCLID_GRAPHQL = "https://testnet.api.euclidprotocol.com/graphql"
EUCLID_SWAP    = "https://testnet.api.euclidprotocol.com/api/v1/execute/astro/swap"
EUCLID_ROUTES  = "https://testnet.api.euclidprotocol.com/api/v1/routes"   # ?limit=10


class EuclidSwap(Base):
    __module_name__ = "EuclidSwap"

    def __init__(self, wallet: Wallet):
        self.client  = Client(private_key=wallet.private_key, proxy=wallet.proxy, network=Networks.MonadTestnet)
        self.wallet  = wallet
        self.session = Browser(wallet=wallet)

        self.base_headers = {
            "accept": "*/*",
            "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "content-type": "application/json",
            "origin": "https://testnet.euclidswap.io",
            "priority": "u=1, i",
            "referer": "https://testnet.euclidswap.io/",
        }

    @async_retry(retries=3, delay=2, to_raise=True)
    async def build_swap(self, payload: dict) -> dict:

        r = await self.session.post(url=EUCLID_SWAP, headers=self.base_headers, json=payload, )
        r.raise_for_status()

        return r.json()

    @controller_log("Swap")
    async def swap_controller(self) -> str:

        settings = Settings()
        amount = TokenAmount(amount=randfloat(from_=settings.monad_transfer_min,
                                              to_=settings.monad_transfer_max, step=0.1))

        balance = await self.client.wallet.balance()

        if balance.Ether == 0:
            raise Exception(f"Failed | No native Monad balance")

        if float(balance.Ether) <= float(amount.Ether):
            msg = f"{self.wallet} | {self.__module_name__} | balance: {balance} MON < amount {amount} MON"
            logger.warning(msg)
            raise Exception(f"balance: {balance} MON < amount {amount} MON")

        limit_lte = str(int(amount.Wei * 10))

        return await self._swap(amount=amount, limit_lte=limit_lte)

    @async_retry(retries=3, delay=2, to_raise=False)
    async def fetch_routes(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in: TokenAmount,
        chain_uids: Optional[List[str]] = None,
        external: bool = True,
        limit: int = 10,
    ) -> dict:

        url = f"{EUCLID_ROUTES}?limit={int(limit)}"
        payload = {
            "external": external,
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": str(int(amount_in.Wei)),
            "chain_uids": chain_uids or [],
        }

        r = await self.session.post(
            url=url,
            json=payload,
            headers=self.base_headers
        )

        return r.json().get('path')

    async def _swap(self, amount: TokenAmount, limit_lte: str) -> str:

        sender_addr = self.client.account.address
        recipient_addr = self.client.account.address

        payload = {
            "amount_in": str(amount.Wei),
            "asset_in": {
                "token": "mon",
                "token_type": {
                    "__typename": "NativeTokenType",
                    "native": {"__typename": "NativeToken", "denom": "mon"},
                },
            },
            "slippage": "500",
            "cross_chain_addresses": [
                {
                    "user": {"address": recipient_addr, "chain_uid": "pharos"},
                    "limit": {"less_than_or_equal": limit_lte},
                }
            ],
            "partnerFee": {"partner_fee_bps": 10, "recipient": "0x8ed341da628fb9f540ab3a4ce4432ee9b4f5d658"},
            "sender": {"address": sender_addr, "chain_uid": "monad"},
            "swap_path": {
                "path": [
                    {
                        "route": ["mon", "euclid", "phrs"],
                        "dex": "euclid",
                        "amount_in": str(amount.Wei),
                        "amount_out": limit_lte,
                        "chain_uid": "vsl",
                        "amount_out_for_hops": ["euclid: 15969655", "phrs: 9223372036854775807"],
                    }
                ],
                "total_price_impact": "NaN",
            },
        }

        logger.debug(
            f"{self.wallet} | {self.__module_name__} | Try swap "
            f"{amount.Ether:.5f} MON -> PHRS"
        )

        # routes_resp = await self.fetch_routes(
        #     token_in="mon",
        #     token_out="phrs",
        #     amount_in=amount,
        #     chain_uids=[],
        #     external=True,
        #     limit=10,
        # )

        resp = await self.build_swap(payload)

        resp = resp.get('msgs')[0]

        to = resp.get('to')
        data = resp.get('data')
        value = resp.get('value')

        tx_params = TxParams(
            to=Web3.to_checksum_address(to),
            data=data,
            value=value
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)

        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"success | swap {amount.Ether:.5f} MON -> PHRS"

        return f"Failed | swap {amount.Ether:.5f} MON -> PHRS"
