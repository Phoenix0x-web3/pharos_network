import asyncio
import contextlib
import json
import random
import re
import uuid
import zlib
from typing import Any, Dict, Optional, Tuple, Callable, Awaitable

import aiohttp
from loguru import logger
from curl_cffi import requests
import base64

from libs.baseAsyncSession import BaseAsyncSession, FINGERPRINT_MAC136
from utils.captcha.bestcapthca import create_bestcaptcha_task, get_bestcaptcha_task_result
from utils.captcha.capthca24 import create_24captch_task, get_24captcha_task_result
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.discord.captcha import get_hcaptcha_solution
from utils.query_json import json_to_query, query_to_json

DISCORD_SITE_KEY = "a9b5fb07-92ff-493f-86fe-352a2803b3df"


class DiscordStatus:
    ok = "OK"
    bad_token = "BAD"
    duplicate = "DUPLICATE"
    captcha = "CAPTCHA"
    verify = "NEED VERIFY"
    
class BaseAsyncSession(requests.AsyncSession):
    def __init__(
            self,
            proxy: Optional[str] = None,
            fingerprint: dict = FINGERPRINT_MAC136,
            **session_kwargs,
    ):
        headers = session_kwargs.pop("headers", {}) or {}
        headers.update({
            "user-agent": fingerprint.get("user-agent"),
            "sec-ch-ua-platform": fingerprint.get("sec-ch-ua-platform"),
            "sec-ch-ua": fingerprint.get("sec-ch-ua"),
            "accept-language": fingerprint.get("accept-language"),
        })
        init_kwargs = {
            "headers": headers,
            "impersonate": getattr(requests.BrowserType, fingerprint.get("impersonate")),
            **session_kwargs,
        }
        if proxy:
            init_kwargs["proxies"] = {"http": proxy, "https": proxy}
        super().__init__(**init_kwargs)

    @property
    def user_agent(self) -> str:
        return self.headers["user-agent"]


def _b64j(data: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(data, separators=(",", ":")).encode("utf-8")).decode("utf-8")


def build_xsuperparams(
        *,
        user_agent: str,
        system_locale: str = "en-US",
        os_version: str = "10.15.7",
        referrer: str = "",
        referring_domain: str = "",
        referrer_current: str = "https://discord.com/",
        referring_domain_current: str = "discord.com",
        release_channel: str = "stable",
        client_event_source: Optional[str] = None,
) -> str:
    """
    client_build_number hardcoded  432548
    """
    payload = {
        "os": "Mac OS X",
        "browser": "Chrome",
        "device": "",
        "system_locale": system_locale,
        "browser_user_agent": user_agent,
        "browser_version": "136.0.0.0",
        "os_version": os_version,
        "referrer": referrer,
        "referring_domain": referring_domain,
        "referrer_current": referrer_current,
        "referring_domain_current": referring_domain_current,
        "release_channel": release_channel,
        "client_build_number": 432548,
        "client_event_source": client_event_source,
    }
    return _b64j(payload)


def build_xcontent(
        *,
        location_guild_id: str,
        location_channel_id: str,
        location: str = "Accept Invite Page",
        location_channel_type: int = 0,
) -> str:
    payload = {
        "location": location,
        "location_guild_id": str(location_guild_id),
        "location_channel_id": str(location_channel_id),
        "location_channel_type": location_channel_type,
    }
    return _b64j(payload)


