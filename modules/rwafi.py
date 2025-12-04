import asyncio
import json
import random
import time
from typing import Any, Dict, Optional, Tuple

from loguru import logger
from web3 import Web3
from web3.types import TxParams

from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import DefaultABIs, RawContract, TokenAmount, TxArgs
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.logs_decorator import action_log, controller_log
from utils.query_json import query_to_json
from utils.retry import async_retry

AQUAFLUX = RawContract(
    title="AquafluxNFT",
    address="0x0D3E024c6F3Dd667AC1Dbf7f278eC865396fb323",
    abi=[
        {
            "name": "faucet",
            "type": "function",
            "stateMutability": "nonpayable",
            "inputs": [
                {"name": "token", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
                {"name": "signature", "type": "bytes"},
            ],
            "outputs": [],
        },
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

AQUAFLUX_STRUCTURE = RawContract(
    title="AquafluxStructure",
    address="0x62FdBc600E8bADf8127E6298DD12B961eDf08b5f",
    abi=[
        {
            "type": "function",
            "name": "deposit",
            "stateMutability": "nonpayable",
            "inputs": [{"name": "id", "type": "bytes32"}, {"name": "amount", "type": "uint256"}],
            "outputs": [],
        }
    ],
)

BASE_API = "https://api3.aquaflux.pro/api/v1"


class AquaContracts:
    USDC_AQUA = RawContract(address="0xb691f00682feef63bc73f41c380ff648d73c6a2c", abi=DefaultABIs.Token, title="USDC_AQUA")
    UST = RawContract(address="0x5E789Bb07B2225132d26BB0FFaca7e37A5eCbEbB", abi=DefaultABIs.Token, title="UST")
    S_UST = RawContract(address="0x93bc7267d802201e51926bef331de80c965ec55f", abi=DefaultABIs.Token, title="S_UST")
    CONTOSO = RawContract(address="0x656B4948C470F3420805abCB43F3928820A0f26D", abi=DefaultABIs.Token, title="CONTOSO")
    S_CORP = RawContract(address="0xeD75C5B68284a1a9568e26A2b48655A3D518D4bc", abi=DefaultABIs.Token, title="S_CORP")
    PRIVATE_CREDIT = RawContract(address="0x4f848D61B35033619Ce558a2FCe8447Cedd38D0d", abi=DefaultABIs.Token, title="PCT")
    S_PCT = RawContract(address="0xc1cf3cf3A86807e8319c0aB1754413c854ab5b7D", abi=DefaultABIs.Token, title="S_PCT")


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
            "Referer": "https://testnet.aquaflux.pro/",
            "Origin": "https://testnet.aquaflux.pro",
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

    @async_retry()
    async def earn(self, token_earn: RawContract | None = None):
        balance = await self.client.wallet.balance()
        if balance.Ether < 0.0003:
            return f"Failed {self.wallet} don't have enough PHRS for transaction. PHRS balance: {balance.Ether}"
        tokens_earn = [AquaContracts.S_CORP, AquaContracts.S_UST, AquaContracts.S_PCT]
        if not token_earn:
            token_earn = random.choice(tokens_earn)
        token_earn = AquaContracts.S_UST
        if token_earn == AquaContracts.S_CORP:
            token_structure = AquaContracts.CONTOSO
            contract_address = Web3.to_checksum_address("0x534966536969c3b697A04538E475992C981521Cf")
        elif token_earn == AquaContracts.S_UST:
            token_structure = AquaContracts.UST
            contract_address = Web3.to_checksum_address("0x92864f94020E79a52aCa036C6A3D3Be9d4388A39")
        elif token_earn == AquaContracts.S_PCT:
            token_structure = AquaContracts.PRIVATE_CREDIT
            contract_address = Web3.to_checksum_address("0x3eaEF8F467059915A6EeB985a0D08de063AB16F9")
        else:
            return f"Failed {self.wallet} can't get structure token for {token_earn.title}"
        balance = await self.client.wallet.balance(token=token_earn)
        if int(balance.Ether) < 2:
            logger.info(f"{self.wallet} balance too small {balance.Ether} {token_earn.title} for token earn. Try deposit")
            deposit = await self.deposit(token_structure=token_structure)
            if not deposit:
                return deposit
            return await self.earn(token_earn)
        await self.approve_interface(token_address=token_earn, spender=contract_address, amount=None)
        c = await self.client.contracts.get(
            contract_address=contract_address,
            abi=[
                {
                    "type": "function",
                    "name": "stake",
                    "stateMutability": "nonpayable",
                    "inputs": [{"name": "amount", "type": "uint256"}],
                    "outputs": [],
                }
            ],
        )
        amount = TokenAmount(random.randint(1, int(int(balance.Ether) / 2)))
        params = TxArgs(amount=amount.Wei)
        data = c.encode_abi("stake", args=params.tuple())
        data = "0xa694fc3a" + data[10:]
        tx = await self.client.transactions.sign_and_send(TxParams(to=c.address, data=data))
        await asyncio.sleep(4)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if rcpt:
            return f"{self.wallet} success earn {amount} {token_structure.title}"
        return f"Failed {self.wallet} can't earn {amount} {token_structure.title} token"

    @async_retry()
    async def deposit(self, token_structure: RawContract | None = None):
        balance = await self.client.wallet.balance()
        if balance.Ether < 0.0003:
            return f"Failed {self.wallet} don't have enough PHRS for transaction. PHRS balance: {balance.Ether}"
        tokens_structure = [AquaContracts.UST, AquaContracts.CONTOSO, AquaContracts.PRIVATE_CREDIT]
        if not token_structure:
            token_structure = random.choice(tokens_structure)
        balance = await self.client.wallet.balance(token=token_structure.address)
        if int(balance.Ether) < 2:
            logger.info(f"{self.wallet} balance too small {balance.Ether} {token_structure.title} for token deposit. Try token faucet")
            claim = await self.claim_tokens(token_structure)
            if not "Failed" in claim:
                return claim
            return await self.deposit(token_structure)
        await self.approve_interface(token_address=token_structure.address, spender=AQUAFLUX_STRUCTURE.address, amount=None)
        if token_structure == AquaContracts.UST:
            id = "0xd048a586b49e0cf14afc137d0ebec0024a50aa5be56d006ecf46088f47537e33"
        elif token_structure == AquaContracts.CONTOSO:
            id = "0xb6dad7cac45cd7ee7d611c0160667e8595bcece1e8dc2b22228b6f329e1caa60"
        elif token_structure == AquaContracts.PRIVATE_CREDIT:
            id = "0x8b79ddf5ff2f0db54884b06a0b748a687abe7eb723e676eac22a5a811e9312ae"
        else:
            return f"Failed {self.wallet} token {token_structure.title} don't have id for structure"
        amount = TokenAmount(random.randint(1, int(int(balance.Ether) / 2)))

        c = await self.client.contracts.get(contract_address=AQUAFLUX_STRUCTURE)
        params = TxArgs(id=id, amount=amount.Wei)
        data = c.encode_abi("deposit", args=params.tuple())
        data = "0xef272020" + data[10:]
        tx = await self.client.transactions.sign_and_send(TxParams(to=c.address, data=data, value=0))
        await asyncio.sleep(2)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if rcpt:
            return f"{self.wallet} success deposit {amount} {token_structure.title}"
        return f"Failed {self.wallet} can't deposit {amount} {token_structure.title} token"

    async def get_faucet_data(self, token_claim):
        if not self.auth_token:
            await self._login()
        json_data = {"tokenAddress": token_claim}
        resp = await self.session.post(url=f"{BASE_API}/faucet/claim-signature", headers=self.base_headers, json=json_data)
        resp.raise_for_status()
        try:
            data = resp.json()

        except Exception:
            data = json.loads(resp.text or "{}")

        if data.get("success"):
            return data.get("data")

        return False

    @controller_log("Claim tokens")
    @async_retry()
    async def claim_tokens(self, token_claim: RawContract | None = None) -> str:
        tokens_claim = [AquaContracts.UST, AquaContracts.CONTOSO, AquaContracts.PRIVATE_CREDIT]
        if not token_claim:
            token_claim = random.choice(tokens_claim)
        get_faucet_data = await self.get_faucet_data(token_claim.address)
        if not get_faucet_data:
            raise Exception(f"{self.wallet} can't get faucet data for claim tokens")
        c = await self.client.contracts.get(contract_address=AQUAFLUX)
        params = TxArgs(
            token=token_claim.address,
            amount=int(get_faucet_data.get("baseAmount")),
            deadline=int(get_faucet_data.get("expiresAt")),
            signature=get_faucet_data.get("signature"),
        )
        data = c.encode_abi("faucet", args=params.tuple())
        data = "0xc564e9ce" + data[10:]
        tx = await self.client.transactions.sign_and_send(TxParams(to=c.address, data=data, value=0))
        await asyncio.sleep(3)
        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if rcpt:
            return f"{self.wallet} success faucet {get_faucet_data.get('baseAmount')} {token_claim.title}"
        return f"Failed {self.wallet} can't faucet {get_faucet_data.get('baseAmount')} {token_claim.title}"

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
