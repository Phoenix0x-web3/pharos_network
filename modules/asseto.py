import asyncio
import random

from loguru import logger
from web3 import Web3
from web3.types import TxParams

from data.config import ABIS_DIR
from data.models import Contracts
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount
from libs.eth_async.utils.files import read_json
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log

STAKE_CONTRACT = RawContract(
    title="STAKE_CONTRACT",
    address="0x56f4add11d723412D27A9e9433315401B351d6E3",
    abi=read_json((ABIS_DIR, "asseto.json")),
)


class Asseto(Base):
    __module_name__ = "Asseto Finance"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet

    async def check_cash_balance(self):
        c = await self.client.contracts.get(contract_address=STAKE_CONTRACT)
        return await c.functions.balanceOf(self.client.account.address).call()

    @controller_log("Unstake")
    async def unstake(self, amount: TokenAmount):
        logger.debug(f"{self.wallet} | {self.__module_name__} | Trying to unstake {amount} USDT")
        token = Contracts.USDT

        c = await self.client.contracts.get(contract_address=STAKE_CONTRACT)

        data = c.encode_abi("redemption", args=[Web3.to_checksum_address(token.address), amount.Wei])

        tx = await self.client.transactions.sign_and_send(
            TxParams(
                to=c.address,
                data=data,
                value=0,
            )
        )

        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt and receipt["status"] == 1:
            return f"Success UnStake {amount} {token.title}"

        return Exception(f"Failed to UnStake {amount} {token.title}")

    @controller_log("Stake")
    async def stake(
        self,
        amount: TokenAmount,
    ):
        logger.debug(f"{self.wallet} | {self.__module_name__} | Trying to stake {amount} USDT")
        token = Contracts.USDT

        c = await self.client.contracts.get(contract_address=STAKE_CONTRACT)

        amount = TokenAmount(amount=amount.Ether, decimals=await self.client.transactions.get_decimals(contract=token.address))

        data = c.encode_abi("subscribe", args=[Web3.to_checksum_address(token.address), amount.Wei])

        if await self.approve_interface(token_address=token.address, spender=c.address, amount=None):
            await asyncio.sleep(2)
        else:
            return f" can not approve"

        tx = await self.client.transactions.sign_and_send(
            TxParams(
                to=c.address,
                data=data,
                value=0,
            )
        )

        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt and receipt["status"] == 1:
            return f"Success Stake {amount} {token.title}"

        return Exception(f"Failed to Stake {amount} {token.title}")