class DiscordInviter:
    __module_name__ = 'Discord Inviter'

    GATEWAY_URL = "wss://gateway.discord.gg/?v=9&encoding=json"
    REST_BASE = "https://discord.com/api/v9"

    def __init__(
            self,
            wallet,
            *,
            fingerprint: dict = FINGERPRINT_MAC136,
            invite_code: str = "pharos",
            channel_id: Optional[str] = None,
            timezone: str = "Europe/Warsaw",
            locale: str = "en-US",
            cookies: Optional[Dict[str, str]] = None,
            captcha_solver: Optional[
                Callable[[str, BaseAsyncSession, str, str, Any, bool], Awaitable[Tuple[bool, str]]]
            ] = None,
    ):
        self.wallet: Wallet = wallet
        self.proxy = self.wallet.discord_proxy if self.wallet.discord_proxy else wallet.proxy

        if self.proxy and not self.proxy.startswith("http"):
            self.proxy = f"http://{self.proxy}"

        self.discord_token: str = wallet.discord_token
        self.invite_code = invite_code
        self.channel = channel_id or "1270276651636232282"
        self.session_id = self._generate_session_id()
        self.timezone = timezone
        self.locale = locale
        self.cookies_in = cookies or {}
        self.captcha_solver = captcha_solver

        self.client_build: Optional[int] = None
        self.native_build: Optional[int] = None

        self.async_session: BaseAsyncSession = BaseAsyncSession(
            proxy=self.proxy,
            fingerprint=fingerprint,
            timeout=30,
        )
        if self.cookies_in:
            self.async_session.cookies.update(self.cookies_in)

        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.client_session: Optional[aiohttp.ClientSession] = None
        self.heartbeat_interval: Optional[int] = None
        self.sequence: Optional[int] = None
        self.tasks: list[asyncio.Task] = []

        self.x_content_properties: Optional[str] = None

    @staticmethod
    def _generate_session_id() -> str:
        return uuid.uuid4().hex

    def _super_props(self) -> str:
        return build_xsuperparams(
            user_agent=self.async_session.user_agent,
            system_locale=self.locale,
            os_version="10.15.7",
            referrer="",
            referring_domain="",
            referrer_current="https://discord.com/",
            referring_domain_current="discord.com",
            release_channel="stable",
        )

    def base_headers(self) -> Dict[str, str]:
        return {
            "accept": "*/*",
            "accept-language": self.async_session.headers.get("accept-language", "en-US,en;q=0.9"),
            "authorization": self.discord_token,
            "priority": "u=1, i",
            "referer": "https://discord.com/channels/@me",
            "sec-ch-ua": self.async_session.headers.get("sec-ch-ua", FINGERPRINT_MAC136["sec-ch-ua"]),
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": f"\"{FINGERPRINT_MAC136['sec-ch-ua-platform']}\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": self.async_session.user_agent,
            "x-debug-options": "bugReporterEnabled",
            "x-discord-locale": self.locale,
            "x-discord-timezone": self.timezone,
            "x-super-properties": self._super_props(),
        }

    @staticmethod
    def open_session(func):
        async def wrapper(self, *args, **kwargs):
            self.async_session.headers.update({
                "authorization": self.discord_token,
                "x-super-properties": self._super_props(),
            })
            if self.cookies_in:
                self.async_session.cookies.update(self.cookies_in)

            headers = {
                'authority': 'discord.com',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'accept-language': self.async_session.headers.get("accept-language", "en-US,en;q=0.9"),
                'sec-ch-ua': self.async_session.headers.get("sec-ch-ua", FINGERPRINT_MAC136["sec-ch-ua"]),
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': f"\"{FINGERPRINT_MAC136['sec-ch-ua-platform']}\"",
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'none',
                'sec-fetch-user': '?1',
                'upgrade-insecure-requests': '1',
                'user-agent': self.async_session.user_agent,
            }
            await self.async_session.get("https://discord.com/login", headers=headers)
            return await func(self, *args, **kwargs)

        return wrapper

    async def connect(self):
        connector_args = {"proxy": self.proxy} if self.proxy else {}
        self.client_session = aiohttp.ClientSession(**connector_args)
        self.ws = await self.client_session.ws_connect(
            self.GATEWAY_URL,
            headers={"Authorization": self.discord_token, "User-Agent": self.async_session.user_agent}
        )
        hello_payload = await self.ws.receive_json()
        self.heartbeat_interval = hello_payload["d"]["heartbeat_interval"]

        self.tasks = [
            asyncio.create_task(self.heartbeat_loop(), name=f"hb:{self.wallet}"),
            asyncio.create_task(self.identify(), name=f"id:{self.wallet}"),
            asyncio.create_task(self.listen_gateway(), name=f"ls:{self.wallet}"),
        ]

    async def close(self):
        for t in getattr(self, "tasks", []):
            t.cancel()
        for t in getattr(self, "tasks", []):
            with contextlib.suppress(asyncio.CancelledError):
                await t
        if self.ws and not self.ws.closed:
            await self.ws.close(code=aiohttp.WSCloseCode.GOING_AWAY)
        if self.client_session and not self.client_session.closed:
            await self.client_session.close()

    async def identify(self):
        payload = {
            "op": 2,
            "d": {
                "token": self.discord_token,
                "capabilities": 30717,
                "properties": {
                    "os": "Mac OS X",
                    "browser": "Chrome",
                    "device": "",
                    "system_locale": self.locale,
                    "has_client_mods": False,
                    "browser_user_agent": self.async_session.user_agent,
                    "browser_version": "136.0.0.0",
                    "os_version": "10.15.7",
                    "referrer": "",
                    "referring_domain": "",
                    "referrer_current": "",
                    "referring_domain_current": "",
                    "release_channel": "stable",
                    "client_build_number": 432548,
                    "client_event_source": None
                },
                "presence": {
                    "status": "unknown",
                    "since": 0,
                    "activities": [],
                    "afk": False,
                },
                "compress": False,
                "client_state": {"guild_versions": {}},
            },
        }
        try:
            await self.ws.send_json(payload)
        except Exception as e:
            logger.error(f'Identify error | {e}')

    async def send_join(self):

        payload = {
            "op": 37,
            "d": {
                "subscriptions": {
                    str(self.channel): {"typing": True, "activities": True, "threads": True}
                }
            }
        }
        try:
            await self.ws.send_json(payload)
        except Exception as e:
            logger.error(f'Send Join error | {e}')

    async def listen_gateway(self):

        async for message in self.ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(message.data)
            elif message.type == aiohttp.WSMsgType.BINARY:
                try:
                    data = json.loads(zlib.decompress(message.data))
                except Exception:
                    data = {"raw": message.data}
            else:
                continue

            t = data.get("t")
            s = data.get("s")
            if s is not None:
                self.sequence = s

            if data.get("op") == 0 and t == "READY":
                user = (data.get("d") or {}).get("user") or {}
                logger.debug(
                    f"{self.wallet} | {self.__module_name__} | Authorized as "
                    f"{user.get('username')}#{user.get('discriminator')} | session_id = {self.session_id}"
                )

    async def heartbeat_loop(self):
        while True:
            await asyncio.sleep((self.heartbeat_interval or 45000) / 1000.0)
            payload = {"op": 1, "d": self.sequence}
            try:
                await self.ws.send_json(payload)
            except Exception as e:
                logger.error(f'Heartbeat error {e}')
                break


    async def get_guild_id(self) -> tuple[bool, str, str]:
        """
        GET /invites/{code}
        """
        try:
            r = await self.async_session.get(f"{self.REST_BASE}/invites/{self.invite_code}")

            if "You need to verify your account" in r.text:
                logger.error(f"{self.wallet} | {self.__module_name__} | Account needs verification (Email code etc).")
                self.wallet.discord_status = DiscordStatus.bad_token
                db.commit()
                return "verification_failed", "", False

            location_guild_id = r.json()['guild_id']
            location_channel_id = r.json()['channel']['id']

            return True, location_guild_id, location_channel_id
        except Exception as err:
            logger.error(f"{self.wallet} | {self.__module_name__} | Failed to get guild ids: {err}")
            return False, None, None

    async def get_tz(self) -> str:
        r = await self.async_session.get(url='https://ipapi.co/timezone/')
        return r.text

    @open_session
    async def accept_invite(self) -> Tuple[bool, str]:
        headers = {
            'accept': '*/*',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': self.async_session.headers.get("accept-language", "en-US,en;q=0.9"),
            'content-type': 'application/json',
            'origin': 'https://discord.com',
            'priority': 'u=1, i',
            'referer': 'https://discord.com/channels/@me',
            'sec-ch-ua': self.async_session.headers.get("sec-ch-ua", FINGERPRINT_MAC136["sec-ch-ua"]),
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f"\"{FINGERPRINT_MAC136['sec-ch-ua-platform']}\"",
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.async_session.user_agent,
            'x-context-properties': self.x_content_properties or "",
            'x-debug-options': 'bugReporterEnabled',
            'x-discord-locale': self.locale,
            'x-discord-timezone': self.timezone,
            'x-super-properties': build_xsuperparams(
                user_agent=self.async_session.user_agent,
                system_locale=self.locale,
                os_version="10.15.7",
            ),
            "host": "discord.com",
            "authorization": self.discord_token,
        }
        # print('headers', json.dumps(headers, indent=4))

        body = {'session_id': self.session_id}
        r = await self.async_session.post(
            f"{self.REST_BASE}/invites/{self.invite_code}",
            json=body,
            headers=headers
        )

        if 'The user is banned from this guild' in (r.text or ""):
            return False, f'{self.wallet} | {self.__module_name__} | Banned on the server!'

        if r.status_code == 200:
            try:
                if r.json().get("type") == 0:
                    return True, f'{self.wallet} | {self.__module_name__} | Joined the server!'
            except Exception:
                pass


        need_captcha = False
        captcha_rqdata = captcha_rqtoken = captcha_session_id = None
        try:
            if r.headers.get("content-type", "").startswith("application/json"):
                j = r.json()
                if any(k in j for k in (
                        "captcha_sitekey", "captcha_rqtoken", "captcha_service", "captcha_rqdata",
                        "captcha_session_id")):
                    need_captcha = True
                    captcha_rqdata = j.get("captcha_rqdata")
                    captcha_rqtoken = j.get("captcha_rqtoken")
                    captcha_session_id = j.get("captcha_session_id")
        except Exception:
            pass

        if ("You need to update your app to join this server." in (r.text or "")) or (
                "captcha_rqdata" in (r.text or "")):
            need_captcha = True
            self.wallet.discord_status = DiscordStatus.captcha
            db.commit()
            #todo captcha flow
            return False, f'{self.wallet} | {self.__module_name__} | {r.text}'

        if not need_captcha:
            if "Unauthorized" in (r.text or ""):
                return False, f'{self.wallet} | {self.__module_name__} | Incorrect discord token or your account is blocked.'
            if "You need to verify your account in order to" in (r.text or ""):
                self.wallet.discord_status = DiscordStatus.verify
                db.commit()
                return False, f'{self.wallet} | {self.__module_name__} | Account needs verification (Email code etc).'
            return False, f'{self.wallet} | {self.__module_name__} | Unknown error: {r.text}'

        status, g_recaptcha_response = await get_hcaptcha_solution(
            proxy=self.proxy,
            session=self.async_session,
            site_key=DISCORD_SITE_KEY,
            page_url="https://discord.com/",
            rq_data=captcha_rqdata,
            enterprise=True
        )
        logger.info(f'hCAPTCHA SOLVED::: {g_recaptcha_response}')

        if not status:
            return False, f'{self.wallet} | {self.__module_name__} | {g_recaptcha_response}'
        logger.debug(
            f"{self.wallet} | {self.__module_name__} |Received captcha solution... Trying to join the server")

        # ok, g_recaptcha_response = await self.captcha_solver(
        #     self.proxy,
        #     self.async_session,
        #     DISCORD_SITE_KEY,
        #     'https://discord.com/',
        #     captcha_rqdata,  # rqdata передаём солверу (enterprise), но НЕ кладём в body
        #     True
        # )
        # if not ok:
        #     return False, f'{self.wallet} | {self.__module_name__} | {g_recaptcha_response}'
        # logger.info(f'[Captcha] Solved: {g_recaptcha_response}')

        headers2 = {
            'Accept': '*/*',
            'Accept-Language': self.async_session.headers.get("accept-language", "en-US,en;q=0.9"),
            'Accept-Encoding': 'gzip, deflate, br',
            'Content-Type': 'application/json',
            'Origin': 'https://discord.com',
            'Referer': f'https://discord.com/invite/{self.invite_code}',
            'Sec-CH-UA': self.async_session.headers.get("sec-ch-ua", FINGERPRINT_MAC136["sec-ch-ua"]),
            'Sec-CH-UA-Mobile': '?0',
            'Sec-CH-UA-Platform': f"\"{FINGERPRINT_MAC136['sec-ch-ua-platform']}\"",
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Authorization': self.discord_token,
            'User-Agent': self.async_session.user_agent,
            'X-Captcha-Key': g_recaptcha_response,
            'X-Captcha-Rqtoken': captcha_rqtoken or "",
            'X-Captcha-Session-Id': captcha_session_id or "",
            'X-Context-Properties': self.x_content_properties or "",
            'X-Debug-Options': 'bugReporterEnabled',
            'X-Discord-Locale': self.locale,
            'X-Discord-Timezone': self.timezone,
            'X-Super-Properties': build_xsuperparams(
                user_agent=self.async_session.user_agent,
                system_locale=self.locale,
                os_version="10.15.7",
            ),
            'Host': 'discord.com',
        }
        # print('headers2', json.dumps(headers2, indent=4))
        body2 = {
            'session_id': self.session_id,  # в HAR иногда null; свой session_id тоже работает
            # 'captcha_key': g_recaptcha_response,  # РЕШЕНИЕ КАПЧИ В ТЕЛЕ — да
            # 'captcha_rqtoken': captcha_rqtoken,  # rqtoken тоже в теле
        }

        r2 = await self.async_session.post(
            f"{self.REST_BASE}/invites/{self.invite_code}",
            json=body2,
            headers=headers2
        )
        logger.debug(f"{self.wallet} | {self.__module_name__} | {r2.status_code} | {r2.text}")

        if 'The user is banned from this guild' in (r2.text or ""):
            return False, f'{self.wallet} | {self.__module_name__} | Banned on the server!'

        if r2.status_code == 200:
            try:
                if r2.json().get('type') == 0:
                    return True, f'{self.wallet} | {self.__module_name__} | Joined the server!'

            except Exception:
                pass

            return False, f'{self.wallet} | {self.__module_name__} | Unexpected 200: {r2.text}'
        if "Unknown Message" in (r2.text or ""):
            return False, f'{self.wallet} | {self.__module_name__} | Unknown Message: {r2.text}'

        return False, f'{self.wallet} | {self.__module_name__} | Wrong invite response: {r2.text}'

    def compute_version(self) -> Optional[int]:
        try:
            s = requests.Session(proxy=self.proxy) if self.proxy else requests.Session()
            res = s.get(
                "https://updates.discord.com/distributions/app/manifests/latest",
                params={"install_id": "0", "channel": "stable", "platform": "win", "arch": "x64"},
                headers={"user-agent": "Discord-Updater/1", "accept-encoding": "gzip"},
                timeout=30,
            )
            return int(res.json().get("metadata_version"))
        except Exception as e:
            logger.error(e)

    def assemble_build(self) -> Optional[int]:
        try:
            s = requests.Session(proxy=self.proxy) if self.proxy else requests.Session()
            res = s.get("https://discord.com/app", timeout=60)
            pg = res.text
            found = re.findall(r'src="/assets/([^"]+)"', pg)
            for f in reversed(found):
                js = s.get(f"https://discord.com/assets/{f}", timeout=60).text
                if "buildNumber:" in js:
                    return int(js.split('buildNumber:"')[1].split('"')[0])
            return -1
        except Exception as e:
            logger.error(e)

    async def agree_with_server_rules(self, location_guild_id: str, location_channel_id: str) -> Tuple[bool, str]:

        r = await self.async_session.get(
            f"{self.REST_BASE}/guilds/{location_guild_id}/member-verification",
            params={"with_guild": "false", "invite_code": self.invite_code}
        )
        if "Unknown Guild" in r.text:
            return True, f"{self.wallet} | {self.__module_name__} | This guild does not require agreement with the rules."

        headers = {
            'authority': 'discord.com',
            'accept': '*/*',
            'content-type': 'application/json',
            'origin': 'https://discord.com',
            'referer': f'https://discord.com/channels/{location_guild_id}/{location_channel_id}',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f"\"{FINGERPRINT_MAC136['sec-ch-ua-platform']}\"",
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'x-debug-options': 'bugReporterEnabled',
            'x-discord-locale': self.locale,
        }

        data = r.json()
        body = {
            'version': data['version'],
            'form_fields': [
                {
                    'field_type': data['form_fields'][0]['field_type'],
                    'label': data['form_fields'][0]['label'],
                    'description': data['form_fields'][0]['description'],
                    'automations': data['form_fields'][0]['automations'],
                    'required': True,
                    'values': data['form_fields'][0]['values'],
                    'response': True,
                },
            ],
        }

        r2 = await self.async_session.put(
            f"{self.REST_BASE}/guilds/{location_guild_id}/requests/@me",
            json=body,
            headers=headers
        )

        if 'You need to verify your account' in r2.text:
            return False, f"{self.wallet} | {self.__module_name__} | Account needs verification (Email code etc)."
        if 'This user is already a member' in r2.text:
            return True, f"{self.wallet} | {self.__module_name__} | This user is already a member!"
        if "application_status" in r2.text:
            if r2.json()['application_status'] == "APPROVED":
                return True, f"{self.wallet} | {self.__module_name__} | Agreed to the server rules."
            else:
                return False, f"{self.wallet} | {self.__module_name__} | Failed to agree to the server rules: {r2.text}"
        return False, f"{self.wallet} | {self.__module_name__} | Failed to agree to the server rules."

    #
    # async def click_to_emoji(self, location_guild_id: str, location_channel_id: str) -> Tuple[bool, str]:
    #     headers = {
    #         'accept': '*/*',
    #         'accept-language': self.async_session.headers.get("accept-language", "en-US,en;q=0.9"),
    #         'origin': 'https://discord.com',
    #         'priority': 'u=1, i',
    #         'referer': f'https://discord.com/channels/{location_guild_id}/{location_channel_id}',
    #         'sec-ch-ua': self.async_session.headers.get("sec-ch-ua", FINGERPRINT_MAC136["sec-ch-ua"]),
    #         'sec-ch-ua-mobile': '?0',
    #         'sec-ch-ua-platform': f"\"{FINGERPRINT_MAC136['sec-ch-ua-platform']}\"",
    #         'sec-fetch-dest': 'empty',
    #         'sec-fetch-mode': 'cors',
    #         'sec-fetch-site': 'same-origin',
    #         'x-debug-options': 'bugReporterEnabled',
    #         'x-discord-locale': self.locale,
    #         'x-discord-timezone': self.timezone,
    #         'x-super-properties': self._super_props(),
    #     }
    #
    #     params = {'location': 'Message Inline Button', 'type': '0'}
    #
    #     r = await self.async_session.put(
    #         f'{self.REST_BASE}/channels/1281443663469084703/messages/1336563387395473428/reactions/%E2%9C%85/%40me',
    #         params=params,
    #         headers=headers,
    #     )
    #     if r.status_code == 204:
    #         return True, f'{self.wallet} | {self.__module_name__} | Успешно нажал на emoji'
    #     return False, f'{self.wallet} | {self.__module_name__} | Не смог нажать на emoji. Ответ сервера: {r.text} | Status_code: {r.status_code}'

    @open_session
    async def start_accept_discord_invite(self):

        tz = await self.get_tz()
        self.timezone = tz

        NUMBER_OF_ATTEMPTS = 2

        for num in range(1, NUMBER_OF_ATTEMPTS + 1):
            try:
                logger.info(f'{self.wallet} | {self.__module_name__} | Starting to join {self.invite_code} channel | attemp {num}/{NUMBER_OF_ATTEMPTS}')

                await self.connect()
                #important pause
                await asyncio.sleep(random.randint(120, 160))

                status, location_guild_id, location_channel_id = await self.get_guild_id()
                logger.debug(f'Location recieved {location_guild_id}, {location_channel_id}')

                if not location_channel_id:
                    await self.close()
                    return f"Failed | do not received guild_id"

                if not status:
                    logger.error('Do not received location_guild_id and location_channel_id from discrod')
                    await self.close()
                    continue

                self.x_content_properties = build_xcontent(
                    location_guild_id=location_guild_id,
                    location_channel_id=location_channel_id,
                )

                invited, answer = await self.accept_invite()

                if ("Banned" in answer) or ("Incorrect discord token or your account is blocked" in answer):
                    logger.error(answer)
                    self.wallet.discord_status = DiscordStatus.bad_token
                    db.commit()
                    await self.close()
                    continue

                if not invited:
                    logger.error(answer)
                    await self.close()
                    continue

                logger.success(answer)

                ok, answer = await self.agree_with_server_rules(location_guild_id, location_channel_id)
                if not ok:
                    logger.error(answer)
                    await self.close()
                    continue

                logger.success(answer)

                # return of connected
                if invited:

                    await self.ws.close()
                    await self.close()
                    await asyncio.sleep(1)

                    return f"Success | Join Guild {self.invite_code} | channel {self.channel}"


            except Exception as e:
                logger.error(
                    f"{self.wallet} | {self.__module_name__} | Attempt {num}/{NUMBER_OF_ATTEMPTS} failed due to: {e}")

                if num == NUMBER_OF_ATTEMPTS:

                    return f"Failed | Join Guild {self.invite_code} | channel {self.channel}"

                with contextlib.suppress(Exception):
                    if self.ws:
                        await self.ws.close()
                await self.close()
                await asyncio.sleep(1)

        return f"Failed | Join Guild {self.invite_code} | channel {self.channel}"

