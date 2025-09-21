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

from modules.R2 import USDC_R2
from utils.browser import Browser
from utils.captcha.captcha_handler import CloudflareHandler
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
        self.headers = {
            'accept': '*/*',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/json',
            'origin': 'https://testnet.zenithswap.xyz',
            'referer': 'https://testnet.zenithswap.xyz/',
        }
        self.session = Browser(wallet=wallet)

    #todo Zenith Faucet

    @controller_log('Swap')
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

            wphrs = await self.client.wallet.balance(token=Contracts.WPHRS)

            if float(wphrs.Ether) > 0:
                result = await self.unwrap_eth(amount=wphrs)
                results.append(result)

            return f"Swap all to native | {results}"

        balance_map = await self.balance_map(tokens)

        if not balance_map:
            return f"{self.wallet} | {self.__module_name__} | No balances try to faucet first"

        if all(float(value) == 0 for value in balance_map.values()):
            return 'Failed | No balance in all tokens, try to faucet first'

        from_token = random.choice(list(balance_map.keys()))

        tokens.remove(from_token)
        to_token = random.choice(tokens)

        if from_token.address != Contracts.PHRS.address:
            amount = float((balance_map[from_token])) - float((balance_map[from_token])) * percent_to_swap
        else:
            amount = float((balance_map[from_token])) * percent_to_swap

        fee = random.choice([500, 3000])
        return await self._swap(
            from_token=from_token,
            to_token=to_token,
            amount=TokenAmount(
                amount=amount,
                decimals= 18 if from_token.title == 'PHRS' \
                    else await self.client.transactions.get_decimals(contract=from_token.address)
            ),
            fee=fee
        )

    async def swap_to_r2_usdc(self):

        settings = Settings()
        percent_to_swap = randfloat(
            from_=settings.swap_percent_from,
            to_=settings.swap_percent_to,
            step=0.001
        ) / 100
        balance = await self.client.wallet.balance()

        amount = float(balance.Ether) * percent_to_swap

        return await self._swap(
            from_token=Contracts.PHRS,
            to_token=USDC_R2,
            amount=TokenAmount(amount=amount),
            slippage=30
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
                    slippage: float = 3.0,
                    fee: int = 500):

        contract = await self.client.contracts.get(contract_address=ZENITH_SWAP_ROUTER)

        from_token_is_phrs = from_token.address.upper() == Contracts.PHRS.address.upper()
        if from_token_is_phrs: from_token = Contracts.WPHRS

        to_token_is_phrs = to_token.address.upper() == Contracts.PHRS.address.upper()
        if to_token_is_phrs: to_token = Contracts.WPHRS

        price, token0, token1, a_amt, b_amt = await self.get_price_pool(from_token, to_token, amount, fee=fee)


        if token0 == from_token:
            amount_out_min = TokenAmount(
                amount=float(amount.Ether) * price * (100 - slippage) / 100
            )
        if token1 == from_token:
            amount_out_min = TokenAmount(
                amount=float(amount.Ether) / price * (100 - slippage) / 100,
            )

        logger.debug(f'{self.wallet} | {self.__module_name__} | Trying to swap {amount.Ether:.5f} {from_token.title} to '
                    f'{amount_out_min.Ether:.5f} {to_token.title}')

        if not to_token_is_phrs:
            amount_out_min = TokenAmount(
                amount=amount_out_min.Ether,
                decimals=await self.client.transactions.get_decimals(contract=from_token.address)
            )

        data = TxArgs(
            tokenIn=from_token.address,
            tokenOut=to_token.address,
            fee=int(fee), #random.choice([500, 3000]),
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

    async def zenith_faucet_get_twitter(self):
        params = {
            'wallet': self.client.account.address
        }

        r = await self.session.get(
            url='https://testnet-router.zenithswap.xyz/api/v1/oauth2/twitter_url',
            params=params
        )

        try:
            data = r.json().get('data')
            return data
        except Exception as e:
            return f'Failed | {r.text} | {e}'

    async def zenith_faucet(self):
        site_key = '0x4AAAAAABesmP1SWw2G_ear'
        web_site = 'https://testnet.zenithswap.xyz'
        settings = Settings()

        if settings.capmonster_api_key == '':
            return 'Failed | You need to provide Capmonster Api key'

        assets = [Contracts.USDT, Contracts.USDC]

        asset: RawContract = random.choice(assets)
        cdata = f"{self.client.account.address}_{asset.address}"

        capmoster = CloudflareHandler(wallet=self.wallet)

        captcha_task = await capmoster.get_recaptcha_task_turnstile(
            websiteKey=site_key,
            websiteURL=web_site,
            cdata=cdata
        )

        turnstile_token = await capmoster.get_recaptcha_token(task_id=captcha_task)

        faucet_payload = {'CFTurnstileResponse': turnstile_token}

        r = await self.session.post(
            url='https://testnet-router.zenithswap.xyz/api/v1/faucet',
            json=faucet_payload,
            headers=self.headers

        )

        try:
            data = r.json()

            if data.get('status') == 200:

                return f'Success faucet {asset.title}'

            if data.get('status') == 400:
                return f'Failed | IP already fauceted today'

            return f'Failed'

        except Exception as e:
            return f'Failed | {e}'


FEE_MAP = {
    500: (-887270, 887270),
    3000: (-887220, 887220),
}

POSITION_MANAGER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "token0", "type": "address"},
                    {"internalType": "address", "name": "token1", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "int24", "name": "tickLower", "type": "int24"},
                    {"internalType": "int24", "name": "tickUpper", "type": "int24"},
                    {"internalType": "uint256", "name": "amount0Desired", "type": "uint256"},
                    {"internalType": "uint256", "name": "amount1Desired", "type": "uint256"},
                    {"internalType": "uint256", "name": "amount0Min", "type": "uint256"},
                    {"internalType": "uint256", "name": "amount1Min", "type": "uint256"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                ],
                "internalType": "tuple",
                "name": "",
                "type": "tuple",
            }
        ],
        "name": "mint",
        "outputs": [
            {"internalType": "uint256", "name": "tokenId", "type": "uint256"},
            {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
            {"internalType": "uint256", "name": "amount0", "type": "uint256"},
            {"internalType": "uint256", "name": "amount1", "type": "uint256"},
        ],
        "stateMutability": "payable",
        "type": "function",
    },
    {
      "inputs": [
        {
          "components": [
            { "internalType": "uint256", "name": "tokenId", "type": "uint256" },
            { "internalType": "address", "name": "recipient", "type": "address" },
            { "internalType": "uint128", "name": "amount0Requested", "type": "uint128" },
            { "internalType": "uint128", "name": "amount1Requested", "type": "uint128" }
          ],
          "internalType": "struct INonfungiblePositionManager.CollectParams",
          "name": "params",
          "type": "tuple"
        }
      ],
      "name": "collect",
      "outputs": [
        { "internalType": "uint256", "name": "amount0", "type": "uint256" },
        { "internalType": "uint256", "name": "amount1", "type": "uint256" }
      ],
      "stateMutability": "payable",
      "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "uint256", "name": "tokenId", "type": "uint256"},
                    {"internalType": "uint256", "name": "amount0Desired", "type": "uint256"},
                    {"internalType": "uint256", "name": "amount1Desired", "type": "uint256"},
                    {"internalType": "uint256", "name": "amount0Min", "type": "uint256"},
                    {"internalType": "uint256", "name": "amount1Min", "type": "uint256"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                ],
                "internalType": "tuple",
                "name": "",
                "type": "tuple",
            }
        ],
        "name": "increaseLiquidity",
        "outputs": [
            {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
            {"internalType": "uint256", "name": "amount0", "type": "uint256"},
            {"internalType": "uint256", "name": "amount1", "type": "uint256"},
        ],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "uint256", "name": "tokenId",   "type": "uint256"},
                    {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
                    {"internalType": "uint256", "name": "amount0Min","type": "uint256"},
                    {"internalType": "uint256", "name": "amount1Min","type": "uint256"},
                    {"internalType": "uint256", "name": "deadline",  "type": "uint256"},
                ],
                "internalType": "tuple",
                "name": "",
                "type": "tuple",
            }
        ],
        "name": "decreaseLiquidity",
        "outputs": [
            {"internalType": "uint256", "name": "amount0", "type": "uint256"},
            {"internalType": "uint256", "name": "amount1", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint256", "name": "index", "type": "uint256"},
        ],
        "name": "tokenOfOwnerByIndex",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "positions",
        "outputs": [
            {"internalType": "uint96", "name": "nonce", "type": "uint96"},
            {"internalType": "address", "name": "operator", "type": "address"},
            {"internalType": "address", "name": "token0", "type": "address"},
            {"internalType": "address", "name": "token1", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"},
            {"internalType": "int24", "name": "tickLower", "type": "int24"},
            {"internalType": "int24", "name": "tickUpper", "type": "int24"},
            {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
            {"internalType": "uint256", "name": "feeGrowthInside0LastX128", "type": "uint256"},
            {"internalType": "uint256", "name": "feeGrowthInside1LastX128", "type": "uint256"},
            {"internalType": "uint128", "name": "tokensOwed0", "type": "uint128"},
            {"internalType": "uint128", "name": "tokensOwed1", "type": "uint128"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "type": "function",
        "name": "multicall",
        "stateMutability": "payable",
        "inputs": [
            {"internalType": "bytes[]", "name": "data", "type": "bytes[]"},
        ],
        "outputs": [
            {"internalType": "bytes[]", "name": "results", "type": "bytes[]"},
        ],
    },
    {
        "type": "function",
        "name": "refundETH",
        "stateMutability": "payable",
        "inputs": [],
        "outputs": [],
    }
]

POSITION_MANAGER = RawContract(
    title="NonfungiblePositionManager",
    address="0xF8a1D4FF0f9b9Af7CE58E1fc1833688F3BFd6115",
    abi=POSITION_MANAGER_ABI,
)


class ZenithLiquidity(Zenith):
    __module_name__ = "Zenith Liquidity"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet

    async def _is_same_token(self, a: RawContract, b: RawContract) -> bool:
        return a.address.upper() == b.address.upper()

    @staticmethod
    async  def _order_tokens(from_token: RawContract, to_token: RawContract, a_amt: TokenAmount, b_amt: TokenAmount = None):

        if int(Web3.to_checksum_address(from_token.address), 16) <= int(Web3.to_checksum_address(to_token.address), 16):
            return from_token, to_token, a_amt, b_amt, False
        return to_token, from_token, b_amt, a_amt, True

    @controller_log("Add Liquidity (v3)")
    async def liquidity_controller(self):
        settings = Settings()

        percent_to_liq = randfloat(
            from_=settings.liquidity_percent_min,
            to_=settings.liquidity_percent_max,
            step=0.001
        ) / 100

        tokens = [
            Contracts.PHRS,
            Contracts.USDT,
            Contracts.USDC,
        ]

        fee = random.choice(list(FEE_MAP.keys()))

        balance_map = await self.balance_map(tokens)

        if not balance_map:
            return f"{self.wallet} | {self.__module_name__} | No balances try to faucet first"

        if all(float(value) == 0 for value in balance_map.values()):
            return 'Failed | No balance in all tokens, try to faucet first'

        from_token = random.choice(list(balance_map.keys()))

        a_amt = TokenAmount(amount=float((balance_map[from_token])) * percent_to_liq, decimals = 18 if from_token.title == 'PHRS' else 6)

        tokens.remove(from_token)

        to_token = random.choice(tokens)

        return await self.prepare_position(
            a_token = from_token,
            b_token= to_token,
            amount = a_amt,
            fee=fee
        )

    async def process_back_swap_from_natve(self,
                                token: RawContract,
                                amount: TokenAmount,
                                fee: int = 3000
                                 ):

        from_token = Contracts.WPHRS
        to_token = token

        balance = await self.client.wallet.balance()

        if float(balance.Ether) <= 0.0001:

            raise Exception(f'Failed | Low {balance} PHRS balance | waiting for faucet')


        price, token0, token1, _, _ = await self.get_price_pool(from_token=from_token, to_token=to_token, a_amt=amount, fee=fee)

        if to_token == token0:
            amount = TokenAmount(
                amount=(float(amount.Ether) * 1.10) * price,
            )

        if from_token == token0:
            amount = TokenAmount(
                amount=(float(amount.Ether) * 1.10) / price,
            )

        logger.debug(
            f"{self.wallet} | {self.__module_name__} | going to swap {amount} {from_token.title} to {to_token.title}")

        return await self._swap(
            amount=amount,
            from_token=Contracts.PHRS,
            to_token=token,
            fee=fee
        )

    async def prepare_position(self,
                               a_token: RawContract,
                               b_token: RawContract,
                               amount: TokenAmount,
                               fee: int = 500 ):


        from_token_is_phrs = a_token.address.upper() == Contracts.PHRS.address.upper()
        if from_token_is_phrs: a_token = Contracts.WPHRS

        to_token_is_phrs = b_token.address.upper() == Contracts.PHRS.address.upper()
        if to_token_is_phrs: b_token = Contracts.WPHRS

        price, from_token, to_token, a_amt, b_amt = await self.get_price_pool(from_token=a_token, to_token=b_token, a_amt=amount, fee=fee)

        if await self._is_same_token(a_token, from_token):
            amt0 = TokenAmount(amount=float(amount.Ether),
                               decimals=await self.client.transactions.get_decimals(contract=from_token.address))
            amt1 = TokenAmount(amount=float(amt0.Ether) * float(price),
                               decimals=await self.client.transactions.get_decimals(contract=to_token.address))
        elif await self._is_same_token(a_token, to_token):

            amt1 = TokenAmount(amount=float(amount.Ether),
                               decimals=await self.client.transactions.get_decimals(contract=to_token.address))
            amt0 = TokenAmount(amount=float(amt1.Ether) / float(price),
                               decimals=await self.client.transactions.get_decimals(contract=from_token.address))
        else:
            raise RuntimeError()


        swaps = False

        logger.debug(
            f"{self.wallet} | {self.__module_name__} | prepare LP {fee} | {amt0} {from_token.title} <-> {amt1} {to_token.title}")

        from_token_is_phrs = from_token.address.upper() == Contracts.WPHRS.address.upper()
        to_token_is_phrs = to_token.address.upper() == Contracts.WPHRS.address.upper()

        if not from_token_is_phrs:
            from_token_balance = await self.client.wallet.balance(token=from_token)
            if float(from_token_balance.Ether) < float(amt0.Ether):
                logger.warning(
                    f"{self.wallet} | {self.__module_name__} | Not enought {amt0} {from_token.title} balance {from_token_balance}, trying to swap from native")

                swap = await self.process_back_swap_from_natve(token=from_token, amount=amt0, fee=fee)
                logger.debug(swap)

                swaps = True

        if not to_token_is_phrs:
            to_token_balance = await self.client.wallet.balance(token=to_token)
            if float(to_token_balance.Ether) < float(amt1.Ether):
                logger.warning(
                    f"{self.wallet} | {self.__module_name__} | Not enought {amt1} {to_token.title} balance {to_token_balance}, trying to swap from native")
                swap = await self.process_back_swap_from_natve(token=to_token, amount=amt1, fee=fee)
                logger.debug(swap)
                swaps = True

        if swaps:
            await asyncio.sleep(random.randint(3, 7))
            return await self.prepare_position(a_token=a_token, b_token=b_token, amount=amount, fee=fee)

        return await self.add_liquidity(
            from_token=from_token,
            to_token=to_token,
            a_amt=amt0,
            b_amt=amt1,
            fee=fee
        )

    async def get_current_position(self):
        c = await self.client.contracts.get(contract_address=POSITION_MANAGER)
        num = await c.functions.balanceOf(self.client.account.address).call()

        positions_map = {
            500: [],
            1000: [],
            3000: [],
        }

        for i in range(num):
            token_id = await c.functions.tokenOfOwnerByIndex(self.client.account.address, i).call()
            positions = await c.functions.positions(token_id).call()
            fee = positions[4]

            positions_map.setdefault(fee, []).append({
                "token_id": token_id,
                "from_token": positions[2],
                "to_token": positions[3],
                "tickLower": positions[5],
                "tickUpper": positions[6],
                "liquidity": positions[7],
                "from_token_amount": positions[10],
                "to_token_amount": positions[11],
            })

        return positions_map

    async def add_liquidity(
        self,
        from_token: RawContract,
        to_token: RawContract,
        a_amt: TokenAmount,
        b_amt: TokenAmount,
        fee: int = 3000,
        slippage: int = 10,
    ) -> str:

        c = await self.client.contracts.get(contract_address=POSITION_MANAGER)

        if slippage:
            a_amt_min = TokenAmount(amount=float(a_amt.Ether) * (100 - slippage) / 100,
                                     decimals=a_amt.decimals)
            b_amt_min = TokenAmount(amount=float(b_amt.Ether) * (100 - slippage) / 100,
                                     decimals=b_amt.decimals)
        else:
            a_amt_min = 0
            b_amt_min = 0

        logger.debug(f"{self.wallet} | {self.__module_name__} | add LP {fee} | {a_amt} {from_token.title}, min {a_amt_min} "
                     f"-- {b_amt} {to_token.title}, min {b_amt_min}")

        for token, amt in ((from_token, a_amt), (to_token, b_amt)):
            if token != Contracts.WPHRS:
                ok = await self.approve_interface(
                    token_address=token.address,
                    spender=c.address,
                    amount=None
                )
                if not ok:
                    return f"Failed | approve {token.title}"

                await asyncio.sleep(1)


        tickLower, tickUpper = FEE_MAP[fee]
        deadline = int(time.time() + 20 * 60)

        current_positions = await self.get_current_position()

        current_position = current_positions[fee]

        current_position = [cur for cur in current_position if cur.get('from_token') == from_token.address and cur.get('to_token') == to_token.address]

        if current_position:
            current_position = current_position[0]

            params = TxArgs(
                tokenId=int(current_position.get('token_id')),
                amount0Desired=a_amt.Wei,
                amount1Desired=b_amt.Wei,
                amount0Min=a_amt_min.Wei,
                amount1Min=b_amt_min.Wei,
                deadline=deadline).tuple()
            data = c.encode_abi("increaseLiquidity", args=[params])
            msg = 'Increases LP'

        else:
            params = TxArgs(
                token0=from_token.address,
                token1=to_token.address,
                fee=fee,
                tickLower=tickLower,
                tickUpper=tickUpper,
                amount0Desired=a_amt.Wei,
                amount1Desired=b_amt.Wei,
                amount0Min=a_amt_min.Wei,
                amount1Min=b_amt_min.Wei,
                recipient=self.client.account.address,
                deadline=deadline,
            ).tuple()

            data = c.encode_abi("mint", args=[params])
            msg = 'Minted LP'

        value = TokenAmount(amount=0)
        if from_token == Contracts.WPHRS:
            second_item = c.encode_abi('refundETH', args=[])
            data = c.encode_abi('multicall', args=[[data, second_item]])
            value = a_amt

        elif to_token == Contracts.WPHRS:
            second_item = c.encode_abi('refundETH', args=[])
            data = c.encode_abi('multicall', args=[[data, second_item]])
            value = b_amt


        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=value.Wei
        ))

        await asyncio.sleep(2)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if rcpt:
            return (f"Success | {msg} | {a_amt} {from_token.title} <-> {b_amt} {to_token.title} - fee {fee}")


        return f"Failed | {msg}"

    async def check_any_positions(self):
        current_positions = await self.get_current_position()
        res = []
        for key, positions in current_positions.items():
            if positions:
                res.extend([pos for pos in positions if pos.get('liquidity') > 0])
        return res

    @controller_log('Remove Liquidity')
    async def remove_liquidity(self):
        current_positions = await self.get_current_position()

        for key, positions in current_positions.items():
            if positions:
                positions = [pos for pos in positions if pos.get('liquidity') > 0]

                if positions:
                    pos = random.choice(positions)

                    return await self.descrease_liquidity(pos=pos)

        return 'Nothing to close | All positions are closed'


    async def descrease_liquidity(self, pos, slippage = 3):
        c = await self.client.contracts.get(contract_address=POSITION_MANAGER)

        deadline = int(time.time() + 20 * 60)

        token_id = int(pos.get('token_id'))
        liquidity = int(pos.get('liquidity'))

        amount0Min = int(pos.get('from_token_amount')) * (100 - slippage) // 100
        amount1Min = int(pos.get('to_token_amount')) * (100 - slippage) // 100

        msg = f'Decreased LP | TokenId {token_id}'

        descrease = TxArgs(
            tokenId=token_id,
            liquidity=liquidity,
            amount0Min=amount0Min,
            amount1Min=amount1Min,
            deadline=deadline
        ).tuple()

        descrease = c.encode_abi("decreaseLiquidity", args=[descrease])

        max_uint128 = 2 ** 128 - 1

        collect = TxArgs(
            tokenId = token_id,
            recipient= self.client.account.address,
            amount0Requested= max_uint128,
            amount1Requested= max_uint128
        ).tuple()

        collect = c.encode_abi("collect", args=[collect])

        data = c.encode_abi("multicall", args=[[descrease, collect]])

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=0
        ))

        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if rcpt:
            return (
                f"Success | {msg}")

        return f"Failed | {msg}"
