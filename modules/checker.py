import time
from datetime import datetime, timezone

from loguru import logger

from libs.base import Base
from libs.eth_async.client import Client
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db


class Checker(Base):
    __module__ = "Checker Pharos"
    BASE = "https://api.claim.pharos.xyz"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.jwt = None
        self.cookies = None
        self.proxy = client.proxy
        self.session = Browser(wallet=wallet)
        self.wallet = wallet

        self.base_headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "authorization": "Bearer null",
            "content-type": "application/json",
            "origin": "https://claim.pharos.xyz",
            "priority": "u=1, i",
            "referer": "https://claim.pharos.xyz/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }

    def __repr__(self):
        return f"{self.__module__} | [{self.client.account.address}]"

    async def _siwe_message(self) -> str:
        return "\n".join(
            (
                "Sign this message to authenticate with Pharos.",
                self.client.account.address,
                "",
                f"Wallet: {self.client.account.address}",
                f"",
                f"Timestamp: {int(time.time() * 1000)}",
            )
        )

    @staticmethod
    async def value_for_today(seq):
        idx = datetime.now(timezone.utc).weekday()

        items = [int(x) for x in seq] if isinstance(seq, str) else list(seq)
        if len(items) != 7:
            raise ValueError("seq must have 7 items")
        return items[idx]

    async def login(self):
        message = await self._siwe_message()

        sig = await self.sign_message(text=message)

        payload = {
            "address": self.client.account.address,
            "message": message,
            "signature": sig,
            "mode": "evm",
        }

        r = await self.session.post(
            url=f"{self.BASE}/accounts/sign_in_blockchain",
            headers=self.base_headers,
            json=payload,
            timeout=120,
        )

        r.raise_for_status()

        if r.json().get("data").get("verified"):
            self.jwt = r.json().get("data").get("token")
            self.cookies = r.cookies

        return r.json()

    async def check_token(self):
        await self.login()

        params = {
            "address": self.client.account.address,
        }

        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "authorization": f"TOKEN {self.jwt}",
            "origin": "https://claim.pharos.xyz",
            "referer": "https://claim.pharos.xyz/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }

        r = await self.session.get(
            url=f"{self.BASE}/airdrop/airdrop_info",
            params=params,
            headers=headers,
            cookies=self.cookies,
            timeout=120,
        )

        r.raise_for_status()

        if r.json().get("data"):
            logger.success(f"{self.wallet.id} | {self.client.account.address} | ELIGBLE | {r.json()}")
            self.wallet.eligble = True
            db.commit()

        else:
            logger.info(f"{self.wallet.id} | {self.client.account.address} | {r.json()} | Seems not eligble")

        return r.json()
