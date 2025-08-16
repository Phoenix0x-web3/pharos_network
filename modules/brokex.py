import asyncio
import json
import random
from typing import Any, Dict, List, Optional

from loguru import logger
from web3 import Web3
from web3.types import TxParams

from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, DefaultABIs, TokenAmount
from libs.twitter.base import BaseAsyncSession
from utils.db_api.models import Wallet
from utils.logs_decorator import action_log, controller_log
from utils.retry import async_retry


PHRS = RawContract(
    title="PHRS_NATIVE",
    address="0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
    abi=[],
)

USDT = RawContract(
    title="USDT",
    address="0x78ac5e2d8a78a8b8e6d10c7b7274b03c10c91cef",
    abi=DefaultABIs.Token,
)

FAUCET_ROUTER = RawContract(
    title="FaucetRouter",
    address="0x50576285BD33261DEe1aD99BF766CD8249520a58",
    abi=[
        {"type": "function", "name": "hasClaimed", "stateMutability": "view",
         "inputs": [{"name": "", "type": "address"}], "outputs": [{"name": "", "type": "bool"}]},
        {"type": "function", "name": "claim", "stateMutability": "nonpayable",
         "inputs": [], "outputs": []},
    ],
)

BROKEX_ABI = [
    {
        "name": "openPosition",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "idx", "type": "uint256"},
            {"name": "proof", "type": "bytes"},
            {"name": "isLong", "type": "bool"},
            {"name": "lev", "type": "uint256"},
            {"name": "size", "type": "uint256"},
            {"name": "sl", "type": "uint256"},
            {"name": "tp", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "getUserOpenIds",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "user", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256[]"}],
    },
    {
        "name": "getOpenById",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "id", "type": "uint256"}],
        "outputs": [{
            "name": "", "type": "tuple", "components": [
                {"name": "trader", "type": "address"},
                {"name": "id", "type": "uint256"},
                {"name": "assetIndex", "type": "uint256"},
                {"name": "isLong", "type": "bool"},
                {"name": "leverage", "type": "uint256"},
                {"name": "openPrice", "type": "uint256"},
                {"name": "sizeUsd", "type": "uint256"},
                {"name": "timestamp", "type": "uint256"},
                {"name": "stopLossPrice", "type": "uint256"},
                {"name": "takeProfitPrice", "type": "uint256"},
                {"name": "liquidationPrice", "type": "uint256"},
            ]
        }],
    },
    {
        "name": "closePosition",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "openId", "type": "uint256"},
            {"name": "proof", "type": "bytes"},
        ],
        "outputs": [],
    },
    {
        "name": "depositLiquidity",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "usdtAmount", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "withdrawLiquidity",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "lpAmount", "type": "uint256"}],
        "outputs": [],
    },
]

TRADE_ROUTER = RawContract(
    title="BrokexTradeRouter",
    address="0x34f89ca5a1c6dc4eb67dfe0af5b621185df32854",
    abi=BROKEX_ABI,
)

POOL_ROUTER = RawContract(
    title="BrokexPoolRouter",
    address="0x9A88d07850723267DB386C681646217Af7e220d7",
    abi=BROKEX_ABI,
)

PAIRS: Dict[str, int] = {
    "BTC_USDT": 0,
    "ETH_USDT": 1,
    "LINK_USDT": 2,
    "DOGE_USDT": 3,
    "AVAX_USDT": 5,
    "SOL_USDT": 10,
    "XRP_USDT": 14,
    "TRX_USDT": 15,
    "ADA_USDT": 16,
    "SUI_USDT": 90,
}

BASE_API = "https://proof.brokex.trade"

