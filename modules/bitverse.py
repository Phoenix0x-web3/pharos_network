import asyncio
import base64
import json
import random
import time
from tokenize import blank_re
from typing import Any, Dict, Optional, Tuple, List

from loguru import logger
from web3 import Web3
from web3.types import TxParams

from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount, DefaultABIs, TxArgs
from libs.eth_async.utils.utils import randfloat
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log
from utils.retry import async_retry
from utils.browser import Browser


BASE_API = "https://api.bitverse.zone/bitverse"

USDT = RawContract(
    title="USDT",
    address="0xD4071393f8716661958F766DF660033b3d35fD29",
    abi=DefaultABIs.Token,
)

ROUTER_IO_ABI = [
    {"type": "function", "name": "deposit", "stateMutability": "nonpayable",
     "inputs": [{"name": "token", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": []},
    {"type": "function", "name": "withdraw", "stateMutability": "nonpayable",
     "inputs": [{"name": "token", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": []},
]

POSITION_ROUTER = RawContract(
    title="PositionRouter",
    address="0xA307cE75Bc6eF22794410D783e5D4265dEd1A24f",
    abi=ROUTER_IO_ABI,
)

BITVERSE_TRADE_ABI = [{
    "type": "function", "name": "placeOrder", "stateMutability": "nonpayable",
    "inputs": [
        {"type": "string",  "name": "pairId"},
        {"type": "uint256", "name": "price"},
        {"type": "uint8",   "name": "orderType"},
        {"type": "uint64",  "name": "leverageE2"},
        {"type": "uint8",   "name": "side"},
        {"type": "uint64",  "name": "slippageE6"},
        {"type": "tuple[]", "name": "margins", "components": [
            {"type": "address", "name": "token"},
            {"type": "uint256", "name": "amount"}
        ]},
        {"type": "uint256", "name": "takeProfitPrice"},
        {"type": "uint256", "name": "stopLossPrice"},
        {"type": "uint256", "name": "positionLongOI"},
        {"type": "uint256", "name": "positionShortOI"},
        {"type": "uint256", "name": "timestamp"},
        {"type": "bytes",   "name": "signature"},
        {"type": "bool",    "name": "isExecuteImmediately"}
    ],
    "outputs": []
},
    {
        "name": "closePosition",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"internalType": "string", "name": "positionId", "type": "string"},
            {"internalType": "uint256", "name": "closeQty", "type": "uint256"},
            {
                "internalType": "struct Types.FundingFee",
                "name": "fundingFee",
                "type": "tuple",
                "components": [
                    {
                        "internalType": "struct Types.FundingFeeItem[]",
                        "name": "items",
                        "type": "tuple[]",
                        "components": [
                            {"internalType": "address", "name": "token", "type": "address"},
                            {"internalType": "int256", "name": "amount", "type": "int256"}
                        ]
                    }
                ]
            },
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
            {"internalType": "bytes", "name": "signature", "type": "bytes"}
        ],
        "outputs": []
    },
    {
        "name": "placeLimitCloseOrder",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"internalType": "string", "name": "positionId", "type": "string"},
            {"internalType": "uint256", "name": "closeSize", "type": "uint256"},
            {"internalType": "uint256", "name": "price", "type": "uint256"},
            {"internalType": "uint256", "name": "priceScale", "type": "uint256"},
            {
                "internalType": "struct Types.FundingFee",
                "name": "fundingFee",
                "type": "tuple",
                "components": [
                    {
                        "internalType": "struct Types.FundingFeeItem[]",
                        "name": "items",
                        "type": "tuple[]",
                        "components": [
                            {"internalType": "address", "name": "token", "type": "address"},
                            {"internalType": "int256", "name": "amount", "type": "int256"}
                        ]
                    }
                ]
            },
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
            {"internalType": "bytes", "name": "signature", "type": "bytes"}
        ],
        "outputs": []
    },
]

TRADE_ROUTER = RawContract(
    title="TradeRouter",
    address="0xbf428011d76eFbfaEE35a20dD6a0cA589B539c54",
    abi=BITVERSE_TRADE_ABI,
)

CLOSE_TRADE_ROUTER = RawContract(
    title="ClosePositionRouter",
    address="0x37769421b882845dc80b54d8Be62D34836f59c8b",
    abi=BITVERSE_TRADE_ABI,
)

TRADE_PROVIDER = "bvx17w0adeg64ky0daxwd2ugyuneellmjgnx53lm9l"  # адрес провайдера из API


class Bitverse(Base):
    __module_name__ = "Bitverse"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = Browser(wallet=wallet)
        self.base_headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Chain-Id": str(self.client.network.chain_id),
            "Origin": "https://testnet.bitverse.zone",
            "Referer": "https://testnet.bitverse.zone/",
            "Tenant-Id": "PHAROS",
        }

    @async_retry()
    async def _get_market_price(self, symbol: str) -> Optional[float]:
        r = await self.session.get(
            url=f"{BASE_API}/quote-all-in-one/v1/public/market/ticker?symbol={symbol}",
            headers=self.base_headers,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("retCode") == 0:
            return float(data["result"]["lastPrice"])
        return None

    @async_retry(delay=5)
    async def get_all_balance(self) -> Optional[list]:
        payload = {"address": self.client.account.address}
        r = await self.session.post(
            url=f"{BASE_API}/trade-data/v1/account/balance/allCoinBalance",
            headers=self.base_headers,
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("retCode") == 0:
            return data["result"]["coinBalance"]

        raise Exception(f"Can't get balances from Bitverse API | {r.text}")

    @async_retry()
    async def _get_all_positions(self) -> Optional[list]:
        payload = {"address": self.client.account.address}

        r = await self.session.post(
            url=f"{BASE_API}/trade-data/v1/position/query/activityPositionPage",
            headers=self.base_headers,
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("retCode") == 0:
            return data["result"]['position']

    @async_retry()
    async def _close_simulation(self, payload: dict) -> Optional[dict]:
        r = await self.session.post(
            url=f"{BASE_API}/trade-data/v1/position/simulation/closePositionV1",
            headers=self.base_headers,
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()


    def _order_payload(self, pair: str, price: TokenAmount, side: int, amount: TokenAmount, leverage: int = None) -> dict:
        return {
            "address": TRADE_PROVIDER,
            "allowedSlippage": "10",
            "isV2": "0",
            "leverageE2": random.randint(1, 10) * 100 if not leverage else leverage,
            "margin": [{"denom": "USDT", "amount": str(amount.Ether)}],
            "orderType": 1,
            "pair": pair,
            "price": str(price.Ether),
            "side": side,
        }

    @async_retry()
    async def _order_simulation(self, payload: dict) -> Optional[dict]:
        r = await self.session.post(
            url=f"{BASE_API}/trade-data/v1//order/simulation/pendingOrder",
            headers=self.base_headers,
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    async def _send(self, to: str, data: str, value: int = 0) -> Optional[str]:
        tx = await self.client.transactions.sign_and_send(TxParams(
            to=Web3.to_checksum_address(to),
            data=data,
            value=value,
        ))
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=600)
        if receipt:
            return tx.hash.hex() if hasattr(tx.hash, "hex") else str(tx.hash)

    @controller_log("Deposit")
    async def deposit(self, token: RawContract, amount: TokenAmount) -> str:
        logger.debug(
            f"{self.wallet} | {self.__module_name__} | Trying to deposit {amount} {token.title}")

        c = await self.client.contracts.get(contract_address=POSITION_ROUTER)

        amount = TokenAmount(amount=amount.Ether,
                             decimals=await self.client.transactions.get_decimals(contract=token.address))

        data = c.encode_abi("deposit", args=[Web3.to_checksum_address(token.address), amount.Wei])

        if await self.approve_interface(
                token_address=token.address,
                spender=c.address,
                amount=None
        ):
            await asyncio.sleep(2)
        else:
            return f' can not approve'

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=0,
        ))

        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Deposit {amount} {token.title}"

        return Exception(f"Failed to deposit {amount} {token.title}")

    @controller_log("Withdraw")
    async def withdraw(self, token: RawContract, amount: TokenAmount) -> str:
        c = await self.client.contracts.get(contract_address=POSITION_ROUTER)
        amount = TokenAmount(amount=amount.Ether,
                             decimals=await self.client.transactions.get_decimals(contract=token.address))

        data = c.encode_abi("withdraw", args=[Web3.to_checksum_address(token.address), amount.Wei])

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=0,
        ))

        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if receipt:
            return f"Withdraw {amount} {token.title}"

        raise Exception(f"Failed to withdraw {amount} {token.title}")

    @controller_log("Trade")
    async def place_order(self, pair: str, side: int, amount: TokenAmount, leverage: int = None) -> str:

        logger.debug(f"{self.wallet} | {self.__module_name__} | Trying to open {'LONG' if side==0 else 'SHORT'} position {pair} with {amount.Ether:.0f} USD")
        price = await self._get_market_price(pair)

        if price is None:
            return f"{self.wallet} | {self.__module_name__} | Failed | price unavailable"

        price = TokenAmount(amount=price, decimals=6)

        sim_payload = self._order_payload(pair, price, side, amount, leverage)

        sim = await self._order_simulation(sim_payload)

        #print(json.dumps(sim, indent=4))

        if not sim or sim.get("retCode") != 0:
            return f"{self.wallet} | {self.__module_name__} | Failed | simulation error"

        res = sim["result"]

        c = await self.client.contracts.get(contract_address=TRADE_ROUTER)

        signature = bytes.fromhex(res["sign"][2:])

        args = TxArgs(
            pairId=res["pair"],
            price=price.Wei,
            orderType=1,
            leverageE2=int(res["leverageE2"]),
            side=int(res["side"]),
            slippageE6=int(res["allowedSlippage"]) * 10000,
            margins=[(Web3.to_checksum_address(USDT.address), amount.Wei)],
            takeProfitPrice=0,
            stopLossPrice=0,
            positionLongOI=int(res["longOI"]),
            positionShortOI=int(res["shortOI"]),
            timestamp=int(res["signTimestamp"]),
            signature=signature,
            isExecuteImmediately=bool(res["marketOpening"])
        )


        data = c.encode_abi("placeOrder", args=args.tuple())

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=0,
        ))

        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if receipt:
            return f"Success Opened {'LONG' if side==0 else 'SHORT'} position {pair} with {amount.Ether:.0f} USD"

        raise Exception(f"Failed Open Position {pair} {'LONG' if side==0 else 'SHORT'}")


    @controller_log('Close Trade')
    async def close_position(self, position: dict):
        pair = position['symbol']
        payload = {
            "address": 'yymm1tnw7ykuee3jcja4wpspxlampp3qadmhy3hdza0',
            "positionUniqueId": position['positionUniqueId'],
            "isV2": "0",
            "orderType": "2",
            "price": "0",
            "size": position['size'],
        }

        close = await self._close_simulation(payload=payload)

        res = close["result"]
        decimals = res['sizeScale']

        close_qty = TokenAmount(amount=position['size'], decimals=decimals)

        fee_items = []
        items = res.get("item", [])

        for it in items or []:
            token = Web3.to_checksum_address(it["token"])
            amount = it.get("amount", 0)
            fee_items.append((token, int(amount)))

        funding_fee_tuple = (fee_items,)

        signature_hex = res.get("fundingFeeSign", "0x")
        signature = bytes.fromhex(signature_hex[2:]) if signature_hex.startswith("0x") else b""

        args = TxArgs(
            positionId=res['positionUniqueId'],
            closeQty=close_qty.Wei,
            fundingFee=funding_fee_tuple,
            timestamp=int(res["fundingFeeSignTimestamp"]),
            signature=signature,
        )

        c = await self.client.contracts.get(contract_address=CLOSE_TRADE_ROUTER)
        data = c.encode_abi("closePosition", args=args.tuple())

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=0,
        ))
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Position Closed {pair} "

        raise Exception(f"Failed | Close Position {pair}")

    async def deposit_usdt(self, amount: TokenAmount ):

        return await self.deposit(USDT, amount)

    async def bitverse_controller(self, percent: float) -> str:

        TRADE_PAIRS = [
            'BTC-USD',
            'ETH-USD',
            'GLXY-USD',
            'NVDA-USD',
            'BTBT-USD',
            'TSLA-USD',
            'BMNR-USD',
            'CRCL-USD',
            'RIOT-USD',
            'BTCS-USD',
            'BLSH-USD',
        ]

        balance = await self.get_all_balance()
        leverage = None

        balance = float(balance[0]['availableBalanceSize'])

        amount = TokenAmount(
            amount=int(balance * percent), decimals=6)

        pair = random.choice(TRADE_PAIRS)
        side = random.choice([0, 1])

        positions = await self._get_all_positions()
        if positions:
            current_positions = [position for position in positions if position['symbol'] == pair]
            if current_positions:
                close_position = await self.close_position(current_positions[0])
                logger.success(close_position)
                await asyncio.sleep(20, 30)

                return await self.bitverse_controller(percent=percent)

            close_position = await self.close_position(positions[0])
            logger.success(close_position)
            await asyncio.sleep(20, 30)

        return await self.place_order(pair=pair, side=side, amount=amount, leverage=leverage)


        if do_withdraw:
            r = await self.withdraw(USDT, TokenAmount(amount=1, decimals=6))
            logger.info(r)

        return f"{self.wallet} | {self.__module_name__} | Flow done"
