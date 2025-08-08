import asyncio
import base64
import json
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from requests import session
from web3 import Web3
from web3.types import TxParams
from yaml import add_implicit_resolver

from data.config import ABIS_DIR
from data.models import Contracts
from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import TokenAmount, TxArgs, RawContract, DefaultABIs
from libs.eth_async.utils.files import read_json
from libs.twitter.base import BaseAsyncSession
from utils.db_api.models import Wallet
from utils.logs_decorator import action_log, controller_log
from utils.retry import async_retry

PUBLIC_KEY_PEM = """
-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDWPv2qP8+xLABhn3F/U/hp76HP
e8dD7kvPUh70TC14kfvwlLpCTHhYf2/6qulU1aLWpzCz3PJr69qonyqocx8QlThq
5Hik6H/5fmzHsjFvoPeGN5QRwYsVUH07MbP7MNbJH5M2zD5Z1WEp9AHJklITbS1z
h23cf2WfZ0vwDYzZ8QIDAQAB
-----END PUBLIC KEY-----
""".strip()

RPC_URL = "https://testnet.dplabs-internal.com/"
BASE_API = 'https://asia-east2-auto-staking.cloudfunctions.net'

USDC = RawContract(
    title="USDC",
    address="0x72df0bcd7276f2dFbAc900D1CE63c272C4BCcCED",
    abi=DefaultABIs.Token
)

USDT = RawContract(
    title="USDT",
    address="0xD4071393f8716661958F766DF660033b3d35fD29",
    abi=DefaultABIs.Token
)

AUTOSTAKING_CONTRACT_ABI = [
    {
        "type": "function",
        "name": "getNextFaucetClaimTime",
        "stateMutability": "view",
        "inputs": [
            {"name": "user", "type": "address"}
        ],
        "outputs": [
            {"name": "", "type": "uint256"}
        ],
    }
]

