import asyncio
import json
import os
import random
import string

from loguru import logger
from requests import session
from web3 import Web3
from web3.types import TxParams
from hexbytes import HexBytes

from data.config import ABIS_DIR
from libs.base import Base
 
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount, TxArgs
from libs.eth_async.utils.files import read_json
from utils.db_api.models import Wallet
from utils.logs_decorator import action_log, controller_log
from utils.browser import Browser

NFT_ABI = [
    {
        "inputs": [
            {"name": "_receiver", "type": "address"},
            {"name": "_quantity", "type": "uint256"},
            {"name": "_currency", "type": "address"},
            {"name": "_pricePerToken", "type": "uint256"},
            {
                "components": [
                    {"name": "proof", "type": "bytes32[]"},
                    {"name": "quantityLimitPerWallet", "type": "uint256"},
                    {"name": "pricePerToken", "type": "uint256"},
                    {"name": "currency", "type": "address"}
                ],
                "name": "_allowlistProof",
                "type": "tuple"
            },
            {"name": "_data", "type": "bytes"}
        ],
        "name": "claim",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

PHAROSWAP_BADGE = RawContract(
    title="Pharoswap Badge",
    address="0x2a469a4073480596b9deb19f52aa89891ccff5ce",
    abi=NFT_ABI,
)


GOTCHIPUS = RawContract(
    title="GotChipus",
    address="0xb2ac4f09735007562c513ebbe152a8d7fa682bef",
    abi=NFT_ABI,
)

SPOUT = RawContract(
    title="Spout",
    address="0x96381ed3fcfb385cbacfe6908159f0905b19767a",
    abi=NFT_ABI,
)

ZENTRA = RawContract(
    title="Zentra",
    address="0xe71188df7be6321ffd5aaa6e52e6c96375e62793",
    abi=NFT_ABI,
)

PTB = RawContract(
    title="PTB",
    address="0x1Da9f40036beE3Fda37ddd9Bff624E1125d8991D",
    abi=NFT_ABI,
)

ASTB = RawContract(
    title="ASTB",
    address="0x0d00314d006e70ca08ac37c3469b4bf958a7580b",
    abi=NFT_ABI,
)
PNS = RawContract(
    title="PNS",
    address="0x4af366c7269DC9a0335Bd055Af979729c20e0F5F",
    abi=NFT_ABI,
)  
BROKEX  = RawContract(
    title="BROKEX ",
    address="0x9979b7fedf761c2989642f63ba6ed580dbdfc46f",
    abi=NFT_ABI,
)

OPENFI = RawContract(
    title="OPENFI",
    address="0x822483f6cf39b7dad66fec5f4feecbfd72172626",
    abi=NFT_ABI,
)



class NFTS(Base):
    __module_name__ = "Mint NFTs"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = Browser(wallet=wallet)
        self.headers = {
            "Accept": "application/json, text/plain, */*",
        }

    async def check_mint(self, contract: RawContract = None):
        c = await self.client.contracts.get(contract_address=contract)
        balance = await c.functions.balanceOf(self.client.account.address).call()

        return balance


    async def mint_nft(self, contract: RawContract = None):
        c = await self.client.contracts.get(contract_address=contract)
        amount = TokenAmount(amount=1)
        allowlist_proof = TxArgs(
            proof=[],
            quantityLimitPerWallet=0,
            pricePerToken=(2**256 - 1),
            currency=Web3.to_checksum_address("0x0000000000000000000000000000000000000000"),
        ).tuple()

        data = TxArgs(
            _receiver=self.client.account.address,
            _quantity=int(1),
            _currency=Web3.to_checksum_address("0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"),
            _pricePerToken=amount.Wei,
            _allowlistProof=allowlist_proof,
            _data=b"",
        ).tuple()

        data = c.encode_abi("claim", args=data)

        tx = await self.client.transactions.sign_and_send(TxParams(
            to=c.address,
            data=data,
            value=amount.Wei
        ))

        await asyncio.sleep(2)

        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
        return f"Success | Minted {contract.title}" if rcpt else f"Failed | Mint {contract.title}"

    async def check_badges(self):
        nfts = [
            PHAROSWAP_BADGE,
            PTB,
            ASTB,
            ZENTRA,
            SPOUT,
            GOTCHIPUS,
            PNS,
            BROKEX,
            OPENFI
        ]

        not_minted = []

        for nft in nfts:
            balance = await self.check_mint(contract=nft)
            if balance == 0:
                not_minted.append(nft)

        return not_minted

    @controller_log("Mint NFT Badge")
    async def nfts_controller(self, not_minted: list = None):

        if not not_minted:
            not_minted = await self.check_badges()

        if not not_minted:
            return 'Already Minted All Badges'

        nft = random.choice(not_minted)

        return await self.mint_nft(contract=nft)
    