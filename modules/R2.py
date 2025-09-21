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

R2USD_ABI = [
    {
        "type": "function",
        "name": "mint",
        "stateMutability": "nonpayable",
        "inputs": [
          {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {
                "name": "permit",
                "type": "tuple",
                "components": [
                    {"name": "value", "type": "uint256"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "v", "type": "uint8"},
                    {"name": "r", "type": "bytes32"},
                    {"name": "s", "type": "bytes32"},
                ],
            },
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "burn",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "outputs": [],
    },
]

SR2USD_ABI = [
    {
        "type": "function",
        "name": "stake",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "r2USDValue", "type": "uint256"},
            {
                "name": "permit",
                "type": "tuple",
                "components": [
                    {"name": "value", "type": "uint256"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "v", "type": "uint8"},
                    {"name": "r", "type": "bytes32"},
                    {"name": "s", "type": "bytes32"},
                ],
            },
        ],
        "outputs": [],
    }
]

USDC_R2 = RawContract(
    title="USDC(R2)",
    address="0x8bebfcbe5468f146533c182df3dfbf5ff9be00e2",
    abi=DefaultABIs.Token,
)

R2USD = RawContract(
    title="R2USD",
    address="0x4f5b54d4AF2568cefafA73bB062e5d734b55AA05",
    abi=R2USD_ABI,
)

SR2USD = RawContract(
    title="SR2USD",
    address="0xF8694d25947A0097CB2cea2Fc07b071Bdf72e1f8",
    abi=SR2USD_ABI,
)


class R2(Base):
    __module__ = 'R2'
    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet

    @staticmethod
    def _zero_permit() -> tuple[int, int, int, bytes, bytes]:
        return 0, 0, 0, b"\x00" * 32, b"\x00" * 32


    async def r2_controller(self, action: str):

        settings = Settings()

        tokens = [
            USDC_R2,
            R2USD
        ]

        balance_map = {}
        for token in tokens:
            balance = await self.client.wallet.balance(token.address)

            if balance.Ether > 0.1:
                balance_map[token.title] = balance.Ether

        if all(float(value) == 0 for value in balance_map.values()):
            return 'Failed | No balance in all tokens, try to faucet first'

        if action == 'swap':

            percent_to_swap = random.randint(
                settings.r2_swap_min,
                settings.r2_swap_max
            ) / 100

            from_token = random.choice(tokens)

            while balance_map[from_token.title] == 0:
                from_token = random.choice(tokens)

            tokens.remove(from_token)
            to_token = random.choice(tokens)

            amount = float((balance_map[from_token.title])) * percent_to_swap

            return await self._swap(
                from_token=from_token,
                to_token=to_token,
                amount=TokenAmount(
                    amount=amount,
                    decimals=await self.client.transactions.get_decimals(contract=from_token.address)
                )
            )
        if action == 'stake':

            token = R2USD
            percent_to_swap = random.randint(
                settings.r2_stake_min,
                settings.r2_stake_max
            ) / 100

            if balance_map[token.title] == 0:
                swap = await self._swap(from_token=USDC_R2, to_token=R2USD, amount=TokenAmount(
                    amount=random.randint(1, 100), decimals=6
                ))
                if 'Failed' not in swap:
                    logger.success(swap)
                    await asyncio.sleep(5)
                    balance = await self.client.wallet.balance(token.address)

                    balance_map[token.title] = balance.Ether

            amount = float((balance_map[token.title])) * percent_to_swap

            return await self._stake(
                amount = TokenAmount(
                    amount=amount,
                    decimals=6
                )
            )

    @controller_log('Swap')
    async def _swap(self, from_token, to_token, amount: TokenAmount) -> str:

        contract = await self.client.contracts.get(contract_address=R2USD)
        logger.debug(f"{self.wallet} | {self.__module__} | Trying to swap {amount} {from_token.title} to {amount} {to_token.title}")

        if from_token == USDC_R2:
            if await self.approve_interface(
                    token_address=USDC_R2.address,
                    spender=contract.address,
                    amount=None
            ):
                await asyncio.sleep(random.randint(2, 5))
            else:
                return f' can not approve'

            data = TxArgs(
                to=self.client.account.address,
                value=amount.Wei,
                permit=self._zero_permit()
            )

            data = contract.encodeABI("mint", args=data.tuple())

        else:

            data = TxArgs(
                to=self.client.account.address,
                value=amount.Wei
            )

            data = contract.encodeABI("burn", args=data.tuple())

        tx_params = TxParams(
            to=contract.address,
            data=data,
            value=0
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success | Swapped {amount} {from_token.title} to {amount} {to_token.title}"

    @controller_log('Stake R2 USD')
    async def _stake(self, amount: TokenAmount) -> str:

        contract = await self.client.contracts.get(contract_address=SR2USD)

        logger.debug(
            f"{self.wallet} | {self.__module__} | Trying to stake {amount} {R2USD.title}")

        if await self.approve_interface(
                token_address=R2USD.address,
                spender=contract.address,
                amount=None
        ):
            await asyncio.sleep(random.randint(2, 5))
        else:
            return f' can not approve'

        data = TxArgs(
            r2USDValue=amount.Wei,
            permit=self._zero_permit()
        )

        data = contract.encodeABI("stake", args=data.tuple())
        tx_params = TxParams(
            to=contract.address,
            data=data,
            value=0
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success | Staked {amount} {R2USD.title}"