import asyncio
import json
import random
import time
from typing import Optional

from loguru import logger
from web3 import Web3
from web3.types import TxParams

from data.config import ABIS_DIR
from data.models import Contracts
from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount, TxArgs
from libs.eth_async.utils.files import read_json
from libs.eth_async.utils.utils import randfloat
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log
from utils.retry import async_retry

DODO_ROUTER = RawContract(
    title="DodoRouter",
    address="0x819829e5CF6e19F9fED92F6b4CC1edF45a2cC4A2",
    abi=[],
)

NATIVE_TOKEN_ADDR = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

PHRS = RawContract(
    title="PHRS",
    address="0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
    abi=[],
)

DODO_API = "https://api.dodoex.io/route-service/v2/widget/getdodoroute"
DODO_API_KEY = "a37546505892e1a952"
DODO_SOURCE = "dodoV2AndMixWasm"


class Faroswap(Base):
    __module_name__ = "Faroswap"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = Browser(wallet=wallet)

        self.base_headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "sec-gpc": "1",
            "referer": "https://faroswap.xyz/",
        }

    @controller_log("Swap")
    async def swap_controller(self, to_native=False):
        settings = Settings()
        percent_to_swap = randfloat(from_=settings.swap_percent_from, to_=settings.swap_percent_to, step=0.001) / 100

        tokens = [
            Contracts.PHRS,
            Contracts.USDT,
            Contracts.USDC,
            Contracts.WBTC,
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
                    await self._swap(from_token=token, to_token=Contracts.WPHRS, amount=amount)
                    result = f"{amount} {token.title}: Success"
                    results.append(result)
                except Exception as e:
                    result = f"{token.title}: Failed | {e}"
                    results.append(result)

            return f"Swap all to native | {results}"

        balance_map = await self.balance_map(tokens)

        if not balance_map:
            return f"{self.wallet} | {self.__module_name__} | No balances try to faucet first"

        if all(float(value) == 0 for value in balance_map.values()):
            return "Failed | No balance in all tokens, try to faucet first"

        from_token = random.choice(list(balance_map.keys()))

        tokens.remove(from_token)
        to_token = random.choice(tokens)

        amount = float((balance_map[from_token])) * percent_to_swap

        return await self._swap(
            from_token=from_token,
            to_token=to_token,
            amount=TokenAmount(
                amount=amount,
                decimals=18 if from_token.title == "PHRS" else await self.client.transactions.get_decimals(contract=from_token.address),
            ),
        )

    @async_retry(retries=3, delay=2, to_raise=False)
    async def fetch_forecast_slippage(
        self,
        *,
        from_token: RawContract,
        to_token: RawContract,
    ) -> Optional[dict]:
        url = "https://api.dodoex.io/frontend-graphql?opname=FetchErc20ForecastSlippage"

        payload = {
            "query": """
            query FetchErc20ForecastSlippage($where: Erc20_extenderc20ExtendV2Filter) {
              erc20_extend_erc20ExtendV2(where: $where) {
                forecastSlippageList {
                  forecastSlippage
                  forecastValue
                  confidenceRatio
                  confidenceIntervalUpper
                  confidenceIntervalLower
                }
              }
            }
            """,
            "variables": {
                "where": {
                    "aToken": {"address": from_token.address, "chainId": self.client.network.chain_id},
                    "bToken": {"address": to_token.address, "chainId": self.client.network.chain_id},
                }
            },
            "operationName": "FetchErc20ForecastSlippage",
        }

        headers = {
            **self.base_headers,
            "content-type": "application/json",
            "origin": "https://faroswap.xyz",
            "referer": "https://faroswap.xyz/",
        }

        r = await self.session.post(url=url, headers=headers, json=payload, timeout=20)
        r.raise_for_status()

        try:
            data = r.json()
        except Exception:
            data = json.loads(r.text or "{}")

        node = (data or {}).get("data", {}).get("erc20_extend_erc20ExtendV2")
        if not node:
            logger.warning(f"{self.wallet} | DODO forecast: empty node")
            return None

        return node  # внутри будет forecastSlippageList

    @async_retry(retries=5, delay=2, to_raise=True)
    async def get_route(
        self,
        *,
        from_token: RawContract,
        to_token: RawContract,
        from_amount_wei: TokenAmount,
        slippage: str = 3.24,
        estimate_gas=True,
        ttl_sec: int = 600,
        timeout=120,
    ) -> dict:
        deadline = int(time.time()) + ttl_sec
        estimate_gas = "true" if estimate_gas else "false"
        params = (
            f"chainId={self.client.network.chain_id}"
            f"&deadLine={deadline}"
            f"&apikey={DODO_API_KEY}"
            f"&slippage={slippage}"
            f"&source={DODO_SOURCE}"
            f"&toTokenAddress={to_token.address}"
            f"&fromTokenAddress={from_token.address}"
            f"&userAddr={self.client.account.address}"
            f"&estimateGas={estimate_gas}"
            f"&fromAmount={from_amount_wei.Wei}"
        )
        url = f"{DODO_API}?{params}"

        r = await self.session.get(url=url, headers=self.base_headers, timeout=timeout)
        r.raise_for_status()

        data = r.json()

        if data.get("status") != -1:
            return data.get("data")

        raise Exception(f"Status not 200: {data.get('status')}.. retry")

    async def _swap(self, amount: TokenAmount, from_token: RawContract, to_token: RawContract):
        from_token_is_phrs = from_token.address.upper() == Contracts.PHRS.address.upper()
        if from_token_is_phrs:
            from_token = PHRS

        to_token_is_phrs = to_token.address.upper() == Contracts.PHRS.address.upper()
        if to_token_is_phrs:
            to_token = PHRS

        slippage = await self.fetch_forecast_slippage(from_token=from_token, to_token=to_token)

        slippage = slippage.get("forecastSlippageList")[-1].get("forecastSlippage") * 100

        route = await self.get_route(
            from_token=from_token,
            to_token=to_token,
            from_amount_wei=amount,
            slippage=slippage,
            estimate_gas=False if not from_token_is_phrs else True,
        )

        to_token_amount = TokenAmount(amount=route.get("minReturnAmount"), decimals=route.get("targetDecimals"), wei=True)

        logger.debug(
            f"{self.wallet} | {self.__module_name__} | Trying to swap {amount.Ether:.5f} {from_token.title} to "
            f"{to_token_amount} {to_token.title} with slippage {slippage}%"
        )

        if not from_token_is_phrs:
            if await self.approve_interface(token_address=from_token.address, spender=route.get("targetApproveAddr"), amount=None):
                await asyncio.sleep(random.randint(2, 5))
            else:
                return f" can not approve"

        tx_params = TxParams(to=Web3.to_checksum_address(route.get("to")), data=route.get("data"), value=int(route.get("value")))

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success swap {amount.Ether:.5f} {from_token.title} to {to_token_amount.Ether:.5f} {to_token.title}"

        return f"Failed to swap {amount.Ether:.5f} {from_token.title} to {to_token_amount.Ether:.5f} {to_token.title}"


ZENITH_SWAP_ROUTER = RawContract(
    title="FaroSwap Router", address="0x3541423f25a1ca5c98fdbcf478405d3f0aad1164", abi=read_json(path=(ABIS_DIR, "zenith_router.json"))
)

ZENITH_FACTORY = RawContract(
    title="Zebith_factory", address="0x4b177aded3b8bd1d5d747f91b9e853513838cd49", abi=read_json(path=(ABIS_DIR, "zenith_factory_v3.json"))
)

POSITION_MANAGER_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "dvmAddress", "type": "address"},
            {"internalType": "uint256", "name": "baseInAmount", "type": "uint256"},
            {"internalType": "uint256", "name": "quoteInAmount", "type": "uint256"},
            {"internalType": "uint256", "name": "baseMinAmount", "type": "uint256"},
            {"internalType": "uint256", "name": "quoteMinAmount", "type": "uint256"},
            {"internalType": "uint8", "name": "flag", "type": "uint8"},
            {"internalType": "uint256", "name": "deadLine", "type": "uint256"},
        ],
        "name": "addDVMLiquidity",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "address", "name": "fee", "type": "uint256"},
            {"internalType": "uint256", "name": "amountADesired", "type": "uint256"},
            {"internalType": "uint256", "name": "amountBDesired", "type": "uint256"},
            {"internalType": "uint256", "name": "amountAMin", "type": "uint256"},
            {"internalType": "uint256", "name": "amountBMin", "type": "uint256"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
        ],
        "name": "addLiquidity",
        "outputs": [
            {"internalType": "uint256", "name": "amountA", "type": "uint256"},
            {"internalType": "uint256", "name": "amountB", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidity", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


POSITION_MANAGER_V2 = RawContract(
    title="NonfungiblePositionManager",
    address="0xb93Cd1E38809607a00FF9CaB633db5CAA6130dD0",
    abi=POSITION_MANAGER_ABI,
)

GET_RESERVES_ABI = [
    {
        "name": "getReserves",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"name": "reserve0", "type": "uint112"},
            {"name": "reserve1", "type": "uint112"},
            {"name": "blockTimestampLast", "type": "uint32"},
        ],
    },
]