class DiscordOAuth:

    def __init__(
            self,
            wallet,
            *,
            proxy: Optional[str] = None,
            timezone: str = "Europe/Warsaw",
            locale: str = "en-US",
            cookies: Optional[Dict[str, str]] = None,
            session: Optional[BaseAsyncSession] = None,
            guild_id: str
    ):
        self.wallet = wallet
        self.proxy = self.wallet.discord_proxy if self.wallet.discord_proxy else wallet.proxy
        if session is not None:
            self.async_session = session
        else:
            self.async_session = BaseAsyncSession(proxy=self.proxy, fingerprint=FINGERPRINT_MAC136)
        self.timezone = timezone
        self.locale = locale
        self.guild_id = guild_id

    def _oauth_headers(self) -> Dict[str, str]:

        return {
            'accept': '*/*',
            'accept-language': self.async_session.headers.get("accept-language", "en-US,en;q=0.9"),
            'authorization': self.wallet.discord_token,
            'priority': 'u=1, i',
            'referer': 'https://discord.com/channels/@me',
            'sec-ch-ua': self.async_session.headers.get("sec-ch-ua", FINGERPRINT_MAC136["sec-ch-ua"]),
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f"\"{FINGERPRINT_MAC136['sec-ch-ua-platform']}\"",
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.async_session.user_agent,
            'x-debug-options': 'bugReporterEnabled',
            'x-discord-locale': self.locale,
            'x-discord-timezone': self.timezone,
            'x-super-properties': build_xsuperparams(
                user_agent=self.async_session.user_agent,
                system_locale=self.locale,
                os_version="10.15.7",
            ),
        }

    async def get_tz(self) -> str:
        r = await self.async_session.get(url='https://ipapi.co/timezone/')
        return r.text

    async def start_oauth2(
            self,
            oauth_url: str
    ) -> str:


        url, state = await self.confirm_auth_code(
            oauth_url = oauth_url,
            integration_type=True
        )

        if url:
            return url, state

        raise Exception(f'Error in Discord OAuth2')

    async def confirm_auth_code(
            self,
            *,
            oauth_url: str,
            integration_type: bool = True,
            permissions: str = "0",
    ) -> str:

        self.timezone = await self.get_tz()

        base_url = "https://discord.com/api/v9/oauth2/authorize"
        referer_base = "https://discord.com/oauth2/authorize"

        params = query_to_json(oauth_url)

        headers = self._oauth_headers()
        headers['referer'] = json_to_query(referer_base, params)

        get_params = params.copy()

        if integration_type:
            get_params["integration_type"] = 0

            req = await self.async_session.get(
                base_url,
                params=get_params,
                headers=headers,
            )

            if req.status_code <= 202:

                return await self.confirm_auth_code(
                    oauth_url=oauth_url,
                    integration_type=False,
                    permissions=permissions,
                )

        post_params = params.copy()

        json_data = {
            "guild_id": self.guild_id,
            'permissions': permissions,
            'authorize': True,
            'integration_type': 0,
            'location_context': {
                'guild_id': '10000',
                'channel_id': '10000',
                'channel_type': 10000,
            },
        }

        r2 = await self.async_session.post(
            base_url,
            params=post_params,
            headers=headers,
            json=json_data,
        )

        if r2.status_code <= 202:
            try:
                loc = r2.json().get("location")
                if loc:
                    return loc, post_params['state']

            except Exception:
                pass

        logger.error(f'[OAuth] Status code {r2.status_code}. Response: {r2.text}')
        raise Exception(f'Status code {r2.status_code}. Response: {r2.text}')