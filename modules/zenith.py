import asyncio
import random

from loguru import logger
from web3 import Web3
from web3.types import TxParams

from data.config import ABIS_DIR
from data.models import Contracts
from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import TokenAmount, TxArgs, RawContract, Networks
from libs.eth_async.utils.files import read_json
from libs.eth_async.utils.utils import randfloat

import time

from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log, action_log

ZENITH_SWAP_ROUTER = RawContract(
    title='Zenith_router',
    address='0x1a4de519154ae51200b0ad7c90f7fac75547888a',
    abi=read_json(path=(ABIS_DIR, 'zenith_router.json'))
)

ZENITH_FACTORY = RawContract(
    title='Zebith_factory',
    address='0x7CE5b44F2d05babd29caE68557F52ab051265F01',
    abi=read_json(path=(ABIS_DIR, 'zenith_factory_v3.json'))
)

class Zenith(Base):
    __module_name__ = "Zenith"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet

    #todo Zenith Faucet

    @action_log('Swap')
    async def swaps_controller(self, to_native=False):

        settings = Settings()
        percent_to_swap = randfloat(
            from_=settings.swap_percent_from,
            to_=settings.swap_percent_to,
            step=0.001
        ) / 100

        tokens = [
            Contracts.PHRS,
            Contracts.USDT,
            Contracts.USDC,
        ]

        if to_native:
            results = []


            for token in tokens:
                try:
                    if token == Contracts.PHRS:
                        continue

                    amount = await self.client.wallet.balance(token=token)

                    if amount.Ether == 0:
                        continue

                    swap = await self._swap(from_token=token, to_token=Contracts.WPHRS, amount=amount)
                    result = f"{amount} {token.title}: Success"

                    results.append(result)
                except Exception as e:
                    result = f"{token.title}: Failed | {e}"
                    results.append(result)

            return f"Swap all to native | {results}"


        balance_map = {}
        for token in tokens:
            if token == Contracts.PHRS:
                balance = await self.client.wallet.balance()
                if balance.Ether == 0:
                    return 'Failed | No balance, try to faucet first'
            else:
                balance = await self.client.wallet.balance(token.address)

            balance_map[token.title] = balance.Ether

        if all(float(value) == 0 for value in balance_map.values()):
            return 'Failed | No balance in all tokens, try to faucet first'

        from_token = random.choice(tokens)
        while balance_map[from_token.title] == 0:
            from_token = random.choice(tokens)

        to_token = random.choice(tokens)

        while to_token == from_token:
            to_token = random.choice(tokens)

        if from_token.address != Contracts.PHRS.address:
            amount = float((balance_map[from_token.title])) - (float((balance_map[from_token.title])) * percent_to_swap)
        else:
            amount = float((balance_map[from_token.title])) * percent_to_swap

        return await self._swap(
            from_token=from_token,
            to_token=to_token,
            amount=TokenAmount(
                amount=amount,
                decimals= 18 if from_token.title == 'PHRS' \
                    else await self.client.transactions.get_decimals(contract=from_token.address)
            )
        )

    async def correct_tokens_position(self,
                                      from_token: RawContract,
                                      to_token: RawContract,
                                      a_amt: TokenAmount,
                                      b_amt: TokenAmount = None):

        uint160_token0 = int(Web3.to_checksum_address(from_token.address), 16)
        uint160_token1 = int(Web3.to_checksum_address(to_token.address), 16)

        if uint160_token0 > uint160_token1:
            return to_token, from_token, b_amt, a_amt
            token0, token1 = to_token, from_token
        else:
            return from_token, to_token, a_amt, b_amt

            token0, token1 = from_token, to_token

        return token0, token1

    async def get_pool_address(self, from_token: RawContract, to_token: RawContract, fee: int = 500):

        contract_pool = await self.client.contracts.get(contract_address=ZENITH_FACTORY)

        data = TxArgs(
            tokenA=from_token.address,
            tokenB=to_token.address,
            fee=fee
        ).tuple()

        try:
            pool_address = await contract_pool.functions.getPool(*data).call()
            if pool_address == '0x0000000000000000000000000000000000000000':
                return None
            else:
                return RawContract(
                    title='POOL',
                    address=pool_address,
                    abi=read_json(path=(ABIS_DIR, 'zenith_v3_pool.json'))
                )
        except Exception as e:
            logger.exception(e)
            return None

    async def get_price_pool(self,
                             from_token: RawContract,
                             to_token: RawContract,
                             a_amt: TokenAmount,
                             b_amt: TokenAmount = None,
                             fee: int = 500):

        from_token, to_token, a_amt, b_amt = await self.correct_tokens_position(
            from_token=from_token,
            to_token=to_token,
            a_amt=a_amt,
            b_amt=b_amt)

        pool_contract = await self.get_pool_address(from_token=from_token, to_token=to_token, fee=fee)

        pool = await self.client.contracts.get(contract_address=pool_contract)
        slot0 = await pool.functions.slot0().call()

        liquidity = await pool.functions.liquidity().call()

        sqrt_price = slot0[0]
        current_tick = slot0[1]

        from_token_decimals = await self.client.transactions.get_decimals(contract=from_token.address)
        to_token_decimals = await self.client.transactions.get_decimals(contract=to_token.address)

        price_raw = (sqrt_price / 2 ** 96) ** 2
        price = price_raw * 10 ** (from_token_decimals - to_token_decimals)


        return price, from_token, to_token, a_amt, b_amt

    async def _swap(self,
                    amount: TokenAmount,
                    from_token: RawContract,
                    to_token: RawContract,
                    slippage: float = 3.0):

        contract = await self.client.contracts.get(contract_address=ZENITH_SWAP_ROUTER)

        from_token_is_phrs = from_token.address.upper() == Contracts.PHRS.address.upper()
        if from_token_is_phrs: from_token = Contracts.WPHRS

        to_token_is_phrs = to_token.address.upper() == Contracts.PHRS.address.upper()
        if to_token_is_phrs: to_token = Contracts.WPHRS

        price, token0, token1, a_amt, b_amt = await self.get_price_pool(from_token, to_token, amount)

        if token0 == from_token:
            amount_out_min = TokenAmount(
                amount=float(amount.Ether) * price * (100 - slippage) / 100
            )
        if token1 == from_token:
            amount_out_min = TokenAmount(
                amount=float(amount.Ether) / price * (100 - slippage) / 100,
            )

        logger.debug(f'{self.wallet} | Trying to swap {amount.Ether:.5f} {from_token.title} to '
                    f'{amount_out_min.Ether:.5f} {to_token.title}')

        if not to_token_is_phrs:
            amount_out_min = TokenAmount(
                amount=amount_out_min.Ether,
                decimals=await self.client.transactions.get_decimals(contract=from_token.address)
            )

        data = TxArgs(
            tokenIn=from_token.address,
            tokenOut=to_token.address,
            fee=3000, #3000 if from_token_is_phrs else 500,
            recepient=self.client.account.address if not to_token_is_phrs else '0x0000000000000000000000000000000000000002',
            amountIn=amount.Wei,
            amountOutMinimum=0 if from_token_is_phrs else amount_out_min.Wei,
            sqrtPriceLimitX96=0
        ).tuple()

        encode = contract.encode_abi("exactInputSingle", args=[data])

        deadline = int(time.time() + 20 * 60)

        if from_token_is_phrs:
            second_item = contract.encode_abi('refundETH', args=[])
        elif to_token_is_phrs:
            second_item = contract.encode_abi('unwrapWETH9', args=[
                amount_out_min.Wei,
                self.client.account.address
            ])
        else:
            second_item = None

        encode = contract.encode_abi('multicall', args=[deadline,
            [item for item in [encode, second_item] if item is not None]
        ])

        if not from_token_is_phrs:
            if await self.approve_interface(
                    token_address=from_token.address,
                    spender=contract.address,
                    amount=None
            ):
                await asyncio.sleep(2)
            else:
                return f' can not approve'

        tx_params = TxParams(
            to=contract.address,
            data=encode,
            value=amount.Wei if from_token_is_phrs else 0
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if receipt:
            return (f'Success swap {amount.Ether:.5f} {from_token.title} to '
                    f'{amount_out_min.Ether:.5f} {to_token.title}')


        return f'Failed to swap {amount.Ether:.5f} {from_token.title} to {amount_out_min.Ether:.5f} {to_token.title}'