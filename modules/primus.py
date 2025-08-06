import asyncio
import random
import string

from web3 import Web3
from web3.types import TxParams

from data.config import ABIS_DIR
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TxArgs, TokenAmount
from libs.eth_async.utils.files import read_json
from libs.eth_async.utils.utils import randfloat
from utils.db_api.models import Wallet
from utils.logs_decorator import action_log, controller_log

PRIMUS = RawContract(
    title="Primus",
    address="0xd17512b7ec12880bd94eca9d774089ff89805f02",
    abi=read_json((ABIS_DIR, "primus.json")),
)

class Primus(Base):
    __module_name__ = "Primus"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet



    @staticmethod
    def _rand_username(platform: str) -> str:
        prefix = "@" if platform in {"x", "tiktok"} else ""
        charset = string.ascii_lowercase + string.digits + "_"
        return prefix + "".join(random.choice(charset) for _ in range(random.randint(5, 12)))


    @controller_log("Tip Sender")
    async def tip(self) -> str:
        contract = await self.client.contracts.get(contract_address=PRIMUS)

        platform = random.choice(['x', 'tiktok'])
        username = self._rand_username(platform=platform)

        amount = TokenAmount(
            amount=randfloat(from_=0.000001, to_=0.00001, step=0.000001)
        )

        token_struct = {
            "tokenType": 1,
            "tokenAddress": "0x0000000000000000000000000000000000000000",
        }

        recipient_struct = {
            "idSource": platform,
            "id": username,
            "amount": amount.Wei,
            "nftIds": [],
        }

        data = contract.encode_abi("tip", args=[token_struct, recipient_struct])

        tx_params = TxParams(
            to=contract.address,
            data=data,
            value=amount.Wei,
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)

        await asyncio.sleep(random.randint(2, 4))

        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return f"Success send {amount.Ether} PHRS to {username}"

        return f"Failed send {amount.Ether} PHRS to {username}"