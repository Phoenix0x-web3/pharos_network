from __future__ import annotations

import asyncio
import random

from loguru import logger
from web3.types import TxParams

from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import DefaultABIs, RawContract, TokenAmount, TxArgs
from libs.eth_async.utils.utils import randfloat
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.retry import async_retry
from utils.logs_decorator import controller_log



MINT_ABI = [
    {"type": "function", "name": "freeMint", "stateMutability": "nonpayable", "inputs": [], "outputs": []},
    {"type": "function", "name": "claimWearable", "stateMutability": "nonpayable", "inputs": [], "outputs": []},
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    }
    ,

]
GOTCHIPUS_FREE = RawContract(
            title='GOTCHIPUS_FREE',
            address='0x0000000038f050528452D6Da1E7AACFA7B3Ec0a8',
            abi=MINT_ABI
        )
class Gotchipus(Base):
    __module__ = "Gotchipus"

    BASE_API = "https://gotchipus.com"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = Browser(wallet=wallet)

    async def check_gotchipus_free_ntf(self):
        c = await self.client.contracts.get(contract_address=GOTCHIPUS_FREE)

        return await c.functions.balanceOf(self.client.account.address).call()

    @controller_log('Mint Free NFT')
    async def mint_gotchipus(self):


        c = await self.client.contracts.get(contract_address=GOTCHIPUS_FREE)


        logger.debug(
            f"{self.wallet} | {self.__module__} | trying to mint Gotchipus")

        data = c.encodeABI('freeMint', args=[])

        tx_params = TxParams(
            to=c.address,
            data=data,
            value=0
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success | Minted Gotchipus"

        return f'Failed | | Minted Gotchipus'