class Brokex(Base):
    __module_name__ = "Brokex"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = BaseAsyncSession(proxy=self.wallet.proxy)

        self.base_headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://app.brokex.trade",
            "Referer": "https://app.brokex.trade/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site"
        }

    async def has_claimed(self) -> Optional[bool]:

        contract = await self.client.contracts.get(contract_address=FAUCET_ROUTER)

        res = await contract.functions.hasClaimed(self.client.account.address).call()
        return res

    async def claim_faucet(self) -> str:
        # claimed = await self.has_claimed()
        #
        # if not claimed:

        contract = await self.client.contracts.get(contract_address=FAUCET_ROUTER)
        data = contract.encode_abi("claim", args=[])

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=contract.address,
            data=data,
            value=0
        ))
        await asyncio.sleep(2)
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return "Success Claimed" if receipt else "Failed | Claim faucet"

    @controller_log("Deposit LP")
    async def deposit_liquidity(self, amount_usdt: float = None) -> str:
        settings = Settings()
        usdt_balance = await self.client.wallet.balance(token=USDT)
        percent = random.randint(settings.stake_percent_min, settings.stake_percent_max) / 100
        amount = TokenAmount(amount=float(usdt_balance.Ether) * percent / 100, decimals=usdt_balance.decimals)

        if await self.approve_interface(
                token_address=USDT.address,
                spender=POOL_ROUTER.address,
                amount=None
        ):
            await asyncio.sleep(2)
        else:
            return f' can not approve'

        c = await self.client.contracts.get(contract_address=POOL_ROUTER)
        data = c.encode_abi("depositLiquidity", args=[int(amount.Wei)])

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=0
        ))
        await asyncio.sleep(2)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
        return f"Success | Deposit LP {amount} USDT" if rcpt else "Failed | Deposit LP"

    @controller_log("Withdraw LP")
    async def withdraw_liquidity(self) -> str:
        settings = Settings()
        percent = random.randint(settings.stake_percent_min, settings.stake_percent_max) / 100

        c = await self.client.contracts.get(contract_address=POOL_ROUTER)
        amount = await c.functions.balanceOf(self.client.account.address).call()
        lp_amount = TokenAmount(amount=amount * percent, wei=True)

        data = c.encode_abi("withdrawLiquidity", args=[int(lp_amount.Wei)])

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=0
        ))
        await asyncio.sleep(2)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=600)
        return f"Success | Withdraw LP {lp_amount}" if rcpt else "Failed | Withdraw LP"

    @async_retry(retries=5, delay=3, to_raise=False)
    async def _fetch_proof(self, pair_index: int) -> Optional[Dict[str, Any]]:

        url = f"{BASE_API}/proof?pairs={pair_index}"

        r = await self.session.get(url=url, headers=self.base_headers, timeout=60)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return json.loads(r.text or "{}")

    async def get_user_open_ids(self) -> List[int]:
        try:
            c = await self.client.contracts.get(contract_address=TRADE_ROUTER)
            ids: List[int] = await c.functions.getUserOpenIds(self.client.account.address).call()
            return list(ids or [])
        except Exception as e:
            logger.error(f"{self.wallet} | getUserOpenIds error: {e}")
            return []

    async def get_open_by_id(self, open_id: int) -> Optional[Dict[str, Any]]:
        try:
            c = await self.client.contracts.get(contract_address=TRADE_ROUTER)
            t = await c.functions.getOpenById(int(open_id)).call()

            return {
                "trader": t[0], "id": int(t[1]), "assetIndex": int(t[2]),
                "isLong": bool(t[3]), "leverage": int(t[4]), "openPrice": int(t[5]),
                "sizeUsd": int(t[6]), "timestamp": int(t[7]),
                "stopLossPrice": int(t[8]), "takeProfitPrice": int(t[9]),
                "liquidationPrice": int(t[10]),
            }
        except Exception as e:
            logger.error(f"{self.wallet} | getOpenById error: {e}")
            return None

    @controller_log("Open Position")
    async def open_position_controller(self):

        pair = random.choice(list(PAIRS))
        direction = random.choice([True, False])
        leverage = random.choice([i for i in range(15)])

        settings = Settings()

        usdt_balance = await self.client.wallet.balance(token=USDT)

        if usdt_balance.Ether == 0:
            await self.claim_faucet()
            await asyncio.sleep(8, 10)
            usdt_balance = await self.client.wallet.balance(token=USDT)

        percent = random.randint(settings.brokex_percent_min, settings.brokex_percent_max) / 100
        amount = TokenAmount(amount=float(usdt_balance.Ether) * percent, decimals=usdt_balance.decimals)

        if float(amount.Ether) < 10:
            amount = TokenAmount(amount=10, decimals=usdt_balance.decimals)

        return await self.open_position(pair=pair, is_long=direction, amount=amount, lev=leverage)

    async def open_position(
            self,
            pair: str,
            is_long: bool,
            amount: TokenAmount = None,
            lev: int = 1,
            sl: int = 0,
            tp: int = 0,
    ) -> str:

        if pair not in PAIRS:
            return f"Failed | Unknown pair {pair}"

        if await self.approve_interface(
                token_address=USDT.address,
                spender=POOL_ROUTER.address,
                amount=None
        ):
            await asyncio.sleep(2)
        else:
            return f' can not approve'

        if await self.approve_interface(
                token_address=USDT.address,
                spender=TRADE_ROUTER.address,
                amount=None
        ):
            await asyncio.sleep(2)
        else:
            return f' can not approve'

        proof = await self._fetch_proof(PAIRS[pair])

        if not proof or not proof.get("proof"):
            return "Failed | Fetch proof"

        proof_bytes = Web3.to_bytes(hexstr=proof["proof"])
        idx = int(PAIRS[pair])

        c = await self.client.contracts.get(contract_address=TRADE_ROUTER)
        data = c.encode_abi(
            "openPosition",
            args=[idx, proof_bytes, bool(is_long), int(lev), int(amount.Wei), int(sl), int(tp)]
        )

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=0
        ))
        await asyncio.sleep(2)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)

        return f"Success | Open {pair} {'Long' if is_long else 'Short'} {amount} USDT" if rcpt else "Failed | Open position"


    @controller_log("Close Position")
    async def close_position_controller(self):
        open_ids = await self.get_user_open_ids()
        if len(open_ids) > 1:
            open_id = random.choice(open_ids)
            pos = await self.get_open_by_id(open_id=open_id)

            return await self.close_position(open_id=pos['id'], pair=pos['assetIndex'])

        return 'Nothing to close'


    async def close_position(self, *, open_id: int, pair: int) -> str:
        proof = await self._fetch_proof(pair)
        if not proof or not proof.get("proof"):
            return "Failed | Fetch proof"

        proof_bytes = Web3.to_bytes(hexstr=proof["proof"])

        try:
            c = await self.client.contracts.get(contract_address=TRADE_ROUTER)
            data = c.encode_abi("closePosition", args=[int(open_id), proof_bytes])

            tx = await self.client.transactions.sign_and_send(TxParams(
                to=c.address,
                data=data,
                value=0
            ))
            await asyncio.sleep(2)
            rcpt = await tx.wait_for_receipt(client=self.client, timeout=600)
            return f"Success | Close position #{open_id}" if rcpt else "Failed | Close position"
        except Exception as e:
            logger.error(f"{self.wallet} | closePosition error: {e}")
            return "Failed | Close position"
