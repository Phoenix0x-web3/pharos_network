# modules/spout.py
import asyncio
import random
from typing import List

from eth_utils import to_bytes
from loguru import logger
from web3 import Web3
from web3.types import TxParams

from data.models import Contracts
from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import DefaultABIs, RawContract, TokenAmount, TxArgs
from libs.eth_async.wallet import Wallet
from utils.browser import Browser
from utils.logs_decorator import controller_log
from utils.retry import async_retry

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
MAX_UINT256 = (1 << 256) - 1

FACTORY_ROUTER = "0x18cB5F2774a80121d1067007933285B32516226a"
GATEWAY_ROUTER = "0x126F0c11F3e5EafE37AB143D4AA688429ef7DCB3"
ISSUER_ROUTER = "0xA5C77b623BEB3bC0071fA568de99e15Ccc06C7cb"
ORDERS_ROUTER = "0x81b33972f8bdf14fD7968aC99CAc59BcaB7f4E9A"

SLQD = "0x54b753555853ce22f66Ac8CB8e324EB607C4e4eE"


ERC20_ABI = [
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "allowance",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "approve",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {"type": "function", "name": "decimals", "stateMutability": "view", "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
]

SPOUT_ABI = [
    {
        "type": "function",
        "name": "getIdentity",
        "stateMutability": "view",
        "inputs": [{"internalType": "address", "name": "_wallet", "type": "address"}],
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
    },
    {
        "type": "function",
        "name": "getClaimIdsByTopic",
        "stateMutability": "view",
        "inputs": [{"internalType": "uint256", "name": "_topic", "type": "uint256"}],
        "outputs": [{"internalType": "bytes32[]", "name": "claimIds", "type": "bytes32[]"}],
    },
    {
        "type": "function",
        "name": "deployIdentityForWallet",
        "stateMutability": "nonpayable",
        "inputs": [{"internalType": "address", "name": "identityOwner", "type": "address"}],
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
    },
    {
        "type": "function",
        "name": "addClaim",
        "stateMutability": "nonpayable",
        "inputs": [
            {"internalType": "uint256", "name": "_topic", "type": "uint256"},
            {"internalType": "uint256", "name": "_scheme", "type": "uint256"},
            {"internalType": "address", "name": "_issuer", "type": "address"},
            {"internalType": "bytes", "name": "_signature", "type": "bytes"},
            {"internalType": "bytes", "name": "_data", "type": "bytes"},
            {"internalType": "string", "name": "_uri", "type": "string"},
        ],
        "outputs": [{"internalType": "bytes32", "name": "claimRequestId", "type": "bytes32"}],
    },
    {
        "type": "function",
        "name": "buyAsset",
        "stateMutability": "nonpayable",
        "inputs": [
            {"internalType": "uint256", "name": "adfsFeedId", "type": "uint256"},
            {"internalType": "string", "name": "ticker", "type": "string"},
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "uint256", "name": "usdcAmount", "type": "uint256"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "sellAsset",
        "stateMutability": "nonpayable",
        "inputs": [
            {"internalType": "uint256", "name": "adfsFeedId", "type": "uint256"},
            {"internalType": "string", "name": "ticker", "type": "string"},
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "uint256", "name": "tokenAmount", "type": "uint256"},
        ],
        "outputs": [],
    },
]

SPOUT_FACTORY = RawContract(title="SpoutFactory", address=FACTORY_ROUTER, abi=SPOUT_ABI)
SPOUT_GATEWAY = RawContract(title="SpoutGateway", address=GATEWAY_ROUTER, abi=SPOUT_ABI)
SPOUT_ORDERS = RawContract(title="SpoutOrders", address=ORDERS_ROUTER, abi=SPOUT_ABI)
SLQD = RawContract(title="SLQD", address=SLQD, abi=DefaultABIs.Token)


class Spout(Base):
    __module__ = "Spout"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = Browser(wallet=wallet)
        self.BASE_API = "https://www.spout.finance/api"

    async def get_identity(self) -> str:
        c = await self.client.contracts.get(contract_address=SPOUT_FACTORY)

        return await c.functions.getIdentity(self.client.account.address).call()

    async def is_identity_created(
        self,
    ) -> bool:
        x = await self.get_identity()
        return bool(x and x != ZERO_ADDRESS)

    async def is_kyc_completed(self) -> bool:
        identity = await self.get_identity()

        identity_check = bool(identity and identity != ZERO_ADDRESS)
        if not identity_check:
            return False

        claims = await self.get_claim_ids(identity_address=identity, topic=1)
        if not claims:
            return False

        return True

    async def get_claim_ids(self, identity_address: str, topic: int = 1) -> List[bytes]:
        c = await self.client.contracts.get(contract_address=RawContract(title="SpoutIdentity", address=identity_address, abi=SPOUT_ABI))

        return await c.functions.getClaimIdsByTopic(topic).call()

    @async_retry(retries=15, delay=2)
    async def get_kyc_signature(self):
        identity = await self.get_identity()

        data = {
            "userAddress": self.client.account.address,
            "onchainIDAddress": identity,
            "claimData": "KYC passed",
            "topic": 1,
            "countryCode": 91,
        }

        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Origin": "https://www.spout.finance",
            "Referer": "https://www.spout.finance/app/profile?tab=kyc",
        }
        url = f"{self.BASE_API}/kyc-signature"
        r = await self.session.post(url=url, json=data, headers=headers)
        r.raise_for_status()

        return r.json()

    async def spout_flow(self):
        identity = await self.is_identity_created()

        if not identity:
            deploy = await self.deploy_identity()
            if "Failed" not in deploy:
                logger.success(deploy)
            else:
                raise Exception

        signature = await self.get_kyc_signature()

        identity = await self.get_identity()

        claims = await self.get_claim_ids(identity_address=identity)

        if not claims:
            await asyncio.sleep(10)
            add_claim = await self.add_claim(signature=signature)
            if "Failed" not in add_claim:
                logger.success(add_claim)
            else:
                raise Exception

        return "Success Registered on spout"

    @controller_log("Identity")
    async def deploy_identity(self) -> str:
        c = await self.client.contracts.get(contract_address=SPOUT_GATEWAY)

        data = TxArgs(to=self.client.account.address)

        data = c.encodeABI("deployIdentityForWallet", args=data.tuple())

        tx_params = TxParams(to=c.address, data=data, value=0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success | Deploy Identity"

        return "Failed | Deploy Identity"

    def _norm_v(self, v: int) -> int:
        v = int(v)
        if v in (27, 28):
            return v
        if v in (0, 1):
            return 27 + v
        return v

    def _pack_rsv(self, sig: dict) -> bytes:
        r = int(sig["r"], 16).to_bytes(32, "big")  # фикс 32
        s = int(sig["s"], 16).to_bytes(32, "big")  # фикс 32
        v = self._norm_v(int(sig["v"])).to_bytes(1, "big")
        out = r + s + v
        if len(out) != 65:
            raise ValueError(f"Bad signature length={len(out)}")
        return out

    @controller_log("Claims")
    async def add_claim(
        self,
        signature: dict,
    ) -> str:
        # sig_dict = signature["signature"]
        # r_bytes = int(sig_dict["r"], 16).to_bytes(32, "big")  # фиксированная ширина 32
        # s_bytes = int(sig_dict["s"], 16).to_bytes(32, "big")
        # v_val = int(sig_dict["v"])
        # v_norm = v_val if v_val in (27, 28) else (27 + v_val if v_val in (0, 1) else v_val)
        # v_byte = v_norm.to_bytes(1, "big")
        # sig65 = r_bytes + s_bytes + v_byte

        sig65 = self._pack_rsv(signature["signature"])

        issuer_address = signature["issuerAddress"]
        data_hash = signature["dataHash"]
        topic = signature["topic"]

        identity = await self.get_identity()

        c = await self.client.contracts.get(contract_address=RawContract(title="SpoutIdentity", address=identity, abi=SPOUT_ABI))

        data = to_bytes(hexstr="0x6fdd523c9e64db4a7a67716a6b20d5da5ce39e3ee59b2ca281248b18087e860")
        # data = to_bytes(hexstr=data_hash)

        data = TxArgs(topic=topic, scheme=1, issuer=Web3.to_checksum_address(ISSUER_ROUTER), signature=sig65, payload=data, uri="")

        data = c.encodeABI("addClaim", args=data.tuple())

        tx_params = TxParams(to=c.address, data=data, value=0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success | Added Claims"

        return "Failed"

    @controller_log("Swap")
    async def _swap(self, from_token: RawContract, to_token: RawContract, amount: TokenAmount):
        c = await self.client.contracts.get(contract_address=SPOUT_ORDERS)

        logger.debug(f"{self.wallet} | {self.__module__} | trying to swap {amount} {from_token.title} to {to_token.title}")

        feed = 2000002

        data = TxArgs(feed=feed, ticker="LQD", token=from_token.address, amount=amount.Wei)
        data = c.encodeABI("buyAsset", args=data.tuple())

        if await self.approve_interface(token_address=from_token.address, spender=c.address, amount=amount):
            await asyncio.sleep(random.randint(2, 5))
        else:
            return f" can not approve"

        tx_params = TxParams(to=c.address, data=data, value=0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success | Swap {amount} {from_token.title} to {to_token.title}"

        return f"Failed | | Swap {amount} {from_token.title} to {to_token.title}"

    async def swap_controller(self):
        settings = Settings()

        percent = random.randint(settings.spout_percent_min, settings.spout_percent_max) / 100

        kyc = await self.is_kyc_completed()

        if not kyc:
            await self.spout_flow()

        token = [
            Contracts.USDC,
            SLQD,
        ]

        from_token = Contracts.USDC
        to_token = SLQD

        balance = await self.client.wallet.balance(token=from_token)
        amount = TokenAmount(
            amount=float(balance.Ether) * percent, decimals=await self.client.transactions.get_decimals(contract=from_token.address)
        )

        return await self._swap(from_token=from_token, to_token=to_token, amount=amount)
