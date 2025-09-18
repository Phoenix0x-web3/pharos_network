import asyncio
import random
import secrets
from time import sleep

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
from utils.query_json import query_to_json
from utils.retry import async_retry
from utils.twitter.twitter_client import TwitterClient
from utils.db_api.wallet_api import db
from sqlalchemy import and_
from datetime import datetime, timezone
from utils.browser import Browser

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
        self.session = Browser(wallet=wallet)
        self.twitter = TwitterClient(user=self.wallet)
 

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

    async def _siwe_message(self, nonce: int) -> tuple[str, str]:

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


    @staticmethod
    async def value_for_today(seq):

        idx = datetime.now(timezone.utc).weekday()

        items = [int(x) for x in seq] if isinstance(seq, str) else list(seq)
        if len(items) != 7:
            raise ValueError("seq must have 7 items")
        return items[idx]

    async def login(self, registration=False):
        settings = Settings()
        nonce = await self.client.wallet.nonce()

        message, timestamp = await self._siwe_message(nonce=nonce)
        sig = await self.sign_message(text=message)
        

        payload = {
            'address': self.client.account.address,
            'signature': sig,
            'wallet': self.wallet.wallet_type,
            'nonce': str(nonce),
            'chain_id': '688688',
            'timestamp': timestamp,
            'domain': 'testnet.pharosnetwork.xyz',
        }

        if registration:
            if settings.invite_codes:  # use only settings if provided
                invite_code = random.choice(settings.invite_codes)
            else:
                invite_codes_from_db = [
                    code[0] for code in db.all(Wallet.invite_code, Wallet.invite_code != "")
                ]
                invite_code = random.choice(invite_codes_from_db) if invite_codes_from_db else ""
        
            if invite_code:
                payload["invite_code"] = invite_code

        r = await self.session.post(
            url=f"{self.BASE}/user/login",
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

        check_in_status = await self.get_checkin_status()

        if check_in_status:
            check_in = await self.check_in()
            if 'Failed' not in str(check_in):
                logger.success(check_in)

        await asyncio.sleep(random.randint(2, 5))

        return r.json()

    async def send_verify(self, tx):
        if not self.auth:
            await self.login()

        headers = {
            **self.base_headers,
            'authorization': f'Bearer {self.jwt}',
        }

        payload = {
            'address': self.client.account.address,
            'task_id': 103,
            'tx_hash': tx.lower()
        }

        r = await self.session.post(
            url=f"{self.BASE}/task/verify",
            headers=headers,
            json=payload,
            timeout=120,
        )

        return r.json().get('msg')


    async def get_twitter_link(self):
        headers = {
            **self.base_headers,
            'Host': 'api.pharosnetwork.xyz',
        }

        r = await self.session.get(
            url=f"{self.BASE}/auth/twitter",
            headers=headers,
            allow_redirects=False,
            timeout=120,
        )

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
            url=f"{self.BASE}/auth/bind/twitter",
            headers=headers,
            json=payload,
            timeout=120,
        )

        r.raise_for_status()

        if r.json().get('code') == 0:
            data = r.json().get('data')

            return f"{r.json().get('msg')}: user_name: {data.get('username')}, id[{data.get('twitterID')}]"

        if  r.json().get('code') == 1:
            raise Exception(f"Failed | {r.json().get('msg')}")

        raise Exception(f"Failed: {r.get('msg')}")

    @action_log('Faucet')
    async def faucet(self):
        if not self.auth:
            await self.login()



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
                url=f"{self.BASE}/faucet/daily",
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

    async def get_checkin_status(self) -> bool:
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
            url = f"{self.BASE}/sign/status",
            headers=headers,
            # cookies=self.cookies,
            params=params,
            timeout=120,
        )
        #logger.success(f"User info | {r.json()}")

        r.raise_for_status()

        if r.json().get('msg') == 'ok':

            status = r.json().get('data').get('status')
            status = await self.value_for_today(seq=status)
            if status == 2:
                return True
            return False

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

    @async_retry(retries=3, delay=3, to_raise=False)
    @controller_log('Check In')
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

            return 'Success Check In'

        if r.json().get('msg') == 'already signed in today':
            #todo return
            return 'Failed Check In'

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

    async def _twitter_actions_from_social(self, social_tasks : list, completed_ids : list) -> list[dict]:
        out = []
        for t in social_tasks:
            if t.get("task_type") != "twitter":
                continue

            # nested follow items
            for sub in t.get("follow_item", []) or []:
                bt = sub.get("button_text")
                tid = sub.get("task_id")
                if tid is None or bt is None or tid in completed_ids:
                    continue
                    
                out.append({"type": bt, "task_id": tid})

   
            bt = t.get("button_text")
            tid = t.get("task_id")
            if tid is None or bt is None or tid in completed_ids:
                continue
                
            out.append({"type": bt, "task_id": tid})
            
        return out
            
    async def tasks_flow(self):
        all_tasks  = await self.get_user_tasks()
        user_tasks = await self.get_user_tasks(user=True)

        completed_ids = {task.get("TaskId") for task in user_tasks}
        social_tasks  = (all_tasks.get("Social Tasks") or {}).get("tasks") or []

        twitter_tasks = await self._twitter_actions_from_social(social_tasks, completed_ids)
        
         # If the only remaining twitter task are 205 → return empty
        if twitter_tasks and {t.get("task_id") for t in twitter_tasks} == {205}:
            twitter_tasks = []
        
        discord_tasks = [task for task in social_tasks if task['task_type'] == 'discord']
        
        return twitter_tasks, discord_tasks

    async def prepare_twitter_tasks(self, twitter_tasks, user_tasks):
        tasks_to_do = [task for task in twitter_tasks if str(task) not in list(user_tasks.keys())]
        return tasks_to_do

    @async_retry(retries=3, delay=3, to_raise=False)
    @controller_log('Follow and  Verify Twitter Tasks')
    async def follow_and_verify_twitter_task(self, twitter_tasks : list[dict]) -> list[dict]:
        
        result = []
        
        for task in twitter_tasks:
        
            task_id = task.get('task_id')
            task_type = task.get('type')
            
            headers = {
                **self.base_headers,
                'authorization': f'Bearer {self.jwt}',
            }

            payload = {
                'address': self.client.account.address,
                'task_id': task_id
            }

            r = await self.session.post(
                url=f"{self.BASE}/task/follow" if task_type == "Follow" else f"{self.BASE}/task/verify",
                headers=headers,
                json=payload
            )

            r.raise_for_status()

            if r.json().get('code') != 0:
                raise Exception(f"Task {task_id} Failed: {r.text}")
            
            result.append(f"Task {task_id}: {r.json().get('msg')}")

            
        return result
    

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

    async def get_discord_oauth_code(self):
        if not self.auth:
            await self.login()

        headers = {
            **self.base_headers,
            'authorization': f'Bearer {self.jwt}',
        }

        r = await self.session.get(
            url=f"{self.BASE}/auth/discord",
            headers=headers,
            allow_redirects=False
        )
        r.raise_for_status()

        return r.headers.get('location')

    @action_log('Bind Discord')
    async def bind_discord(self, url, state):
        if not self.auth:
            await self.login()

        headers = {
            **self.base_headers,
            'authorization': f'Bearer {self.jwt}',
        }
        code = query_to_json(url)

        payload = {
            "state": state,
            "code": code['code'],
            'address': self.client.account.address,
        }

        r = await self.session.post(
            url=f"{self.BASE}/auth/bind/discord",
            headers=headers,
            json=payload
        )
        r.raise_for_status()

        if r.json().get('code') == 0:
            return f"Success | {r.json().get('msg')} username: {r.json().get('data').get('username')}"

        return f'Failed to Bind | {r.text}'