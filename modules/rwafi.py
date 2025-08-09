import asyncio
import time
from typing import Optional, Dict, Any

from web3 import Web3
from web3.types import TxParams

from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount
from libs.twitter.base import BaseAsyncSession
from utils.db_api.models import Wallet
from utils.logs_decorator import action_log
from utils.retry import async_retry

AQUAFLUX = RawContract(
    title="AquafluxNFT",
    address="0xCc8cF44E196CaB28DBA2d514dc7353af0eFb370E",
    abi=[
        {"type": "function", "name": "claimTokens", "stateMutability": "nonpayable", "inputs": [], "outputs": []},
        {"type": "function", "name": "combineCS", "stateMutability": "nonpayable", "inputs": [{"name": "amount", "type": "uint256"}], "outputs": []},
        {"type": "function", "name": "combinePC", "stateMutability": "nonpayable", "inputs": [{"name": "amount", "type": "uint256"}], "outputs": []},
        {"type": "function", "name": "combinePS", "stateMutability": "nonpayable", "inputs": [{"name": "amount", "type": "uint256"}], "outputs": []},
        {"type": "function", "name": "hasClaimedStandardNFT", "stateMutability": "view", "inputs": [{"name": "owner", "type": "address"}], "outputs": [{"type": "bool"}]},
        {"type": "function", "name": "hasClaimedPremiumNFT",  "stateMutability": "view", "inputs": [{"name": "owner", "type": "address"}], "outputs": [{"type": "bool"}]},
        {
            "type": "function",
            "name": "mint",
            "stateMutability": "nonpayable",
            "inputs": [
                {"name": "nftType", "type": "uint8"},
                {"name": "expiresAt", "type": "uint256"},
                {"name": "signature", "type": "bytes"},
            ],
            "outputs": [],
        },
    ],
)

BASE_API = "https://api.aquaflux.pro/api/v1"


class AquaFlux(Base):
    __module_name__ = "AquaFlux"

    def __init__(self, client: Client, wallet: Wallet, proxy: Optional[str] = None):
        self.client = client
        self.wallet = wallet
        self.proxy = proxy
        self.session = BaseAsyncSession(proxy=self.wallet.proxy)
        self._token: Optional[str] = None

        self.base_headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://playground.aquaflux.pro",
            "Referer": "https://playground.aquaflux.pro/",
            "Content-Type": "application/json",
            "User-Agent": self.session.user_agent,
        }

    # =========================
    # HTTP helpers (with retry)
    # =========================

    @async_retry(retries=3, delay=3, to_raise=False)
    async def _post(self, path: str, payload: Dict[str, Any], *, auth: bool = False) -> Optional[Dict[str, Any]]:
        headers = dict(self.base_headers)
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        r = await self.session.post(
            url=f"{BASE_API}{path}",
            headers=headers,
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            from json import loads
            return loads(r.text or "{}")

    @async_retry(retries=3, delay=3, to_raise=False)
    async def _get(self, path: str, *, auth: bool = True) -> Optional[Dict[str, Any]]:
        headers = dict(self.base_headers)
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        r = await self.session.get(
            url=f"{BASE_API}{path}",
            headers=headers,
            timeout=120,
        )
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            from json import loads
            return loads(r.text or "{}")

    # =========================
    # API auth & helpers
    # =========================

    @async_retry(retries=3, delay=3, to_raise=False)
    async def _login(self) -> bool:
        ts_ms = int(time.time() * 1000)
        msg = f"Sign in to AquaFlux with timestamp: {ts_ms}"
        sig = await self.sign_message(text=msg)

        payload = {
            "address": self.client.account.address,
            "message": msg,
            "signature": sig,
        }

        data = await self._post("/users/wallet-login", payload, auth=False)
        if not data:
            return False

        token = (data.get("data") or {}).get("accessToken")
        if not token:
            return False

        self._token = token
        return True

    @async_retry(retries=3, delay=3, to_raise=False)
    async def _get_signature(self, nft_type: int) -> Optional[tuple[int, str]]:
        data = await self._post(
            "/users/get-signature",
            {"walletAddress": self.client.account.address, "requestedNftType": nft_type},
            auth=True,
        )
        if not data or "data" not in data:
            return None
        d = data["data"]
        return int(d["expiresAt"]), d["signature"]

    @async_retry(retries=3, delay=3, to_raise=False)
    async def _is_twitter_bound(self) -> bool:
        data = await self._get("/users/twitter/binding-status", auth=True)
        return bool((data or {}).get("data", {}).get("isBound", False))

    async def _contract(self):
        return await self.client.contracts.get(contract_address=AQUAFLUX)

    async def _already_minted(self, premium: bool) -> bool:
        try:
            c = await self._contract()
            fn = "hasClaimedPremiumNFT" if premium else "hasClaimedStandardNFT"
            data = c.encode_abi(fn, args=[self.client.account.address])
            res = await self.client.transactions.call(to=c.address, data=data)
            return bool(int(res, 16))
        except Exception:
            return False

    # =========================
    # On-chain actions
    # =========================

    @action_log("Aquaflux | Claim tokens")
    async def claim_tokens(self) -> str:
        c = await self._contract()
        data = c.encode_abi("claimTokens", args=[])
        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=0,
        ))
        await asyncio.sleep(2)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
        return "Success | claimTokens" if rcpt and getattr(rcpt, "status", 1) == 1 else "Failed | claimTokens"

    @action_log("Aquaflux | Combine")
    async def combine(self, variant: str = "combineCS", amount_ether: float = 100) -> str:
        if variant not in {"combineCS", "combinePC", "combinePS"}:
            variant = "combineCS"

        c = await self._contract()
        amount = TokenAmount(amount=amount_ether)
        data = c.encode_abi(variant, args=[amount.Wei])

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=0,
        ))
        await asyncio.sleep(2)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
        return f"Success | {variant} {amount.Ether} PHRS" if rcpt and getattr(rcpt, "status", 1) == 1 else f"Failed | {variant}"

    @action_log("Aquaflux | Mint")
    async def mint(self, nft_type: str = "standard") -> str:
        premium = str(nft_type).lower().startswith("p")

        if not await self._login():
            return "Failed | login"

        if premium and not await self._is_twitter_bound():
            return "Failed | premium requires twitter bound"

        if await self._already_minted(premium=premium):
            return f"Failed | already minted {nft_type}"

        sig = await self._get_signature(1 if premium else 0)
        if not sig:
            return "Failed | signature"
        expires_at, sig_hex = sig

        c = await self._contract()
        sig_bytes = Web3.to_bytes(hexstr=sig_hex)
        data = c.encode_abi("mint", args=[1 if premium else 0, int(expires_at), sig_bytes])

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=0,
        ))
        await asyncio.sleep(2)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
        return f"Success | mint {nft_type}" if rcpt and getattr(rcpt, "status", 1) == 1 else f"Failed | mint {nft_type}"