class FaroswapLiquidity(Faroswap):
    __module_name__ = "Faroswap Liquidity"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = Browser(wallet=wallet)

        self.base_headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "sec-gpc": "1",
            "referer": "https://faroswap.xyz/",
        }

    @async_retry(retries=3, delay=2)
    async def fetch_liquidity_list(
        self,
        *,
        chain_ids: list[int] | tuple[int, ...] = [688689],
        page_size: int = 8,
        current_page: int = 1,
        filter_types: list[str] | tuple[str, ...] = ("CLASSICAL", "DVM", "DSP", "GSP", "AMMV2", "AMMV3"),
        timeout: int = 20,
    ) -> dict:
        url = "https://api.dodoex.io/frontend-graphql?opname=FetchLiquidityList"

        headers = {
            **self.base_headers,
            "content-type": "application/json",
            "origin": "https://faroswap.xyz",
        }

        payload = {
            "query": """
            query FetchLiquidityList($where: Liquiditylist_filter) {
              liquidity_list(where: $where) {
                currentPage
                pageSize
                totalCount
                lqList {
                  id
                  pair {
                    id
                    chainId
                    type
                    lpFeeRate
                    mtFeeRate
                    creator
                    baseLpToken { id decimals }
                    quoteLpToken { id decimals }
                    baseToken { id symbol name decimals logoImg }
                    quoteToken { id symbol name decimals logoImg }
                    tvl
                    apy {
                      miningBaseApy
                      miningQuoteApy
                      transactionBaseApy
                      transactionQuoteApy
                      metromMiningApy
                    }
                    miningAddress
                    volume24H
                  }
                }
              }
            }
            """,
            "variables": {
                "where": {
                    "chainIds": list(chain_ids),
                    "pageSize": page_size,
                    "filterState": {
                        "viewOnlyOwn": False,
                        "filterTypes": list(filter_types),
                    },
                    "currentPage": current_page,
                }
            },
            "operationName": "FetchLiquidityList",
        }

        r = await self.session.post(url=url, json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json().get("data").get("liquidity_list").get("lqList")

    @controller_log("Add Liquidity (v2)")
    async def liquidity_controller(self):
        settings = Settings()
        percent_to_liq = randfloat(from_=settings.liquidity_percent_min, to_=settings.liquidity_percent_max, step=0.001) / 100

        tokens = [
            Contracts.USDT,
            Contracts.USDC,
        ]

        balance_map = await self.balance_map(tokens)

        if not balance_map:
            await self.swap_controller()
            return await self.liquidity_controller()
            return f"{self.wallet} | {self.__module_name__} | No balances try to faucet first"

        if all(float(value) == 0 for value in balance_map.values()):
            await self.swap_controller()
            return await self.liquidity_controller()
            return "Failed | No balance in all tokens, try to faucet first"

        from_token = random.choice(list(balance_map.keys()))

        a_amt = TokenAmount(amount=float((balance_map[from_token])) * percent_to_liq, decimals=18 if from_token.title == "PHRS" else 6)

        tokens.remove(from_token)

        to_token = random.choice(tokens)

        return await self.add_liquidity_v2(
            from_token=from_token,
            to_token=to_token,
            amount=a_amt,
        )

    @async_retry()
    async def add_liquidity_v2(self, from_token: RawContract, to_token: RawContract, amount: TokenAmount):
        pools = await self.fetch_liquidity_list(filter_types=["AMMV2"])

        pool = [
            p
            for p in pools
            if p["pair"]["baseToken"]["id"].lower() == from_token.address.lower()
            and p["pair"]["quoteToken"]["id"].lower() == to_token.address.lower()
        ][0]

        POOL = RawContract(
            title="POOL",
            address=pool["id"],
            abi=GET_RESERVES_ABI,
        )

        c = await self.client.contracts.get(contract_address=POOL)
        a = await c.functions.getReserves().call()

        reserve0, reserve1, _ = a

        if reserve0 == 0 or reserve1 == 0:
            return None

        from_token_decimals = int(pool["pair"]["baseToken"]["decimals"])
        to_token_decimals = int(pool["pair"]["quoteToken"]["decimals"])

        price0_in_1 = (reserve1 / 10**to_token_decimals) / (reserve0 / 10**from_token_decimals)

        c = await self.client.contracts.get(contract_address=POSITION_MANAGER_V2)
        to_token_amount = TokenAmount(amount=float(amount.Ether) * price0_in_1, decimals=to_token_decimals)
        deadline = int(time.time() + 20 * 60)
        to_token_balance = await self.client.wallet.balance(token=to_token)

        if to_token_balance.Ether < to_token_amount.Ether:
            await self._swap(
                from_token=from_token, to_token=to_token, amount=TokenAmount(amount=float(amount.Ether) * 1.3, decimals=from_token_decimals)
            )
            # logger.debug(swap)

            await asyncio.sleep(5)

        params = TxArgs(
            tokenA=from_token.address,
            tokenB=to_token.address,
            fee=30,
            amountADesired=amount.Wei,
            amountBDesired=to_token_amount.Wei,
            amountAMin=0,
            amountBMin=0,
            to=self.client.account.address,
            deadline=deadline,
        ).tuple()

        data = c.encode_abi("addLiquidity", args=params)
        msg = "Added LP "

        if await self.approve_interface(token_address=from_token.address, spender=c.address, amount=None):
            await asyncio.sleep(random.randint(2, 5))
        else:
            return f" can not approve"

        if await self.approve_interface(token_address=to_token.address, spender=c.address, amount=None):
            await asyncio.sleep(random.randint(2, 5))
        else:
            return f" can not approve"

        tx = await self.client.transactions.sign_and_send(TxParams(to=c.address, data=data, value=0))

        await asyncio.sleep(2)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if rcpt:
            return f"Success | {msg} | {amount} {from_token.title} <-> {to_token_amount} {to_token.title}"

        return f"Failed | {msg} | {amount} {from_token.title} <-> {to_token_amount} {to_token.title}"
