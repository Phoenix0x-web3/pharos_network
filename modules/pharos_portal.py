import random
import secrets

from loguru import logger
from curl_cffi import requests

from data.settings import Settings
from libs.base import Base
from libs.baseAsyncSession import BaseAsyncSession
from libs.eth_async.client import Client

import datetime as dt
from urllib.parse import urlparse, parse_qs, unquote

from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log, action_log
from utils.twitter.twitter_client import TwitterClient
from utils.twitter.twitter_oauth import Twitter


class PharosPortal(Base):

    __module__ = 'Pharos Portal'
    BASE = "https://api.pharosnetwork.xyz"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.api_key = None
        self.user_id = None
        self.proxy = client.proxy
        self.chat_id = None
        self.cookies = {}
        self.jwt = None
        self.auth = False
        self.wallet = wallet
        self.session = BaseAsyncSession(proxy=self.proxy)
        self.twitter = TwitterClient(user=self.wallet)
        # self.twitter = Twitter(
        #     auth_token=twitter_token,
        #     address=self.client.account.address,
        #     version='136',
        #     session=self.session
        # )

        self.base_headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'authorization': 'Bearer null',
            'content-type': 'application/json',
            'origin': 'https://testnet.pharosnetwork.xyz',
            'priority': 'u=1, i',
            'referer': 'https://testnet.pharosnetwork.xyz/',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
        }

    def __repr__(self):
        return f'{self.__module__} | [{self.client.account.address}]'

    def _siwe_message(self, nonce: int) -> tuple[str, str]:

        issued_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        return "\n".join(
            [
                "testnet.pharosnetwork.xyz wants you to sign in with your Ethereum account:",
                self.client.account.address,
                "",
                "I accept the Pharos Terms of Service: testnet.pharosnetwork.xyz/privacy-policy/Pharos-PrivacyPolicy.pdf",
                "",
                "URI: https://testnet.pharosnetwork.xyz",
                "",
                "Version: 1",
                "",
                "Chain ID: 688688",
                "",
                f"Nonce: {nonce}",
                "",
                f"Issued At: {issued_at}",
            ]
        ), issued_at


    async def login(self, registration=False):
        settings = Settings()
        nonce = await self.client.wallet.nonce()

        message, timestamp = self._siwe_message(nonce=nonce)
        sig = await self.sign_message(text=message)

        invite_code = random.choice(settings.invite_codes)

        payload = {
            'address': self.client.account.address,
            'signature': sig,
            'wallet': self.wallet.wallet_type,
            'nonce': str(nonce),
            'invite_code': invite_code,
            'chain_id': '688688',
            'timestamp': timestamp,
            'domain': 'testnet.pharosnetwork.xyz',
        }

        if not registration or len(settings.invite_codes) == 0:
            payload.pop('invite_code')

        r = await self.session.post(
            f"{self.BASE}/user/login",
            headers=self.base_headers,
            json=payload,
            timeout=120,
        )

        r.raise_for_status()
        if r.json().get('data').get('jwt'):

            self.jwt = r.json().get('data').get('jwt')
            self.cookies = r.cookies
            self.auth = True
            logger.debug(f"{self.wallet} | Success Login to PharosNetwork")

        return r.json()

    async def get_twitter_link(self):
        headers = {
            **self.base_headers,
            'Host': 'api.pharosnetwork.xyz',
        }

        r = await self.session.get(
            f"{self.BASE}/auth/twitter",
            headers=headers,
            allow_redirects=False,
            timeout=120,
        )

        parsed_url = urlparse(r.headers.get('location'))

        return r.headers.get('location')


    @action_log('Bind Twitter')
    async def bind_twitter(self, redirect_url: str):

        parsed = urlparse(redirect_url)
        query_raw = parse_qs(parsed.query)

        query = {k: unquote(v[0]) for k, v in query_raw.items()}

        headers = {
            **self.base_headers,
            'authorization': f'Bearer {self.jwt}',
            'Host': 'api.pharosnetwork.xyz',
        }

        payload = {
            **query,
            'address': self.client.account.address
        }

        r = await self.session.post(
            f"{self.BASE}/auth/bind/twitter",
            headers=headers,
            json=payload,
            timeout=120,
        )

        r.raise_for_status()

        if r.json().get('code') == 0:
            data = r.json().get('data')

            return f"{r.json().get('msg')}: user_name: {data.get('username')}, id[{data.get('twitterID')}]"

        raise Exception(f"Failed: {r.get('msg')}")

    @action_log('Faucet')
    async def faucet(self):
        if not self.auth:
            await self.login()

        await self.check_in()

        faucet_status = await self.get_faucet_status()

        if faucet_status.get('data').get('is_able_to_faucet'):
            headers = {
                **self.base_headers,
                'authorization': f'Bearer {self.jwt}',
            }

            payload = {
                'address': self.client.account.address,
            }

            r = await self.session.post(
                f"{self.BASE}/faucet/daily",
                headers=headers,
                # cookies=self.cookies,
                json=payload,
                timeout=120,
            )

            return f"Success | {r.json()}"

        return f"Failed | {faucet_status}"

    async def get_faucet_status(self) -> dict:

        if not self.auth:
            await self.login()

        headers = {
            **self.base_headers,
            'authorization': f'Bearer {self.jwt}',
        }

        params = {
            'address': self.client.account.address,
        }

        r = await self.session.get(
            url = f"{self.BASE}/faucet/status",
            headers=headers,
            params=params
        )

        return r.json()

    async def get_user_info(self) -> dict:
        if not self.auth:
            await self.login()

        headers = {
            **self.base_headers,
            'authorization': f'Bearer {self.jwt}',
        }

        params = {
            'address': self.client.account.address,
        }

        r = await self.session.get(
            url = f"{self.BASE}/user/profile",
            headers=headers,
            # cookies=self.cookies,
            params=params,
            timeout=120,
        )
        #logger.success(f"User info | {r.json()}")

        r.raise_for_status()

        if r.json().get('msg') == 'ok':

            data = r.json().get('data').get('user_info')

            return data

    @action_log('Twitter Bind')
    async def bind_twitter_task(self):

        if not self.auth:
            await self.login()

        auth_url = await self.get_twitter_link()

        bind_url = await self.twitter.connect_twitter_to_site_oauth2(twitter_auth_url=auth_url)

        bind = await self.bind_twitter(redirect_url=bind_url)

        if bind.get('code') == 0:
            data = bind.get('data')

            return f"{bind.get('msg')}: user_name: {data.get('username')}, id[{data.get('twitterID')}]"

        raise Exception(f"Failed: {bind.get('msg')}")

    @action_log('Check In')
    async def check_in(self) -> dict:

        if not self.auth:
            await self.login()

        headers = {
            **self.base_headers,
            'authorization': f'Bearer {self.jwt}',
        }

        payload = {
            'address': self.client.account.address,
        }

        r = await self.session.post(
            url = f"{self.BASE}/sign/in",
            headers=headers,
            json=payload,
            timeout=120,
        )

        r.raise_for_status()

        if r.json().get('msg') == 'ok':

            return r.json()

        if r.json().get('msg') == 'already signed in today':
            #todo return
            return 'already signed in today'

    async def get_user_tasks(self, user=False) -> dict:

        if not self.auth:
            await self.login()

        headers = {
            **self.base_headers,
            'authorization': f'Bearer {self.jwt}',
        }

        if user:
            params = {
            'address': self.client.account.address,
            }
            r = await self.session.get(
                url = f"{self.BASE}/user/tasks",
                headers=headers,
                params=params,
                timeout=120,
            )

            r.raise_for_status()

            return r.json().get('data').get('user_tasks')


        r = await self.session.get(
            url=f"{self.BASE}/info/tasks",
            headers=headers,
            timeout=120,
        )
        r.raise_for_status()

        return r.json()

    async def tasks_flow(self):
        all_tasks = await self.get_user_tasks()
        user_tasks = await self.get_user_tasks(user=True)
        completed_task_ids = {task['TaskId'] for task in user_tasks}

        social_tasks = all_tasks.get('Social Tasks').get('tasks')

        social_to_do = [social_task for social_task in social_tasks if social_task['task_id'] not in completed_task_ids]

        return social_to_do

        for task in social_to_do:

            if task['task_type'] == 'twitter':
                #todo follow, retweet, reply in twitter

                task = await self.verify_task(task=task)
                logger.success(task)

        return social_to_do

    async def verify_task(self, task: dict) -> dict:

        headers = {
            **self.base_headers,
            'authorization': f'Bearer {self.jwt}',
        }

        payload = {
            'address': self.client.account.address,
            'task_id': task['task_id']
        }

        r = await self.session.post(
            url=f"{self.BASE}/task/verify",
            headers=headers,
            json=payload
        )
        r.raise_for_status()

        if r.json().get('msg') == 'task verified successfully':
            return f"Task {task['name']}: {r.json().get('msg')}"

        raise Exception(f"Task {task['name']} Failed: {r.text}")


    #todo discord bind