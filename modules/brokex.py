import asyncio
import json
from typing import Any, Dict, List, Optional

from loguru import logger
from web3 import Web3
from web3.types import TxParams

from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, DefaultABIs, TokenAmount
from libs.twitter.base import BaseAsyncSession
from utils.db_api.models import Wallet
from utils.logs_decorator import action_log
from utils.retry import async_retry


# =========================
# CONSTANTS / CONTRACTS
# =========================

BASE_API = "https://proofcrypto-production.up.railway.app"

PHRS = RawContract(
    title="PHRS_NATIVE",
    address="0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
    abi=[],  # нативка
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
    address="0xDe897635870b3Dd2e097C09f1cd08841DBc3976a",
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


    async def _has_claimed(self) -> Optional[bool]:

        contract = await self.client.contracts.get(contract_address=FAUCET_ROUTER)

        res = await contract.functions.hasClaimed(self.client.account.address).call()
        return res

    async def claim_faucet(self) -> str:
        claimed = await self._has_claimed()

        if not claimed:

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
                return "Success | Claim faucet" if receipt else "Failed | Claim faucet"
