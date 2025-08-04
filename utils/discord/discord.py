import asyncio
import contextlib
import json
import random
import re
import uuid
from functools import wraps

import aiohttp

from data.config import logger
from curl_cffi import requests

from settings import DISCORD_SITE_KEY
from utils.discord.captcha import get_hcaptcha_solution
from utils.discord.headers import create_x_super_properties, create_x_context_properties

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"


NUMBER_OF_ATTEMPTS = 2

class BaseAsyncSession(requests.AsyncSession):

    def __init__(
            self,
            proxy: str = None,
            user_agent: str = DEFAULT_UA,
            *,
            impersonate: requests.BrowserType = requests.BrowserType.chrome136,
            **session_kwargs,
    ):
        proxies = {"http": proxy, "https": proxy}
        headers = session_kwargs.pop("headers", {})
        headers["user-agent"] = user_agent
        super().__init__(
            proxies=proxies,
            headers=headers,
            impersonate=impersonate,
            **session_kwargs,
        )

    @property
    def user_agent(self) -> str:
        return self.headers["user-agent"]

class Discord:
    def __init__(self, auth_token, address, version: str, session: BaseAsyncSession):
        self.auth_token = auth_token
        self.address = address
        self.version = version
        self.platfrom = '136'
        self.tasks = None
        self.async_session = session

    async def start_oauth2(
            self,
    ) -> str:

        url = await self.confirm_auth_code(
            client_id='1283243979562811482',
            response_type='code',
            redirect_uri='https://chat.chainopera.ai/callback/discord',
            scope='guilds identify guilds.join',
        )

        if url:
            return url

        raise Exception(f'Error in Discord Oauth2')

    async def confirm_auth_code(self, client_id, response_type, redirect_uri, scope,integration_type=True ):

        url = "https://discord.com/api/v9/oauth2/authorize"
        headers = self.base_headers()
        headers[
            'referer'] = f'https://discord.com/oauth2/authorize?client_id={client_id}&response_type={response_type}&redirect_uri=https%3A%2F%2Fchat.chainopera.ai%2Fcallback%2Fdiscord&scope=guilds%20identify%20guilds.join'

        params = {
            "client_id": client_id,
            "response_type": response_type,
            "redirect_uri": redirect_uri,
            "scope": scope,
        }
        if integration_type:
            params['integration_type'] = 0

            response = await self.async_session.get(
                url,
                params=params,
                headers=headers,
            )
            if response.status_code <= 202:
                #print(json.dumps(response.json(), indent=4))

                return await self.confirm_auth_code(client_id=client_id,
                                                    response_type=response_type,
                                                    redirect_uri=redirect_uri,
                                                    scope=scope,
                                                    integration_type=False)

        json_data = {
            'permissions': '0',
            'authorize': True,
            'integration_type': 0,
            'location_context': {
                'guild_id': '10000',
                'channel_id': '10000',
                'channel_type': 10000,
            },
        }

        response = await self.async_session.post(
            url,
            params=params,
            headers=headers,
            json=json_data,
        )

        if response.status_code <= 202:
            return response.json().get("location")

        logger.error(f'Status code {response.status_code}. Response: {response.text}')
        raise Exception(f'Status code {response.status_code}. Response: {response.text}')


    def base_headers(self):
        return {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': self.auth_token,
            'priority': 'u=1, i',
            'referer': 'https://discord.com/channels/@me',
            'sec-ch-ua': f'"Google Chrome";v="{self.version}", "Chromium";v="{self.version}", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f'"{self.platfrom}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.async_session.user_agent,
            'x-debug-options': 'bugReporterEnabled',
            'x-discord-locale': 'en-US',
            'x-discord-timezone': 'Europe/Warsaw',
            'x-super-properties': create_x_super_properties(self.async_session.user_agent),
        }



