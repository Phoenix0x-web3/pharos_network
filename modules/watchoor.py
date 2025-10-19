import asyncio
import random

from eth_abi import encode
from faker import Faker
from web3.types import TxParams

from data.rpc import RPC_MAP
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import TokenAmount
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log


class Watchoor(Base):
    __module_name__ = "Watchoor"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.browser = Browser(wallet=wallet)

    def encode_exact(self, selector_hex: str, name: str, symbol: str) -> str:
        selector = bytes.fromhex(selector_hex.replace("0x", ""))
        encoded = encode(["string", "string", "uint256"], [name, symbol, 0])
        return "0x" + (selector + encoded).hex()

    def generate_name_and_symbol(self, base: str) -> tuple[str, str]:
        name = base.strip().title()
        symbol = "".join(ch for ch in base.upper() if ch.isalpha())[:4]
        return name, symbol

    async def check_contract(self, mint_signature: str) -> bool:
        if mint_signature == "0xa094fd7c":
            signature = "0xce39e562"
        else:
            signature = "0x28d249fe"
        json_data = {
            "jsonrpc": "2.0",
            "id": random.randint(1, 100),
            "method": "eth_call",
            "params": [
                {
                    "data": f"{signature}000000000000000000000000{self.wallet.address[2:]}",
                    "to": "0xF3bF0736DDf31da6a542c7cF97652F4D0835B9d3",
                },
                "latest",
            ],
        }
        response = await self.browser.post(url=f"{RPC_MAP['pharos']}", json=json_data)
        data = response.json()
        if data["result"] == "0x0000000000000000000000000000000000000000000000000000000000000000":
            return False
        return True

    async def get_contract_mint_signature(self):
        mint_nft_erc_sig = ["0xa094fd7c", "0xd4773b5f"]
        random.shuffle(mint_nft_erc_sig)
        for sig in mint_nft_erc_sig:
            already_mint = await self.check_contract(sig)
            if not already_mint:
                return sig
        return None

    @controller_log("Contract Mint")
    async def contract_mint(self, signature) -> str:
        if signature == "0xa094fd7c":
            name_mint = "NFT"
        else:
            name_mint = "ERC20"
        faker = Faker()
        name, symbol = self.generate_name_and_symbol(base=faker.cryptocurrency_name())
        data = self.encode_exact(selector_hex=signature, name=name, symbol=symbol)

        amount = TokenAmount(amount=0.25)
        to = self.client.w3.to_checksum_address("0xf3bf0736ddf31da6a542c7cf97652f4d0835b9d3")
        tx_params = TxParams(
            to=to,
            data=data,
            value=amount.Wei,
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)

        await asyncio.sleep(random.randint(2, 4))

        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success mint {name_mint} contract {name}({symbol}) for {amount.Ether} PHRS"

        return f"Failed mint {name_mint} contract {name}({symbol}) for {amount.Ether} PHRS"
