from __future__ import annotations

import asyncio
import random
import time

from eth_abi import encode
from eth_utils import keccak, to_hex
from loguru import logger
from web3.types import TxParams

from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount, TxArgs
from libs.eth_async.utils.utils import randfloat
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log
from utils.retry import async_retry

MINT_ABI = [
    {"type": "function", "name": "freeMint", "stateMutability": "nonpayable", "inputs": [], "outputs": []},
    {"type": "function", "name": "claimWearable", "stateMutability": "nonpayable", "inputs": [], "outputs": []},
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "allTokensOfOwner",
        "stateMutability": "view",
        "inputs": [{"name": "_owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256[]"}],
    },
    {
        "type": "function",
        "name": "tokenOfOwnerByIndex",
        "stateMutability": "view",
        "inputs": [{"name": "_owner", "type": "address"}, {"name": "_index", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "pet",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "gotchipusTokenId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "summonGotchipus",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "args",
                "type": "tuple",
                "components": [
                    {"name": "gotchipusTokenId", "type": "uint256"},
                    {"name": "gotchiName", "type": "string"},
                    {"name": "collateralToken", "type": "address"},
                    {"name": "stakeAmount", "type": "uint256"},
                    {"name": "utc", "type": "uint8"},
                    {"name": "story", "type": "bytes"},
                ],
            }
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "getLastPetTime",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint32"}],
    },
    {
        "type": "function",
        "name": "transfer",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "transferFrom",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "from", "type": "address"}, {"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "ownerOf",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "type": "function",
        "name": "executeAccount",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "acc", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
        ],
        "outputs": [],
    },
]

