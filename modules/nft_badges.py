import asyncio
import random

from web3 import Web3
from web3.types import TxParams

from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount, TxArgs
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log

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
                    {"name": "currency", "type": "address"},
                ],
                "name": "_allowlistProof",
                "type": "tuple",
            },
            {"name": "_data", "type": "bytes"},
        ],
        "name": "claim",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

PHAROS_ATLANTIC_BADGE = RawContract(
    title="PHAROS",
    address="0x22614Ca3393E83DA6411A45f012239Bafc258ABD",
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
        amount = TokenAmount(amount=0.1)
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

        tx = await self.client.transactions.sign_and_send(TxParams(to=c.address, data=data, value=amount.Wei))

        await asyncio.sleep(2)

        rcpt = await tx.wait_for_receipt(client=self.client, timeout=300)
        return f"Success | Minted {contract.title}" if rcpt else f"Failed | Mint {contract.title}"

    async def check_badges(self):
        nfts = [PHAROS_ATLANTIC_BADGE]

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
            return "Already Minted All Badges"

        nft = random.choice(not_minted)

        return await self.mint_nft(contract=nft)
