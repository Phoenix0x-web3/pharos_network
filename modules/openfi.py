import asyncio
import random

from loguru import logger
from web3.types import TxParams

from data.models import Contracts
from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import DefaultABIs, RawContract, TokenAmount, TxArgs
from libs.eth_async.utils.utils import randfloat
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log

abi_wrp = [
    {
        "inputs": [
            {"internalType": "address", "name": "weth", "type": "address"},
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "contract IPool", "name": "pool", "type": "address"},
        ],
        "stateMutability": "nonpayable",
        "type": "constructor",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "previousOwner", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "newOwner", "type": "address"},
        ],
        "name": "OwnershipTransferred",
        "type": "event",
    },
    {"stateMutability": "payable", "type": "fallback"},
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "uint256", "name": "interestRateMode", "type": "uint256"},
            {"internalType": "uint16", "name": "referralCode", "type": "uint16"},
        ],
        "name": "borrowETH",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "address", "name": "onBehalfOf", "type": "address"},
            {"internalType": "uint16", "name": "referralCode", "type": "uint16"},
        ],
        "name": "depositETH",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "emergencyEtherTransfer",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "emergencyTokenTransfer",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getWETHAddress",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {"inputs": [], "name": "renounceOwnership", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "uint256", "name": "rateMode", "type": "uint256"},
            {"internalType": "address", "name": "onBehalfOf", "type": "address"},
        ],
        "name": "repayETH",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "newOwner", "type": "address"}],
        "name": "transferOwnership",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "address", "name": "to", "type": "address"},
        ],
        "name": "withdrawETH",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
            {"internalType": "uint8", "name": "permitV", "type": "uint8"},
            {"internalType": "bytes32", "name": "permitR", "type": "bytes32"},
            {"internalType": "bytes32", "name": "permitS", "type": "bytes32"},
        ],
        "name": "withdrawETHWithPermit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {"stateMutability": "payable", "type": "receive"},
]
b_wphrs = "0x974828e18bff1E71780f9bE19d0DFf4Fe1f61fCa"
b_coin = "0x11d1ca4012d94846962bca2FBD58e5A27ddcBfC5"

oWPRH = RawContract(title="oWPRH", address="0x24bdfd3496a158977ee768f0802cb1bc0ff0ee34", abi=DefaultABIs.Token)
oUSDC = RawContract(title="oUSDC", address="0x5244c9452cf3168c55a0423ff946b5ad21b2a934", abi=DefaultABIs.Token)
oUSDT = RawContract(title="oUSDT", address="0xb0643e47a36616c5d6573486e3c7e49449628c9c", abi=DefaultABIs.Token)

