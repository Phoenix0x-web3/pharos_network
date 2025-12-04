import asyncio
import random
from modules.faroswap import Faroswap

from web3.types import TxParams

from data.models import Contracts
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount, TxArgs
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.retry import async_retry

ZENITH_ABI = [
    {
        "type": "function",
        "name": "supply",
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "address", "type": "address"},
            {"name": "param4", "type": "uint16"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
    }
]
ZENITH_LIQ = RawContract(title="Zenith_liq", address="0x62E72185F7DEAbdA9f6a3Df3B23D67530b42eFf6", abi=ZENITH_ABI)


class ZenithNew(Faroswap):
    __module_name__ = "ZenithNew"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.headers = {
            "accept": "*/*",
            "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "content-type": "application/json",
            "origin": "https://testnet.zenithswap.xyz",
            "referer": "https://testnet.zenithswap.xyz/",
        }
        self.session = Browser(wallet=wallet)
        self.base_headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "sec-gpc": "1",
            "referer": "https://faroswap.xyz/",
        }

    @async_retry()
    async def liquidity_controller(self):
        tokens_for_liq = [Contracts.WBTC, Contracts.WETH]
        tokens_with_balance = []
        for token in tokens_for_liq:
            balance = await self.client.wallet.balance(token=token)
            if int(balance.Wei) > 0:
                tokens_with_balance.append(token)
        if not tokens_with_balance:
            swap = await self.swap_controller(to_token=random.choice(tokens_for_liq), from_token=Contracts.PHRS)
            if "Failed" in swap:
                raise Exception(f"{self.wallet} can't swap token for add liquidity in zenith")
            return await self.liquidity_controller()
        return await self.add_liquidity(token_liq=random.choice(tokens_with_balance))

    async def add_liquidity(self, token_liq: RawContract):
        c = await self.client.contracts.get(contract_address=ZENITH_LIQ)
        balance = await self.client.wallet.balance(token=token_liq)
        amount = TokenAmount(random.uniform(float(balance.Ether) // 2, float(balance.Ether)))
        if await self.approve_interface(token_address=token_liq.address, spender=ZENITH_LIQ.address, amount=None):
            await asyncio.sleep(random.randint(2, 5))
        else:
            raise Exception(f"{self.wallet} can not approve {token_liq.title} for add zenith liquidity")
        tx_args = TxArgs(token=token_liq.address, amount=amount.Wei, address=self.client.account.address, param4=0)
        data = c.encode_abi("supply", args=tx_args.tuple())
        tx_params = TxParams(to=c.address, data=data)
        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if receipt:
            return f"Success Add Liq {amount.Ether:.5f} {token_liq.title} to Zenith"

        return f"Failed Add Liq {amount.Ether:.5f} {token_liq.title} to Zenith"