TBA_REGISTRY_ABI = [
    {
        "type": "function",
        "name": "account",
        "stateMutability": "view",
        "inputs": [
            {"name": "implementation", "type": "address"},
            {"name": "salt", "type": "bytes32"},
            {"name": "chainId", "type": "uint256"},
            {"name": "tokenContract", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "type": "function",
        "name": "createAccount",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "implementation", "type": "address"},
            {"name": "salt", "type": "bytes32"},
            {"name": "chainId", "type": "uint256"},
            {"name": "tokenContract", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
        ],
        "outputs": [{"name": "account_", "type": "address"}],
    },
]
TBA_REGISTRY_ADDRESS = "0x000000E7C8746fdB64D791f6bb387889c5291454"
# опционально:
TBA_IMPLEMENTATION_ADDRESS = "0x41C8f39463A868d3A88af00cd0fe7102F30E44eC"  # если понадобится — скажи, поищу
TBA_SALT = "0x" + "00" * 32

TBA_REGISTRY = RawContract(
    title="ERC6551Registry",
    address=TBA_REGISTRY_ADDRESS,  # <- заполни в settings
    abi=TBA_REGISTRY_ABI,
)

GOTCHIPUS_FREE = RawContract(title="GOTCHIPUS_FREE", address="0x0000000038f050528452D6Da1E7AACFA7B3Ec0a8", abi=MINT_ABI)

EIP712_NAME = "Gotchipus"
EIP712_VERSION = "v0.1.0"
ZERO_ADDR = "0x0000000000000000000000000000000000000000"


class Gotchipus(Base):
    __module__ = "Gotchipus"

    BASE_API = "https://gotchipus.com"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = Browser(wallet=wallet)
        self.base_headers = {
            "Accept": "*/*",
            "Origin": "https://gotchipus.com",
            "Referer": "https://gotchipus.com/",
        }

    async def check_gotchipus_free_ntf(self):
        c = await self.client.contracts.get(contract_address=GOTCHIPUS_FREE)

        return await c.functions.balanceOf(self.client.account.address).call()

    async def get_gotchipus_nft_id(self):
        c = await self.client.contracts.get(contract_address=GOTCHIPUS_FREE)

        return await c.functions.allTokensOfOwner(self.client.account.address).call()

    @controller_log("Mint Free NFT")
    async def mint_gotchipus(self):
        c = await self.client.contracts.get(contract_address=GOTCHIPUS_FREE)

        logger.debug(f"{self.wallet} | {self.__module__} | trying to mint Gotchipus")

        data = c.encodeABI("freeMint", args=[])

        tx_params = TxParams(to=c.address, data=data, value=0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success | Minted Gotchipus"

        return f"Failed | Minted Gotchipus"

    @controller_log("Mint Wearable")
    async def mint_wearable(self):
        c = await self.client.contracts.get(contract_address=GOTCHIPUS_FREE)

        logger.debug(f"{self.wallet} | {self.__module__} | trying to mint Wearable")

        data = c.encodeABI("claimWearable", args=[])

        tx_params = TxParams(to=c.address, data=data, value=0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success | Minted Wearable"

        return f"Failed | | Mint Wearable"

    @async_retry()
    async def get_tasks_info(self) -> dict:
        url = f"{self.BASE_API}/api/tasks/info"
        payload = {"address": self.client.account.address}
        r = await self.session.post(url=url, json=payload, headers=self.base_headers)
        if r.json().get("status") == "error":
            raise Exception
        return r.json()

    @async_retry()
    async def verify_tasks_info(self) -> dict:
        url = f"{self.BASE_API}/api/tasks/verify"
        payload = self._build_checkin_payload()
        r = await self.session.post(url=url, json=payload, headers=self.base_headers)
        return r.json()

    @async_retry()
    async def _claim_checkin(self) -> dict:
        url = f"{self.BASE_API}/api/tasks/checkin"
        payload = {"address": self.client.account.address, "event": "check_in"}
        r = await self.session.post(url=url, json=payload, headers=self.base_headers)
        return r.json()

    def _build_checkin_payload(self) -> dict:
        domain_typehash = keccak(text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
        name_hash = keccak(text=EIP712_NAME)
        version_hash = keccak(text=EIP712_VERSION)

        domain_separator = keccak(
            encode(
                ["bytes32", "bytes32", "bytes32", "uint256", "address"],
                [domain_typehash, name_hash, version_hash, self.client.network.chain_id, GOTCHIPUS_FREE.address],
            )
        )

        checkin_typehash = keccak(text="CheckIn(string intent,address user,uint256 timestamp)")
        intent_hash = keccak(text="Daily Check-In for Gotchipus")
        ts = int(time.time())

        struct_hash = keccak(
            encode(
                ["bytes32", "bytes32", "address", "uint256"],
                [checkin_typehash, intent_hash, self.client.account.address, ts],
            )
        )

        digest = keccak(b"\x19\x01" + domain_separator + struct_hash)
        signed = self.client.account.signHash(digest)

        return {
            "address": self.client.account.address,
            "signature": to_hex(signed.signature),
            "timestamp": ts,
        }

    @async_retry()
    async def get_gotchipus_tokens(self, include_info: bool = False) -> dict:
        url = f"{self.BASE_API}/api/tokens/gotchipus"
        params = {
            "owner": self.client.account.address,
            "includeGotchipusInfo": "true" if include_info else "false",
        }
        r = await self.session.get(url=url, params=params, headers=self.base_headers)
        return r.json().get("ids")

    @async_retry()
    async def get_story_stream(self) -> dict:
        url = f"{self.BASE_API}/api/story/stream"
        r = await self.session.get(url=url, headers=self.base_headers)
        return r.json()

    @controller_log("Gotchipus Send")
    async def transfer_from_gotchipus(self):
        c = await self.client.contracts.get(contract_address=GOTCHIPUS_FREE)

        amount = TokenAmount(amount=randfloat(from_=0.00001, to_=0.001, step=0.00001))

        gotchipus_address = await self.get_tokenid_wallet()

        token_id = await self.get_gotchipus_tokens()
        token_id = token_id[0]

        data = TxArgs(acc=gotchipus_address, token=int(token_id), to=self.client.account.address, amount=amount.Wei, data=b"")

        data = c.encodeABI("executeAccount", args=data.tuple())

        tx_params = TxParams(to=c.address, data=data, value=0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success | Sended {amount} PHRS to self address"

        return f"Failed | Send PHRS to self"

    @controller_log("Popup Gotchipus")
    async def popup_gotchipus(self, address: str, amount: TokenAmount):
        send_phrs = await self.send_eth(to_address=address, amount=amount)

        if send_phrs:
            return f"Success | Sended {amount} PHRS to Gotchipus"

        return f"Failed | Send PHRS to self"

    @controller_log("Summon Gotchipus")
    async def summon(self, utc: int = 0) -> str:
        story_json = await self.get_story_stream()

        name = story_json["storys"][0]["name"]
        story = story_json["storys"][0]["story"]

        if not name or not story:
            return "Failed | Story/Name not found"

        token_id = await self.get_gotchipus_nft_id()

        if token_id is None:
            return "Failed | tokenId not found"

        token_id = token_id[0]

        c = await self.client.contracts.get(contract_address=GOTCHIPUS_FREE)

        balance = await self.client.wallet.balance()

        stake = TokenAmount(amount=float(balance.Ether) * 0.05)

        args = [
            [
                int(token_id),
                name,
                ZERO_ADDR,
                stake.Wei,
                int(utc),
                story.encode("utf-8"),
            ]
        ]

        data = c.encodeABI("summonGotchipus", args=args)

        tx_params = TxParams(to=c.address, data=data, value=stake.Wei)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success | Summoned Gotchipus"

        return f"Failed | | Summoned Gotchipus"

    @controller_log("Pet")
    async def pet(self, utc: int = 0) -> str:
        token_id = await self.get_gotchipus_tokens()
        token_id = token_id[0]

        if token_id is None:
            return "Failed | tokenId not found"

        c = await self.client.contracts.get(contract_address=GOTCHIPUS_FREE)

        data = c.encodeABI("pet", args=[int(token_id)])

        tx_params = TxParams(to=c.address, data=data, value=0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success | Petted Success "

        return f"Failed | Failed Petted"

    async def can_check_pet(self):
        c = await self.client.contracts.get(contract_address=GOTCHIPUS_FREE)
        token_id = await self.get_gotchipus_tokens()
        token_id = token_id[0]

        pet_check_time = await c.functions.getLastPetTime(int(token_id)).call()

        PET_COOLDOWN = 86_400
        now = int(time.time())

        if (pet_check_time + PET_COOLDOWN - now) < 0:
            return True
        return False

    @async_retry()
    async def get_all_tasks(self) -> dict:
        url = f"{self.BASE_API}/api/tasks/allTasks"
        r = await self.session.get(url=url, headers=self.base_headers)

        r.raise_for_status()
        data = r.json().get("data")
        return data

    @async_retry()
    async def check_task_completed(self, task: dict) -> str:
        url = f"{self.BASE_API}/api/tasks/is_task_completed"

        payload = {"address": self.client.account.address, "task_id": int(task["task_id"])}

        r = await self.session.post(url=url, json=payload, headers=self.base_headers)
        r.raise_for_status()

        if r.json().get("status") == "success":
            return r.json().get("data")

        raise Exception(f"Failed | {task['task_title']} | {r.json()}")

    @controller_log("Completed Task")
    @async_retry()
    async def task_completed(self, task: dict) -> str:
        url = f"{self.BASE_API}/api/tasks/complete-select-task"

        payload = {"address": self.client.account.address, "task_id": int(task["task_id"])}

        r = await self.session.post(url=url, json=payload, headers=self.base_headers)
        r.raise_for_status()

        if r.json().get("status") == "success":
            return f"Success | {task['task_title']} | {r.json().get('data')}"

        return f"Failed | {task['task_title']} | {r.json()}"

    async def complete_tasks(self):
        tasks = await self.get_all_tasks()

        await self.get_tasks_info()

        for task in tasks:
            status = await self.task_completed(task=task)
            if "Failed" not in status:
                logger.success(status)
            else:
                logger.warning(status)

    async def check_tasks_completed(self):
        tasks = await self.get_all_tasks()

        res = []

        for task in tasks:
            status = await self.check_task_completed(task=task)
            res.append(status)

        if False in res:
            return False

        return True

    async def can_check_in(self):
        info = await self.get_tasks_info()

        if not info or info.get("code") != 0:
            return f"Failed | Fetch tasks | {info!r}"

        data = info.get("data") or {}
        latest = data.get("latest_check_in_at")

        if latest and int(time.time()) < int(latest) + 86400:
            return False

        return True

    @controller_log("Daily Check-In")
    async def check_in(self):
        ver = await self.verify_tasks_info()
        if not ver or ver.get("code") != 0:
            return f"Failed | Verify | {ver!r}"
        res = await self._claim_checkin()

        if res and res.get("code") == 0:
            return "Success | Claimed"

        raise Exception(f"Failed | Claim | {res!r}")

    async def get_tokenid_wallet(self):
        url = f"{self.BASE_API}/api/tokens/gotchipus-details"

        token_id = await self.get_gotchipus_tokens()
        token_id = token_id[0]

        params = {"owner": self.client.account.address, "tokenId": token_id}

        r = await self.session.get(url=url, params=params, headers=self.base_headers)
        r.raise_for_status()

        return r.json().get("tokenBoundAccount")

    async def owner_of(self) -> str:
        token_id = await self.get_gotchipus_tokens()
        token_id = token_id[0]
        c = await self.client.contracts.get(contract_address=GOTCHIPUS_FREE)
        return await c.functions.ownerOf(int(token_id)).call()

    @controller_log("Gotchipus Flow")
    async def flow(self):
        bal = await self.check_gotchipus_free_ntf()
        ids = await self.get_gotchipus_tokens()

        if bal == 0:
            mint = await self.mint_gotchipus()
            if "Failed" not in mint:
                logger.success(mint)

        if not ids:
            try:
                s = await self.summon()
                if "Failed" not in s:
                    logger.success(s)

                mw = await self.mint_wearable()
                if "Failed" not in mw:
                    logger.success(mw)

            except Exception as e:
                logger.debug(f"Summon skip | {e}")

        ci = await self.can_check_in()
        if ci:
            ci = await self.check_in()
            if "Failed" not in ci:
                logger.info(ci)

        can = await self.can_check_pet()
        if can:
            p = await self.pet()
            if "Failed" not in p:
                logger.success(p)

        tr = await self.transfer_from_gotchipus()

        if "Failed" not in tr:
            logger.success(tr)

        await self.complete_tasks()
        return "Flow Done"