LENDING_ABI = [
    {
        "type": "function",
        "name": "isMintable",
        "stateMutability": "view",
        "inputs": [{"internalType": "address", "name": "asset", "type": "address"}],
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "getUserReserveData",
        "stateMutability": "view",
        "inputs": [
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "address", "name": "user", "type": "address"},
        ],
        "outputs": [
            {"internalType": "uint256", "name": "currentBTokenBalance", "type": "uint256"},
            {"internalType": "uint256", "name": "currentStableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "currentVariableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "principalStableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "scaledVariableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "stableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidityRate", "type": "uint256"},
            {"internalType": "uint40", "name": "stableRateLastUpdated", "type": "uint40"},
            {"internalType": "bool", "name": "usageAsCollateralEnabled", "type": "bool"},
        ],
    },
    {
        "type": "function",
        "name": "getReserveConfigurationData",
        "stateMutability": "view",
        "inputs": [{"internalType": "address", "name": "asset", "type": "address"}],
        "outputs": [
            {"internalType": "uint256", "name": "decimals", "type": "uint256"},
            {"internalType": "uint256", "name": "ltv", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidationThreshold", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidationBonus", "type": "uint256"},
            {"internalType": "uint256", "name": "reserveFactor", "type": "uint256"},
            {"internalType": "bool", "name": "usageAsCollateralEnabled", "type": "bool"},
            {"internalType": "bool", "name": "borrowingEnabled", "type": "bool"},
            {"internalType": "bool", "name": "stableBorrowRateEnabled", "type": "bool"},
            {"internalType": "bool", "name": "isActive", "type": "bool"},
            {"internalType": "bool", "name": "isFrozen", "type": "bool"},
        ],
    },
    {
        "type": "function",
        "name": "getReserveData",
        "stateMutability": "view",
        "inputs": [{"internalType": "address", "name": "asset", "type": "address"}],
        "outputs": [
            {"internalType": "uint256", "name": "unbacked", "type": "uint256"},
            {"internalType": "uint256", "name": "accruedToTreasuryScaled", "type": "uint256"},
            {"internalType": "uint256", "name": "totalBToken", "type": "uint256"},
            {"internalType": "uint256", "name": "totalStableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "totalVariableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidityRate", "type": "uint256"},
            {"internalType": "uint256", "name": "variableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "stableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "averageStableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidityIndex", "type": "uint256"},
            {"internalType": "uint256", "name": "variableBorrowIndex", "type": "uint256"},
            {"internalType": "uint40", "name": "lastUpdateTimestamp", "type": "uint40"},
        ],
    },
    {
        "type": "function",
        "name": "mint",
        "stateMutability": "nonpayable",
        "inputs": [
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "depositETH",
        "stateMutability": "payable",
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "address", "name": "onBehalfOf", "type": "address"},
            {"internalType": "uint16", "name": "referralCode", "type": "uint16"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "supply",
        "stateMutability": "nonpayable",
        "inputs": [
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "address", "name": "onBehalfOf", "type": "address"},
            {"internalType": "uint16", "name": "referralCode", "type": "uint16"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "borrow",
        "stateMutability": "nonpayable",
        "inputs": [
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "uint256", "name": "interestRateMode", "type": "uint256"},
            {"internalType": "uint16", "name": "referralCode", "type": "uint16"},
            {"internalType": "address", "name": "onBehalfOf", "type": "address"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "repay",
        "stateMutability": "nonpayable",
        "inputs": [
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "uint256", "name": "interestRateMode", "type": "uint256"},
            {"internalType": "address", "name": "onBehalfOf", "type": "address"},
        ],
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "withdraw",
        "stateMutability": "nonpayable",
        "inputs": [
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "address", "name": "to", "type": "address"},
        ],
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
    },
    {
        "inputs": [{"internalType": "address", "name": "user", "type": "address"}],
        "name": "getUserAccountData",
        "outputs": [
            {"internalType": "uint256", "name": "totalCollateralBase", "type": "uint256"},
            {"internalType": "uint256", "name": "totalDebtBase", "type": "uint256"},
            {"internalType": "uint256", "name": "availableBorrowsBase", "type": "uint256"},
            {"internalType": "uint256", "name": "currentLiquidationThreshold", "type": "uint256"},
            {"internalType": "uint256", "name": "ltv", "type": "uint256"},
            {"internalType": "uint256", "name": "healthFactor", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

SUPPLY_MAP = {Contracts.PHRS: b_wphrs, Contracts.USDC: b_coin, Contracts.USDT: b_coin}


class OpenFi(Base):
    __module_name__ = "OpenFi"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        # self.session = Browser(wallet=wallet)
        #
        # self.base_headers = {
        #     "accept": "application/json, text/plain, */*",
        #     "accept-language": "en-US,en;q=0.9",
        #     "sec-gpc": "1",
        #     "referer": "https://faroswap.xyz/",
        # }

    async def balance_map(self, tokens: list):
        balance_map = {}
        for token in tokens:
            if token == Contracts.PHRS:
                balance = await self.client.wallet.balance()
                if balance.Ether == 0:
                    return "Failed | No balance, try to faucet first"
            else:
                balance = await self.client.wallet.balance(token.address)

            if balance.Ether > 0.1:
                balance_map[token] = balance.Ether

        return balance_map

    async def lending_controller(self):
        settings = Settings()

        percent_to_swap = randfloat(from_=settings.liquidity_percent_min, to_=settings.liquidity_percent_max, step=0.001) / 100

        tokens = [
            Contracts.PHRS,
            Contracts.USDT,
            Contracts.USDC,
        ]

        o_tokens = [oUSDC, oUSDT, oWPRH]

        balance_map = await self.balance_map(tokens)

        if not balance_map:
            return f"{self.wallet} | {self.__module_name__} | No balances try to faucet first"

        if all(float(value) == 0 for value in balance_map.values()):
            return "Failed | No balance in all tokens, try to faucet first"

        from_token = random.choice(list(balance_map.keys()))

        amount = float((balance_map[from_token])) * percent_to_swap

        amount = TokenAmount(amount=amount, decimals=18 if from_token == Contracts.PHRS else 6)

        actions = [lambda: self.supply(token=from_token, amount=amount)]
        allowance_borrow = await self.get_allowance_borrow()

        if allowance_borrow > 0.5:
            borrow_assets = [Contracts.USDT, Contracts.USDC]
            borrow_token = random.choice(borrow_assets)
            actions.append(
                lambda: self.borrow(token=borrow_token, amount=TokenAmount(amount=(allowance_borrow * percent_to_swap), decimals=6))
            )

        repay_amounts = await self.get_current_borrows()

        if repay_amounts:
            if all(float(value.Ether) > 0 for value in repay_amounts.values()):
                token, borrow_amount = random.choice(list(repay_amounts.items()))

                actions.append(
                    lambda: self.repay(token=token, amount=TokenAmount(amount=float(borrow_amount.Ether) * percent_to_swap, decimals=6))
                )

        action = random.choice(actions)

        return await action()

    async def _prepare_contract(self, address: str):
        return RawContract(title="COIN", address=address, abi=LENDING_ABI)

    @controller_log("Supply")
    async def supply(self, token: RawContract, amount: TokenAmount):
        contract = await self._prepare_contract(SUPPLY_MAP[token])
        contract = await self.client.contracts.get(contract_address=contract)

        from_token_is_phrs = token.address.upper() == Contracts.PHRS.address.upper()
        logger.debug(f"{self.wallet} | {self.__module_name__} | Trying to Supply {amount} {token.title}")
        if from_token_is_phrs:
            data = TxArgs(
                address=token.address,
                onBehalfOf=self.client.account.address,
                referralCode=0,
            ).tuple()

            encode = contract.encode_abi("depositETH", args=data)

        else:
            data = TxArgs(
                address=token.address,
                amount=amount.Wei,
                onBehalfOf=self.client.account.address,
                referralCode=0,
            ).tuple()

            encode = contract.encode_abi("supply", args=data)

        if not from_token_is_phrs:
            if await self.approve_interface(token_address=token.address, spender=contract.address, amount=None):
                await asyncio.sleep(2)
            else:
                return f" can not approve"

        tx_params = TxParams(to=contract.address, data=encode, value=amount.Wei if from_token_is_phrs else 0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if receipt:
            return f"Success supplied {amount.Ether:.5f} {token.title}"

        raise Exception(f"Failed to supply {amount.Ether:.5f} {token.title}")

    @controller_log("Borrow")
    async def borrow(self, token: RawContract, amount: TokenAmount):
        contract = await self._prepare_contract(SUPPLY_MAP[token])
        contract = await self.client.contracts.get(contract_address=contract)

        from_token_is_phrs = token.address.upper() == Contracts.PHRS.address.upper()

        logger.debug(f"{self.wallet} | {self.__module_name__} | Trying to Borrow {amount} {token.title}")

        if from_token_is_phrs:
            data = TxArgs(
                address=token.address,
                onBehalfOf=self.client.account.address,
                referralCode=0,
            ).tuple()

            encode = contract.encode_abi("borrow", args=data)

        else:
            data = TxArgs(
                address=token.address,
                amount=amount.Wei,
                onBehalfOf=self.client.account.address,
                referralCode=0,
            ).tuple()

            encode = contract.encode_abi("supply", args=data)

        if not from_token_is_phrs:
            if await self.approve_interface(token_address=token.address, spender=contract.address, amount=None):
                await asyncio.sleep(2)
            else:
                return f" can not approve"

        tx_params = TxParams(to=contract.address, data=encode, value=amount.Wei if from_token_is_phrs else 0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if receipt:
            return f"Success borrowed {amount.Ether:.5f} {token.title}"

        raise Exception(f"Failed to borrow {amount.Ether:.5f} {token.title}")

    @controller_log("Repay")
    async def repay(self, token: RawContract, amount: TokenAmount):
        contract = await self._prepare_contract(SUPPLY_MAP[token])
        contract = await self.client.contracts.get(contract_address=contract)

        from_token_is_phrs = token.address.upper() == Contracts.PHRS.address.upper()

        logger.debug(f"{self.wallet} | {self.__module_name__} | Trying to Repay {amount} {token.title}")

        if from_token_is_phrs:
            data = TxArgs(
                address=token.address,
                onBehalfOf=self.client.account.address,
                referralCode=0,
            ).tuple()

            encode = contract.encode_abi("repay", args=data)

        else:
            data = TxArgs(
                address=token.address,
                amount=amount.Wei,
                onBehalfOf=self.client.account.address,
                referralCode=0,
            ).tuple()

            encode = contract.encode_abi("repay", args=data)

        if not from_token_is_phrs:
            if await self.approve_interface(token_address=token.address, spender=contract.address, amount=None):
                await asyncio.sleep(2)
            else:
                return f" can not approve"

        tx_params = TxParams(to=contract.address, data=encode, value=amount.Wei if from_token_is_phrs else 0)

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if receipt:
            return f"Success borrowed {amount.Ether:.5f} {token.title}"

        raise Exception(f"Failed to borrow {amount.Ether:.5f} {token.title}")

    async def get_allowance_borrow(self):
        contract = await self._prepare_contract(b_coin)
        contract = await self.client.contracts.get(contract)
        data = await contract.functions.getUserAccountData(self.client.account.address).call()
        allowance_borrow = data[2] / 10**8

        return allowance_borrow

    async def get_current_borrows(self):
        provider = "0x54cb4f6C4c12105B48b11e21d78becC32Ef694EC"
        tokens = [Contracts.USDT, Contracts.USDC]
        contract = await self._prepare_contract(provider)
        contract = await self.client.contracts.get(contract)

        map = {}

        for token in tokens:
            data = await contract.functions.getUserReserveData(token.address, self.client.account.address).call()

            if data[2] > 1000:
                map[token] = TokenAmount(amount=data[2], decimals=6, wei=True)

        return map