ERC_20_WITH_FAUCET_ABI = [
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "address", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "allowance",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "approve",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "decimals",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
    {
        "type": "function",
        "name": "claimFaucet",
        "stateMutability": "nonpayable",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]

MUSD = RawContract(
    title="MockUSD",
    address="0x7F5e05460F927Ee351005534423917976F92495e",
    abi=ERC_20_WITH_FAUCET_ABI,
)

mvMUSD = RawContract(
    title="mvMUSD",
    address="0xF1CF5D79bE4682D50f7A60A047eACa9bD351fF8e",
    abi=ERC_20_WITH_FAUCET_ABI,
)

AUTOSTAKING_READ = RawContract(
    title="AutostakingReader",
    address=mvMUSD.address,
    abi = AUTOSTAKING_CONTRACT_ABI,
)

STAKING_ROUTER = RawContract(
    title="StakingRouter",
    address="0x11cD3700B310339003641Fdce57c1f9BD21aE015",
    abi=ERC_20_WITH_FAUCET_ABI,
)


BALANCED = (
    "1. Mandatory Requirement: The product's TVL must be higher than one million USD.\n"
    "2. Balance Preference: Prioritize products that have a good balance of high current APY and high TVL.\n"
    "3. Portfolio Allocation: Select the 3 products with the best combined ranking in terms of current APY and TVL "
    "among those with TVL > 1,000,000 USD. To determine the combined ranking, rank all eligible products by current "
    "APY (highest to lowest) and by TVL (highest to lowest), then sum the two ranks for each product. Choose the 3 "
    "products with the smallest sum of ranks. Allocate the investment equally among these 3 products, with each "
    "receiving ~33.3% of the investment."
)
CONCERVATIVE = (
    "1. Must: TVL > $1,000,000.\n"""
    "2. Priority: Highest TVL for max safety.\n"
    "3. Allocation: Select top 3 products by TVL (TVL > $1,000,000), distribute total investment proportionally to TVL (e.g., X/(X+Y+Z), Y/(X+Y+Z), Z/(X+Y+Z)), where X, Y, Z are TVLs, ensuring higher TVL gets larger share."
)
AGGRESIVE = (
"1. Must: TVL > $1,000,000.\n"
"2. Priority: Highest current APY for max ROI.\n"
"3. Allocation: Pick top 3 products (TVL > $1,000,000) by APY, distribute investment proportionally to APY (e.g., A/(A+B+C), B/(A+B+C), C/(A+B+C)), where A, B, C are APYs, ensuring higher APY gets larger share."

)

PROMPT = [
    CONCERVATIVE,
    BALANCED,
    AGGRESIVE
]

class AutoStaking(Base):
    __module_name__ = "AutoStaking"

    def __init__(self, client: Client, wallet: Wallet, *, proxy: Optional[str] = None):
        self.client = client
        self.wallet = wallet
        self.proxy = proxy
        self.session = BaseAsyncSession(proxy=self.wallet.proxy)
        self.base_headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://autostaking.pro",
            "Referer": "https://autostaking.pro/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "authorization": self._auth_token()
        }

    def _auth_token(self) -> str:
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.backends import default_backend

        pub = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode("ascii"), backend=default_backend())
        plaintext = self.client.account.address.encode("ascii")

        ciphertext = pub.encrypt(
            plaintext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return base64.b64encode(ciphertext).decode("ascii")

    def _payload_recommendation(
            self, usdc_amount: float,
            usdt_amount: float,
            musd_amount: float,
            user_positions: list = None) -> Dict[str, Any]:

        to_units = lambda v: str(int(v * 10 ** 6))

        return {
            "user": self.client.account.address,
            "profile": random.choice(PROMPT),
            "userPositions": user_positions if user_positions else [],
            "userAssets": [
                {
                    "chain": {"id": self.client.network.chain_id},
                    "name": "USDC",
                    "symbol": "USDC",
                    "decimals": 6,
                    "address": USDC.address,
                    "assets": to_units(usdc_amount),
                    "price": 1,
                    "assetsUsd": usdc_amount,
                },
                {
                    "chain": {"id": self.client.network.chain_id},
                    "name": "USDT",
                    "symbol": "USDT",
                    "decimals": 6,
                    "address": USDT.address,
                    "assets": to_units(usdt_amount),
                    "price": 1,
                    "assetsUsd": usdt_amount,
                },
                {
                    "chain": {"id": self.client.network.chain_id},
                    "name": "MockUSD",
                    "symbol": "MockUSD",
                    "decimals": 6,
                    "address": MUSD.address,
                    "assets": to_units(musd_amount),
                    "price": 1,
                    "assetsUsd": musd_amount,
                },
            ],
            "chainIds": [self.client.network.chain_id],
            "tokens": ["USDC", "USDT", "MockUSD"],
            "protocols": ["MockVault"],
            "env": "pharos",
        }

    def _payload_change_txs(self, change_tx: Any) -> Dict[str, Any]:
        return {
            "user": self.client.account.address,
            "changes": change_tx,
            "prevTransactionResults": {},
        }

    async def get_next_faucet_claim_time(self) -> Optional[int]:
        contract = await self.client.contracts.get(contract_address=AUTOSTAKING_READ)
        next_time = await contract.functions.getNextFaucetClaimTime(self.client.account.address).call()
        return int(next_time)

    action_log('Faucet')
    async def claim_faucet(self) -> Optional[str]:

        contract = await self.client.contracts.get(contract_address=mvMUSD)
        data = contract.encode_abi("claimFaucet", args=[])

        tx_params = TxParams(
            to=mvMUSD.address,
            data=data,
            value=0
        )
        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return "Success MocUSD Faucet"


        return "Failed MocUSD Faucet"

    @async_retry(retries=3, delay=3, to_raise=False)
    async def _financial_portfolio_recommendation(
        self,
            usdc_amount: float,
            usdt_amount: float,
            musd_amount: float,
            user_positions: list = None
    ) -> Optional[Dict[str, Any]]:

        r = await self.session.post(
            url=f"{BASE_API}/auto_staking_pharos/investment/financial-portfolio-recommendation",
            json=self._payload_recommendation(usdc_amount, usdt_amount, musd_amount, user_positions=user_positions),

            headers=self.base_headers,
            timeout=300,
        )
        r.raise_for_status()

        if r.status_code >= 400:
            logger.error(f"{self.wallet} | Portfolio HTTP {r.status_code}: {r.text[:256]}")
            return None
        try:
            data = r.json()

        except Exception:
            data = json.loads(r.text or "{}")

        if not data or "data" not in data:
            logger.error(f"{self.wallet} | Invalid portfolio response: {data}")
            return None
        return data

    @async_retry(retries=5, delay=3, to_raise=False)
    async def _get_user_positions(self):
        url = f"{BASE_API}/auto_staking_pharos/user/positions?user={self.client.account.address}&env=pharos"

        r = await self.session.get(
            url=url,
            headers=self.base_headers,
            timeout=120,
        )
        r.raise_for_status()

        return r.json()

    async def stable_coins_balances(self) -> dict:
        settings = Settings()

        stables = [
            Contracts.USDT,
            Contracts.USDC,
            MUSD
        ]

        balance_map = {}

        for stable in stables:
            percent = random.randint(settings.stake_percent_min, settings.stake_percent_max)

            balance = await self.client.wallet.balance(token=stable)
            balance_map[stable] = float(balance.Ether) * percent

        return balance_map

    @async_retry(retries=10, delay=5, to_raise=False)
    async def _generate_change_transactions(self, change_tx: Any) -> dict:

        payload = self._payload_change_txs(change_tx)

        r = await self.session.post(
            url=f"{BASE_API}/auto_staking_pharos/investment/generate-change-transactions",
            headers=self.base_headers,
            json=payload,
            timeout=120,
        )

        r.raise_for_status()

        try:
            data = r.json()

        except Exception:
            data = json.loads(r.text or "{}")
        chain_data = data.get('data')

        if not chain_data:
            raise Exception(f"No calldata in response: {data}")

        return chain_data

    async def send_raw_tx(self, data):

        tx_params = TxParams(
            to=Web3.to_checksum_address(data['to']),
            data=data['data'],
            value=0
        )
        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)

        await asyncio.sleep(random.randint(2, 4))
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)

        if receipt:
            return tx.hash.hex() if hasattr(tx.hash, "hex") else str(tx.hash)


    async def autostacking_flow(self):

        next_time = await self.get_next_faucet_claim_time()

        now = int(time.time())

        if now >= next_time:
            faucet = await self.claim_faucet()

            if 'Failed' not in faucet:
                logger.success(faucet)

        current_position = await self._get_user_positions()

        current_position = current_position.get('positions')

        logger.debug(f"{self.wallet} | got current_positions")

        balance_map = await self.stable_coins_balances()

        ai_req = await self._financial_portfolio_recommendation(
            usdc_amount=balance_map[Contracts.USDC],
            usdt_amount=balance_map[Contracts.USDT],
            musd_amount=balance_map[MUSD],
            user_positions=current_position
        )

        return await self.prepare_transactions(ai_req=ai_req)

    async def prepare_transactions(self, ai_req: dict):
        changes = ai_req.get('data').get('changes')

        withdraw_tasks = 0
        deposit_tasks = 0

        withdraw = [task for task in changes if task.get('type') == 'withdraw']
        if withdraw:
            result = await self.process_transactions(tx_list=withdraw)
            withdraw_tasks += result

        deposit = [task for task in changes if task.get('type') == 'deposit']

        if deposit:
            result = await self.process_transactions(tx_list=deposit)
            deposit_tasks += result

        return f"Autostake Completed [Withdrawls: {withdraw_tasks}, Deposits: {deposit_tasks}]"

    async def process_transactions(self, tx_list: list, tx_count: int = 0):
        settings = Settings()
        changes = await self._generate_change_transactions(change_tx=tx_list)
        last_tx = {}

        sleep = random.randint(settings.random_pause_between_actions_min, settings.random_pause_between_actions_max)

        for key, value in changes.items():
            tx = await self.send_raw_tx(data=value)
            last_tx = value
            logger.debug(f'{self.wallet} | tx_success: {tx}, start sleeping for {sleep} secs')
            tx_count += 1

            await asyncio.sleep(sleep)

        if '0x095ea7' in last_tx.get('data'):
            return await self.process_transactions(tx_list=tx_list, tx_count=tx_count)

        return tx_count