class DiscordInviter(Discord):
    
    def __init__(self, wallet, discord_token):
        self.wallet = wallet
        self.proxy = wallet.proxy

        self.client_build = None
        self.native_build = None

        if 'http' not in self.proxy:
            self.proxy = f'http://{self.proxy}'

        self.discord_token = discord_token
        self.async_session: BaseAsyncSession = BaseAsyncSession(
            proxy=self.proxy,
            #user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            user_agent = DEFAULT_UA,
            timeout=5
        )

        self.invite_code = 'chainopera'
        self.channel = '1281108150748971038'
        self.session_id = self.generate_session_id()

        self.ws = None
        self.client_session = None
        self.gateway_url = "wss://gateway.discord.gg/?v=9&encoding=json"
        self.heartbeat_interval = None
        self.sequence = None
    
    @staticmethod
    def generate_session_id():
        return uuid.uuid4().hex

    @staticmethod
    def open_session(func):
        @wraps(func)

        async def wrapper(self, *args, **kwargs):
            self.async_session.headers.update({
                "authorization": self.discord_token,
                "x-super-properties": create_x_super_properties(
                    native_build_number=self.native_build,
                    client_build_number=self.client_build
                )
            })

            headers = {
                'authority': 'discord.com',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'accept-language': 'en-US,en;q=0.9',
                'sec-ch-ua': '"Google Chrome";v="136", "Chromium";v="136", "Not_A Brand";v="24"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'none',
                'sec-fetch-user': '?1',
                'upgrade-insecure-requests': '1',
                'user-agent': self.async_session.user_agent,
            }

            self.async_session.cookies.update({
                'cf_clearance': 'ci1vlr9efAE_Pe5XxOxenwFuK6OPvbpdtNwt8O_.D6g-1736817731-1.2.1.1-uTb1SslQlUYOJjEgrPeDRngfA7GYWcpjo88JnxTf2gt89_cJfy.tTvjLKXOvYli_xW_NobI9BU8kX8JROYblcAxyOd.dJSf4PlDrteLBjD2AoRSLwjZinstFA2YPw0c8z3l4Qmnj3MvFXrX9KGjgHaGHp63jlsL9k9ebProP93GMulNGv6yWk_WGij_TZp.wEo3buRH6uzcdIQEhebsFghX0ALPz4GDj0B9eMflSKDWQ_e3aKdxKeKt.5NcFFTm0hV35xunq__EaT9nL1MGUVKnmzTsf80MicBTzrvvVSuU',
                'locale': 'en-US',
            })

            await self.async_session.get("https://discord.com/login", headers=headers)

            return await func(self, *args, **kwargs)

        return wrapper
    
    async def connect(self):
        """
        Подключаемся к Discord Gateway через веб-сокет (с прокси, если указано).
        """

        connector_args = {"proxy": self.proxy} if self.proxy else {}

        # Открываем aiohttp-сессию вручную
        self.client_session = aiohttp.ClientSession(**connector_args)

        # Подключаемся к Gateway
        self.ws = await self.client_session.ws_connect(
            self.gateway_url,
            headers={"Authorization": self.discord_token}
        )

        # Ждём HELLO
        hello_payload = await self.ws.receive_json()
        self.heartbeat_interval = hello_payload["d"]["heartbeat_interval"]

        # Запускаем heartbeat loop
        self.tasks = [
            asyncio.create_task(self.heartbeat_loop(), name=f"hb:{self.wallet.name}"),
            asyncio.create_task(self.identify(),       name=f"id:{self.wallet.name}"),
            asyncio.create_task(self.listen_gateway(), name=f"ls:{self.wallet.name}"),
        ]

        # asyncio.create_task(self.heartbeat_loop())
        #
        # # Отправляем IDENTIFY
        # asyncio.create_task(self.identify())
        #
        # # Слушаем Gateway
        # asyncio.create_task(self.listen_gateway())

    async def close(self):
        """
        Закрытие WebSocket и HTTP-сессии.
        """

        # 1) отменяем фоновые задачи
        for t in getattr(self, "tasks", []):
            t.cancel()
        for t in getattr(self, "tasks", []):
            with contextlib.suppress(asyncio.CancelledError):
                await t

        # 2) гасим WebSocket
        if self.ws and not self.ws.closed:
            await self.ws.close(code=aiohttp.WSCloseCode.GOING_AWAY)

        # 3) гасим HTTP‑сессию
        if self.client_session and not self.client_session.closed:
            await self.client_session.close()

        # Закрываем веб-сокет
        # if self.ws:
        #     await self.ws.close()
        #
        # # Закрываем aiohttp.ClientSession
        # if self.client_session:
        #     await self.client_session.close()
    
    async def identify(self):
        """
        Отправляет IDENTIFY пакет.
        """
        identify_payload = {
            "op": 2,
            "d": {
                "token": self.discord_token,
                "capabilities": 30717,
                "properties": {
                    "os": "Windows",
                    "browser": "Chrome",
                    "device": "",
                    "system_locale": "en-US",
                    "has_client_mods": False,
                    "browser_user_agent": DEFAULT_UA,
                    "browser_version": "136.0.0.0",
                    "os_version": "10",
                    "referrer": "",
                    "referring_domain": "",
                    "referrer_current": "",
                    "referring_domain_current": "",
                    "release_channel": "stable",
                    "client_build_number": 359425,
                    "client_event_source": None
                },
                "presence": {
                    "status": "uknown",
                    "since": 0,
                    "activities": [],
                    "afk": False,
                },
                "compress": False,
                "client_state": {
                    "guild_versions": {},
                },
            },
        }
        try:
            await self.ws.send_json(identify_payload)
        except Exception as e:
            logger.error(f'Identify error | {e}')
            pass

    async def send_join(self):
        """
        Отправляет IDENTIFY пакет.
        """
        identify_payload = {
            "op": 37,
            "d": {
                "subscriptions": {
                    self.channel: {
                        "typing": True,
                        "activities": True,
                        "threads": True
                    }
                }
            }
        }
        try:
            await self.ws.send_json(identify_payload)
        except Exception as e:
            logger.error(f'Send Join error | {e}')
            pass
            # print(f"Ошибка при отправке IDENTIFY: {e}")

    async def listen_gateway(self):
        """
        Слушаем входящие события от Gateway.
        """
        async for message in self.ws:
            data = json.loads(message.data)
            op = data["op"]
            t = data.get("t")
            s = data.get("s")
            if s is not None:
                self.sequence = s

            if op == 0 and t == "READY":
                # print(data)
                self.session_id = data["d"]["session_id"]
                user = data["d"]["user"]
                logger.info(
                    f"Discord | [{self.wallet.name}] | Авторизовались как {user['username']}#{user['discriminator']} | session_id = {self.session_id}")

    async def heartbeat_loop(self):
        """
        Периодически отправляет HEARTBEAT (op=1).
        """
        while True:
            await asyncio.sleep(self.heartbeat_interval / 1000.0)
            payload = {
                "op": 1,
                "d": self.sequence,
            }
            try:
                await self.ws.send_json(payload)
            except Exception as e:
                logger.error(f'Heartbeat error {e}')
                # print(f"Ошибка при отправке HEARTBEAT: {e}")
                break

    async def get_guild_id(self) -> tuple[bool, str, str]:
        try:
            response = await self.async_session.get(f"https://discord.com/api/v9/invites/{self.invite_code}")

            if "You need to verify your account" in response.text:
                logger.error(f"[{self.wallet.name}] | Account needs verification (Email code etc).")
                return "verification_failed", "", False

            location_guild_id = response.json()['guild_id']
            location_channel_id = response.json()['channel']['id']

            return True, location_guild_id, location_channel_id

        except Exception as err:
            logger.error(f"Discord | [{self.wallet.name}] | Failed to get guild ids: {err}")
            return False, "", "",

    @open_session
    async def accept_invite(self, my_try=100):
        while True:
            self.client_build = self.assemble_build()
            self.native_build = self.compute_version()

            headers = {
                'accept': '*/*',
                'accept-encoding': 'gzip, deflate, br',
                'accept-language': 'en-US,en;q=0.9',
                'content-type': 'application/json',
                'origin': 'https://discord.com',
                'priority': 'u=1, i',
                'referer': 'https://discord.com/channels/@me',
                'sec-ch-ua': '"Google Chrome";v="136", "Chromium";v="136", "Not_A Brand";v="24"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'user-agent': self.async_session.user_agent,
                'x-context-properties': self.x_content_properties,
                'x-debug-options': 'bugReporterEnabled',
                'x-discord-locale': 'en-US',
                'x-discord-timezone': 'Europe/Warsaw',
                'x-super-properties': create_x_super_properties(
                    native_build_number=self.native_build,
                    client_build_number=self.client_build
                ),
                "host": "discord.com",
            }

            json_data = {
                'session_id': self.session_id
            }

            response = await self.async_session.post(
                f"https://discord.com/api/v9/invites/{self.invite_code}",
                json=json_data,
                headers=headers
            )

            if 'The user is banned from this guild' in response.text:
                return False, f'Discord | [{self.wallet.name}] | Banned on the server!'

            if "You need to update your app to join this server." in response.text or "captcha_rqdata" in response.text:
                # return False, f'Discord | [{self.wallet.name}] | capthca.. I will try again!'
                logger.debug(f'JOIN ANSER::: {response.text}')
                captcha_rqdata = response.json()["captcha_rqdata"]
                captcha_rqtoken = response.json()["captcha_rqtoken"]

                logger.info(f"Discord | [{self.wallet.name}] | Creating hCAPTCHA task...")

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
                    return False, f'Discord | [{self.wallet.name}] | {g_recaptcha_response}'
                logger.info(
                    f"[{self.wallet.name}] {self.discord_token} | Received captcha solution... Trying to join the server")

                headers = {
                    'accept': '*/*',
                    'accept-language': 'en-US,en;q=0.9',
                    'accept-encoding': 'gzip, deflate, br',
                    'content-type': 'application/json',
                    'origin': 'https://discord.com',
                    'referer': f'https://discord.com/invite/{self.invite_code}',
                    'sec-ch-ua': '"Google Chrome";v="136", "Chromium";v="136", "Not_A Brand";v="24"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"Windows"',
                    'sec-fetch-dest': 'empty',
                    'sec-fetch-mode': 'cors',
                    'sec-fetch-site': 'same-origin',
                    'user-agent': self.async_session.user_agent,
                    'x-captcha-key': g_recaptcha_response,
                    'x-captcha-rqtoken': captcha_rqtoken,
                    'x-context-properties': self.x_content_properties,
                    'x-debug-options': 'bugReporterEnabled',
                    'x-discord-locale': 'en-US',
                    'x-discord-timezone': 'Europe/Warsaw',
                    'x-super-properties': create_x_super_properties(
                        native_build_number=self.native_build,
                        client_build_number=self.client_build
                    ),
                    "host": "discord.com",
                }

                json_data = {
                    'session_id': self.session_id,
                    "captcha_key": g_recaptcha_response,
                    "captcha_rqtoken": captcha_rqtoken
                }

                response = await self.async_session.post(
                    f"https://discord.com/api/v9/invites/{self.invite_code}",
                    json=json_data,
                    headers=headers
                )

                # print(self.wallet.name, response.status_code)
                # print(self.wallet.name, response.text)
                if 'The user is banned from this guild' in response.text:
                    return False, f'Discord | [{self.wallet.name}] | Banned on the server!'

                if response.status_code == 200 and response.json().get('type') == 0:
                    return True, f'Discord | [{self.wallet.name}] | Joined the server!'

                elif "Unknown Message" in response.text:
                    return False, f'Discord | [{self.wallet.name}] | Unknown Message: {response.text}'

                return False, f'Discord | [{self.wallet.name}] | Wrong invite response: {response.text}'

            elif response.status_code == 200 and response.json().get("type") == 0:
                return True, f'Discord | [{self.wallet.name}] | Joined the server!'

            elif "Unauthorized" in response.text:
                return False, f'Discord | [{self.wallet.name}] | Incorrect discord token or your account is blocked.'

            elif "You need to verify your account in order to" in response.text:
                return False, f'Discord | [{self.wallet.name}] | Account needs verification (Email code etc).'

            return False, f'Discord | [{self.wallet.name}] | Unknown error: {response.text}'
        
    def compute_version(self):

        try:
            res = requests.Session(proxy=self.proxy).get(

                "https://updates.discord.com/distributions/app/manifests/latest",
                params={"install_id": "0", "channel": "stable", "platform": "win", "arch": "x64"},
                headers={"user-agent": "Discord-Updater/1", "accept-encoding": "gzip"},
                timeout=30,
            )
            res = res.json()
            return int(res["metadata_version"])
        except Exception as e:
            logger.error(e)

    def assemble_build(self):
        try:
            res = requests.Session(proxy=self.proxy).get(
                "https://discord.com/app",
                timeout=60)
            pg = res.text

            found = re.findall(r'src="/assets/([^"]+)"', pg)
            for f in reversed(found):
                jsn = requests.Session(proxy=self.proxy).get(f"https://discord.com/assets/{f}", timeout=10)
                jsn = jsn.text
                if "buildNumber:" in jsn:
                    return int(jsn.split('buildNumber:"')[1].split('"')[0])
            return -1
        except Exception as e:
            logger.error(e)
    async def agree_with_server_rules(self, location_guild_id, location_channel_id):
        response = await self.async_session.get(
            f"https://discord.com/api/v9/guilds/{location_guild_id}/member-verification?with_guild=false&invite_code={self.invite_code}"
        )
        if "Unknown Guild" in response.text:
            return True, f"Discord | [{self.wallet.name}]| This guild does not require agreement with the rules."

        headers = {
            'authority': 'discord.com',
            'accept': '*/*',
            'content-type': 'application/json',
            'origin': 'https://discord.com',
            'referer': f'https://discord.com/channels/{location_guild_id}/{location_channel_id}',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'x-debug-options': 'bugReporterEnabled',
            'x-discord-locale': 'en-US',
        }

        json_data = {
            'version': response.json()['version'],
            'form_fields': [
                {
                    'field_type': response.json()['form_fields'][0]['field_type'],
                    'label': response.json()['form_fields'][0]['label'],
                    'description': response.json()['form_fields'][0]['description'],
                    'automations': response.json()['form_fields'][0]['automations'],
                    'required': True,
                    'values': response.json()['form_fields'][0]['values'],
                    'response': True,
                },
            ],
        }

        response = await self.async_session.put(
            f"https://discord.com/api/v9/guilds/{location_guild_id}/requests/@me",
            json=json_data
        )

        if 'You need to verify your account' in response.text:
            return False, f"Discord | [{self.wallet.name}]| Account needs verification (Email code etc)."

        elif 'This user is already a member' in response.text:
            return True, f"Discord | [{self.wallet.name}]| This user is already a member!"

        if "application_status" in response.text:
            if response.json()['application_status'] == "APPROVED":
                return True, f"Discord | [{self.wallet.name}]| Agreed to the server rules."
            else:
                logger.error(f"{self.account_index} | Failed to agree to the server rules: {response.text}")
                return False, f"Discord | [{self.wallet.name}]| Failed to agree to the server rules: {response.text}"

        else:
            return False, f"Discord | [{self.wallet.name}]| Failed to agree to the server rules: {response.json()['rejection_reason']}"

    async def click_to_emoji(self, location_guild_id, location_channel_id):

        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'origin': 'https://discord.com',
            'priority': 'u=1, i',
            'referer': f'https://discord.com/channels/{location_guild_id}/{location_channel_id}',
            'sec-ch-ua': '"Google Chrome";v="136", "Chromium";v="136", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'x-debug-options': 'bugReporterEnabled',
            'x-discord-locale': 'en-US',
            'x-discord-timezone': 'Europe/Warsaw',
            'x-super-properties': create_x_super_properties(
                native_build_number=self.native_build,
                client_build_number=self.client_build
            ),
        }

        params = {
            'location': 'Message Inline Button',
            'type': '0',
        }

        response = await self.async_session.put(
            f'https://discord.com/api/v9/channels/1281443663469084703/messages/1336563387395473428/reactions/%E2%9C%85/%40me',
            params=params,
            headers=headers,
        )

        if response.status_code == 204:
            return True, f'Discord | [{self.wallet.name}]| Успешно нажал на emoji'

        return False, f'Discord | [{self.wallet.name}]| Не смог нажать на emoji. Ответ сервера: {response.text} | Status_code: {response.status_code}'

    @open_session
    async def start_accept_discord_invite(self):
        for num in range(1, NUMBER_OF_ATTEMPTS + 1):
            try:
                logger.info(f'Discord | [{self.wallet.name}] | попытка {num}/{NUMBER_OF_ATTEMPTS}')

                await self.connect()
                await asyncio.sleep(random.randint(120, 150))

                status, location_guild_id, location_channel_id = await self.get_guild_id()
                logger.info(f'Location::: {location_guild_id}, {location_channel_id}')

                if not status:
                    logger.error(
                        f'Discord | [{self.wallet.name}] | не смог получить location_guild_id и location_channel_id')
                    await self.close()
                    continue

                self.x_content_properties = create_x_context_properties(location_guild_id, location_channel_id)

                status, answer = await self.accept_invite()

                if "Banned" in answer or "Incorrect discord token or your account is blocked" in answer:
                    logger.error(answer)
                    await self.close()
                    return False

                if not status:
                    logger.error(answer)
                    await self.close()
                    continue

                logger.success(answer)

                status, answer = await self.agree_with_server_rules(location_guild_id, location_channel_id)
                if not status:
                    logger.error(answer)
                    await self.close()
                    continue

                logger.success(answer)

                if self.invite_code == 'chainopera':

                    status, answer = await self.click_to_emoji(location_guild_id, location_channel_id)
                    if not status:
                        logger.error(answer)
                        await self.close()
                        continue

                    logger.success(answer)

                await self.ws.close()
                await self.close()
                await asyncio.sleep(1)

                return self.discord_token

            except Exception as e:
                logger.error(
                    f"Discord | [{self.wallet.name}] | Attempt {num}/{NUMBER_OF_ATTEMPTS} failed due to: {e}")
                if num == NUMBER_OF_ATTEMPTS:
                    return False
                await self.ws.close()
                await self.close()
                await asyncio.sleep(1)

        return False
