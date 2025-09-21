import asyncio
import random
import time

import aiohttp
from eth_account.messages import encode_defunct, encode_typed_data, _hash_eip191_message
from hexbytes import HexBytes
from loguru import logger
from web3.types import TxParams

from libs.eth_async.client import Client
from libs.eth_async.data.models import TokenAmount, TxArgs, Networks
from libs.eth_async.utils.utils import randfloat

from data.models import Contracts
from utils.browser import BaseAsyncSession, Browser
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log


class Base:
    __module__ = 'Web3 Base'
    def __init__(self, client: Client, wallet: Wallet):
        self.client: Client = client
        self.wallet: Wallet = wallet
        self.browser: Browser = Browser(wallet=self.wallet)

    async def balance_map(self, tokens: list):
        balance_map = {}
        for token in tokens:
            if token == Contracts.PHRS:
                balance = await self.client.wallet.balance()
            else:
                balance = await self.client.wallet.balance(token.address)

            if balance.Ether > 0.001:
                balance_map[token.title] = balance.Ether

        return balance_map

    async def get_token_price(self, token_symbol='ETH', second_token: str = 'USDT') -> float | None:
        token_symbol, second_token = token_symbol.upper(), second_token.upper()

        if token_symbol.upper() in ('USDC', 'USDC.E', 'USDT', 'DAI', 'CEBUSD', 'BUSD'):
            return 1
        if token_symbol == 'WETH':
            token_symbol = 'ETH'
        if token_symbol == 'USDC.E':
            token_symbol = 'USDC'

        for _ in range(5):
            try:
                async with self.browser:
                    r = await self.browser.get(
                            url = f'https://api.binance.com/api/v3/depth?limit=1&symbol={token_symbol}{second_token}')
                    if r.status_code != 200:
                        return None
                    result_dict = r.json()
                    if 'asks' not in result_dict:
                        return None
                    return float(result_dict['asks'][0][0])
            except Exception as e:
                await asyncio.sleep(5)
        raise ValueError(f'Can not get {token_symbol + second_token} price from Binance')

    async def approve_interface(self, token_address, spender, amount: TokenAmount | None = None) -> bool:
        balance = await self.client.wallet.balance(token=token_address)
        if balance.Wei <= 0:
            return False

        if not amount or amount.Wei > balance.Wei:
            amount = balance

        approved = await self.client.transactions.approved_amount(
            token=token_address,
            spender=spender,
            owner=self.client.account.address
        )

        if amount.Wei <= approved.Wei:
            return True

        #print(f'Trying to approve: {token_address} {amount.Ether} - {amount.Wei}')

        tx = await self.client.transactions.approve(
            token=token_address,
            spender=spender,
            amount=amount
        )

        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if receipt:
            return True

        return False

    async def get_token_info(self, contract_address):
        contract = await self.client.contracts.default_token(contract_address=contract_address)
        print('name:', await contract.functions.name().call())
        print('symbol:', await contract.functions.symbol().call())
        print('decimals:', await contract.functions.decimals().call())

    @staticmethod
    def parse_params(params: str, has_function: bool = True):
        if has_function:
            function_signature = params[:10]
            print('function_signature', function_signature)
            params = params[10:]
        while params:
            print(params[:64])
            params = params[64:]


    async def sign_message(
            self,
            text: str = None,
            typed_data: dict = None,
            hash: bool = False
    ):
        if text:
            message = encode_defunct(text=text)
        elif typed_data:
            message = encode_typed_data(full_message=typed_data)
            if hash:
                message = encode_defunct(hexstr=_hash_eip191_message(message).hex())

        signed_message = self.client.account.sign_message(message)

        signature = signed_message.signature.hex()

        if not signature.startswith('0x'): signature = '0x' + signature
        return signature


    async def send_eth(self, to_address, amount: TokenAmount):

        tx_params = TxParams(
            to=to_address,
            data='0x',
            value=amount.Wei
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return receipt
            return (f'Balance Sender | Success send {amount.Ether:.5f} ETH to {to_address}')
        else:
            return f'Balance Sender | Failed'

    async def wait_tx_status(self, tx_hash: HexBytes, max_wait_time=100) -> bool:
        start_time = time.time()
        while True:
            try:
                receipts = await self.client.w3.eth.get_transaction_receipt(tx_hash)
                status = receipts.get("status")
                if status == 1:
                    return True
                elif status is None:
                    await asyncio.sleep(0.3)
                else:
                    return False
            except BaseException:
                if time.time() - start_time > max_wait_time:
                    logger.exception(f'{self.client.account.address} получил неудачную транзакцию')
                    return False
                await asyncio.sleep(3)

    async def wrap_eth(self, amount: TokenAmount = None):

            success_text = f'BASE | Wrap ETH | Success | {amount.Ether:.5f} ETH'
            failed_text = f'BASE | Wrap ETH | Failed | {amount.Ether:.5f} ETH'

            if self.client.network == Networks.Ethereum:
                weth =Contracts.WETH_ETHEREUM
            else:
                weth = Contracts.WETH

            contract = await self.client.contracts.get(contract_address=weth)

            encode = contract.encode_abi("deposit", args=[])
            #print(encode)
            tx_params = TxParams(
                to=contract.address,
                data=encode,
                value=amount.Wei
            )

            tx_label = f"Wrapped {amount.Ether:.5f}"

            tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
            await asyncio.sleep(random.randint(2, 4))
            receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

            if receipt:

                return tx_label

    async def unwrap_eth(self, amount: TokenAmount = None):

            if self.client.network == Networks.Ethereum:
                weth =Contracts.WETH_ETHEREUM
            if self.client.network == Networks.PharosTestnet:
                weth =Contracts.WPHRS
            else:
                weth = Contracts.WETH

            if not amount:
                amount = await self.client.wallet.balance(token=weth)

            contract = await self.client.contracts.get(contract_address=weth)

            data = TxArgs(
                wad = amount.Wei
            ).tuple()

            encode = contract.encode_abi("withdraw", args=data)
            #print(encode)
            tx_params = TxParams(
                to=contract.address,
                data=encode,
                value=0
            )

            tx_label = f"Unwrapper {amount.Ether:.5f}"

            tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
            await asyncio.sleep(random.randint(2, 4))
            receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

            if receipt:

                return tx_label