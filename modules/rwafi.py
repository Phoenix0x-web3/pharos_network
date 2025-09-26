import asyncio
import json
import time
from typing import Any, Dict, Optional, Tuple

from web3 import Web3
from web3.types import TxParams

from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.logs_decorator import action_log, controller_log
from utils.query_json import query_to_json
from utils.retry import async_retry

AQUAFLUX = RawContract(
    title="AquafluxNFT",
    address="0xCc8cF44E196CaB28DBA2d514dc7353af0eFb370E",
    abi=[
        {"type": "function", "name": "claimTokens", "stateMutability": "nonpayable", "inputs": [], "outputs": []},
        {
            "type": "function",
            "name": "combineCS",
            "stateMutability": "nonpayable",
            "inputs": [{"name": "amount", "type": "uint256"}],
            "outputs": [],
        },
        {
            "type": "function",
            "name": "combinePC",
            "stateMutability": "nonpayable",
            "inputs": [{"name": "amount", "type": "uint256"}],
            "outputs": [],
        },
        {
            "type": "function",
            "name": "combinePS",
            "stateMutability": "nonpayable",
            "inputs": [{"name": "amount", "type": "uint256"}],
            "outputs": [],
        },
        {
            "type": "function",
            "name": "hasClaimedStandardNFT",
            "stateMutability": "view",
            "inputs": [{"name": "owner", "type": "address"}],
            "outputs": [{"type": "bool"}],
        },
        {
            "type": "function",
            "name": "hasClaimedPremiumNFT",
            "stateMutability": "view",
            "inputs": [{"name": "owner", "type": "address"}],
            "outputs": [{"type": "bool"}],
        },
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

    def __init__(self, client: Client, wallet: Wallet, *, proxy: Optional[str] = None):
        self.client = client
        self.wallet = wallet
        self.proxy = proxy
        self.session = Browser(wallet=wallet)
        self.auth_token: Optional[str] = None
        self.base_headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://playground.aquaflux.pro",
            "Referer": "https://playground.aquaflux.pro/",
            "Content-Type": "application/json",
        }

    @async_retry(retries=3, delay=3, to_raise=False)
    async def _login(self) -> bool:
        ts_ms = int(time.time() * 1000)
        message = f"Sign in to AquaFlux with timestamp: {ts_ms}"
        signature = await self.sign_message(text=message)

        r = await self.session.post(
            url=f"{BASE_API}/users/wallet-login",
            headers=self.base_headers,
            json={"address": self.client.account.address, "message": message, "signature": signature},
            timeout=120,
        )

        r.raise_for_status()

        try:
            data = r.json()

        except Exception:
            import json as _json

            data = _json.loads(r.text or "{}")

        token = (data.get("data") or {}).get("accessToken")
        if not token:
            return False

        self.auth_token = token
        self.base_headers = {**self.base_headers, "authorization": f"Bearer {self.auth_token}"}
        return True

    @async_retry(retries=5, delay=3, to_raise=False)
    async def _get_signature(self, nft_type: int) -> Optional[Tuple[int, str]]:
        payload = {"walletAddress": self.client.account.address, "requestedNftType": nft_type}

        r = await self.session.post(
            url=f"{BASE_API}/users/get-signature",
            headers=self.base_headers,
            json=payload,
            timeout=120,
        )

        r.raise_for_status()

        try:
            data = r.json()

        except Exception:
            import json as _json

            data = _json.loads(r.text or "{}")

        block = data.get("data") or {}
        if "expiresAt" not in block or "signature" not in block:
            return None
        return int(block["expiresAt"]), str(block["signature"])

    async def twitter_bound(self) -> bool:
        if not self.auth_token:
            await self._login()

        r = await self.session.get(
            url=f"{BASE_API}/users/twitter/binding-status",
            headers=self.base_headers,
            timeout=60,
        )
        r.raise_for_status()
        try:
            data = r.json()

        except Exception:
            import json as _json

            data = _json.loads(r.text or "{}")

        return data.get("data").get("bound")

    @async_retry(retries=5, delay=3, to_raise=False)
    async def twitter_initiate(
        self,
    ) -> Optional[str | Dict[str, Any]]:
        """
        POST /users/twitter/initiate
        Возвращает URL авторизации в Twitter (обычно в data.url / data.authUrl).
        """
        if not self.auth_token:
            ok = await self._login()
            if not ok:
                return None

        redirect_url: str = "https://playground.aquaflux.pro/oauthcallback/x"

        r = await self.session.post(
            url=f"{BASE_API}/users/twitter/initiate",
            headers=self.base_headers,
            json={"redirectUrl": redirect_url},
            timeout=120,
        )
        r.raise_for_status()

        try:
            data = r.json()

        except Exception:
            import json as _json

            data = _json.loads(r.text or "{}")

        d = data.get("data") or {}
        url = d.get("url") or d.get("authUrl") or d.get("redirectUrl") or r.headers.get("location")
        return url or data

    @controller_log("Bind Twitter")
    async def bind_twitter(self, callback_data):
        query = query_to_json(callback_data.callback_url)

        redirect_url = "https://playground.aquaflux.pro/oauthcallback/x"
        payload = {"code": query["code"], "state": query["state"], "redirectUrl": redirect_url}

        resp = await self.session.post(
            url=f"{BASE_API}/users/twitter/callback",
            headers=self.base_headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        try:
            data = resp.json()

        except Exception:
            data = json.loads(resp.text or "{}")

        if data.get("status") == "success":
            return f"Success | bounded user {data.get('data').get('user').get('twitterUsername')}"

        return f"Failed bind twitter"

    async def check_twitter_following(self):
        resp = await self.session.post(
            url=f"{BASE_API}/users/check-twitter-follow",
            headers=self.base_headers,
            timeout=120,
        )

        resp.raise_for_status()

        try:
            data = resp.json()

        except Exception:
            data = json.loads(resp.text or "{}")

        if data.get("status") == "success":
            return data.get("data").get("isFollowing")

        return False

    @controller_log("Claim tokens")
    async def claim_tokens(self) -> str:
        c = await self.client.contracts.get(contract_address=AQUAFLUX)
        data = c.encode_abi("claimTokens", args=[])
        tx = await self.client.transactions.sign_and_send(TxParams(to=c.address, data=data, value=0))
        await asyncio.sleep(2)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)

        return "Success | claimTokens" if rcpt else "Failed | claimTokens"

    @controller_log("Combine")
    async def combine(self, variant: str = "combineCS", amount_ether: float = 100) -> str:
        if variant not in {"combineCS", "combinePC", "combinePS"}:
            variant = "combineCS"

        c = await self.client.contracts.get(contract_address=AQUAFLUX)
        amount = TokenAmount(amount=amount_ether)
        data = c.encode_abi(variant, args=[amount.Wei])

        tx = await self.client.transactions.sign_and_send(TxParams(to=c.address, data=data, value=0))

        await asyncio.sleep(2)

        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
        return f"Success | {variant} {amount.Ether} PHRS" if rcpt else f"Failed | {variant}"

    async def already_minted(self, *, premium: bool) -> bool:
        c = await self.client.contracts.get(contract_address=AQUAFLUX)

        if premium:
            res = await c.functions.hasClaimedPremiumNFT(self.client.account.address).call()
            return res
        else:
            res = await c.functions.hasClaimedStandardNFT(self.client.account.address).call()
            return res

    async def check_token_holdings(self):
        resp = await self.session.post(
            url=f"{BASE_API}/users/check-token-holding",
            headers=self.base_headers,
            timeout=120,
        )
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            data = json.loads(resp.text or "{}")

        if data.get("status") == "success":
            return data.get("data").get("isHoldingToken")

        return f"Failed bind twitter"

    @action_log("Mint")
    async def mint(self, nft_type: str = "premium") -> str:
        if not self.auth_token:
            ok = await self._login()
            if not ok:
                return "Failed | login"

        premium = str(nft_type).lower().startswith("p")

        # if premium:
        #     if not await self.twitter_bound():
        #         return "Failed | premium requires twitter bound"
        #
        # if await self.already_minted(premium=premium):
        #     return f"Failed | already minted {nft_type}"
        check_holdings = await self.check_token_holdings()
        if check_holdings:
            sig = await self._get_signature(1 if premium else 0)
            if not sig:
                return "Failed | signature"

            expires_at, sig_hex = sig

            c = await self.client.contracts.get(contract_address=AQUAFLUX)

            sig_bytes = Web3.to_bytes(hexstr=sig_hex)

            calldata = c.encode_abi("mint", args=[1 if premium else 0, int(expires_at), sig_bytes])

            tx = await self.client.transactions.sign_and_send(TxParams(to=c.address, data=calldata, value=0))

            await asyncio.sleep(2)
            rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
            return f"Success | minted {nft_type} nft" if rcpt else f"Failed | mint {nft_type} nft"
