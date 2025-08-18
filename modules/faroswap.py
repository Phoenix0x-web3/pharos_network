import asyncio
import json
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from web3 import Web3, AsyncWeb3
from web3.types import TxParams

from data.models import Contracts
from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount
from libs.eth_async.utils.utils import randfloat
from libs.twitter.base import BaseAsyncSession
from utils.db_api.models import Wallet
from utils.logs_decorator import action_log, controller_log
from utils.retry import async_retry


DODO_ROUTER = RawContract(
    title="DodoRouter",
    address="0x73CAfc894dBfC181398264934f7Be4e482fc9d40",
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
        self.session = BaseAsyncSession(proxy=self.wallet.proxy)

        self.base_headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "sec-gpc": "1",
            "referer": "https://faroswap.xyz/",
        }

    @controller_log('Swap')
    async def swap_controller(self, to_native=False):
        settings = Settings()
        percent_to_swap = randfloat(
            from_=settings.swap_percent_from,
            to_=settings.swap_percent_to,
            step=0.001
        ) / 100

        tokens = [
            Contracts.PHRS,
            #Contracts.USDT,
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

        amount = float((balance_map[from_token.title])) * percent_to_swap

        return await self._swap(
            from_token=from_token,
            to_token=to_token,
            amount=TokenAmount(
                amount=amount,
                decimals=18 if from_token.title == 'PHRS' \
                    else await self.client.transactions.get_decimals(contract=from_token.address)
            )
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
            estimate_gas = True,
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
            return data.get('data')

        raise Exception(f'Status not 200: {data.get("status")}.. retry')


    async def _swap(self,
                    amount: TokenAmount,
                    from_token: RawContract,
                    to_token: RawContract):

        from_token_is_phrs = from_token.address.upper() == Contracts.PHRS.address.upper()
        if from_token_is_phrs: from_token = PHRS

        to_token_is_phrs = to_token.address.upper() == Contracts.PHRS.address.upper()
        if to_token_is_phrs: to_token = PHRS

        slippage = await self.fetch_forecast_slippage(from_token=from_token, to_token=to_token)

        slippage = slippage.get('forecastSlippageList')[-1].get('forecastSlippage') * 100

        route = await self.get_route(
            from_token=from_token,
            to_token=to_token,
            from_amount_wei=amount,
            slippage=slippage,
            estimate_gas=False if not from_token_is_phrs else True
        )

        to_token_amount = TokenAmount(
            amount=route.get('minReturnAmount'),
            decimals=route.get('targetDecimals'),
            wei=True
        )

        logger.debug(f'{self.wallet} | {self.__module_name__} | Trying to swap {amount.Ether:.5f} {from_token.title} to '
                    f'{to_token_amount} {to_token.title} with slippage {slippage}%')

        if not from_token_is_phrs:

            if await self.approve_interface(
                    token_address=from_token.address,
                    spender=route.get('targetApproveAddr'),
                    amount=None
            ):
                await asyncio.sleep(random.randint(2, 5))
            else:
                return f' can not approve'

        tx_params = TxParams(
            to=Web3.to_checksum_address(route.get('to')),
            data=route.get('data'),
            value=int(route.get('value'))
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return (f'Success swap {amount.Ether:.5f} {from_token.title} to '
                    f'{to_token_amount.Ether:.5f} {to_token.title}')


        return f'Failed to swap {amount.Ether:.5f} {from_token.title} to {to_token_amount.Ether:.5f} {to_token.title}'
