import asyncio
import json
import base64
import urllib.parse
from urllib.parse import urlparse
from typing import Optional, Tuple 
from loguru import logger

from utils.browser import Browser
from utils.db_api.models import Wallet
from data.settings import Settings


class CloudflareHandler:
    """Handler for Cloudflare Turnstile protection"""

    def __init__(self, wallet: Wallet):
        """
        Initialize Cloudflare handler

        Args:
            browser: Browser instance for making requests
        """
        self.browser = Browser(wallet=wallet)

    async def parse_proxy(self) -> Tuple[Optional[str], Optional[int], Optional[str], Optional[str]]:
        """
        Parse proxy string into components

        Returns:
            Tuple[ip, port, login, password]
        """
        if not self.browser.wallet.proxy:
            return None, None, None, None

        parsed = urlparse(self.browser.wallet.proxy)

        ip = parsed.hostname
        port = parsed.port
        login = parsed.username
        password = parsed.password

        return ip, port, login, password

    def encode_html_to_base64(self, html_content: str) -> str:
        """
        Encode HTML to base64

        Args:
            html_content: HTML content to encode

        Returns:
            HTML encoded in base64
        """
        # Equivalent to encodeURIComponent in JavaScript
        encoded = urllib.parse.quote(html_content)

        # Equivalent to unescape in JavaScript (replace %xx sequences)
        unescaped = urllib.parse.unquote(encoded)

        # Equivalent to btoa in JavaScript
        base64_encoded = base64.b64encode(unescaped.encode('latin1')).decode('ascii')

        return base64_encoded

    async def get_recaptcha_task(self, html: str, websiteURL: str, websiteKey: str) -> Optional[int]:
        """
        Create task for solving Cloudflare Turnstile in CapMonster

        Args:
            html: HTML page with captcha

        Returns:
            Task ID or None in case of error
        """
        try:
            # Parse proxy
            ip, port, login, password = await self.parse_proxy()

            # Encode HTML to base64
            html_base64 = self.encode_html_to_base64(html)
            windows_user_agent = Settings().actual_ua

            # Data for CapMonster request
            json_data = {
                "clientKey": Settings().capmonster_api_key,
                "task": {
                    "type": "TurnstileTask",
                    "websiteURL": f"{websiteURL}",
                    "websiteKey": f"{websiteKey}",
                    "cloudflareTaskType": "cf_clearance",
                    "htmlPageBase64": html_base64,
                    "userAgent": windows_user_agent
                }
            }

            # Add proxy data if available
            if ip and port:
                json_data["task"].update({
                    "proxyType": "http",
                    "proxyAddress": ip,
                    "proxyPort": port
                })

                if login and password:
                    json_data["task"].update({
                        "proxyLogin": login,
                        "proxyPassword": password
                    })

            # Create new session and make request
            resp = await self.browser.post(
                url='https://api.capmonster.cloud/createTask',
                json=json_data,
            )

            if resp.status_code == 200:
                result = resp.text
                result = json.loads(result)
                if result.get('errorId') == 0:
                    logger.info(f"{self.browser.wallet} created task in CapMonster: {result['taskId']}")
                    return result['taskId']
                else:
                    logger.error(f"{self.browser.wallet} CapMonster error: {result.get('errorDescription', 'Unknown error')}")
                    return None
            else:
                logger.error(f"{self.browser.wallet} CapMonster request error: {resp.status_code}")
                return None

        except Exception as e:
            logger.error(f"{self.browser.wallet} error creating task in CapMonster: {str(e)}")
            return None

    async def get_recaptcha_token(self, task_id: int) -> Optional[str]:
        """
        Get task result from CapMonster

        Args:
            task_id: Task ID

        Returns:
            cf_clearance token or None in case of error
        """
        json_data = {
            "clientKey": Settings().capmonster_api_key,
            "taskId": task_id
        }

        # Maximum wait time (60 seconds)
        max_attempts = 60

        for _ in range(max_attempts):
            try:
                resp = await self.browser.post(
                    url='https://api.capmonster.cloud/getTaskResult',
                    json=json_data,
                )

                if resp.status_code == 200:
                    result = resp.text
                    result = json.loads(result)
                    if result['status'] == 'ready':
                        # Get cf_clearance from solution
                        if 'solution' in result:
                            cf_clearance = result['solution'].get('cf_clearance') or result['solution'].get('token')
                            logger.success(f"{self.browser.wallet} obtained cf_clearance token")
                            return cf_clearance

                        logger.error(f"{self.browser.wallet} solution does not contain cf_clearance")
                        return None

                    elif result['status'] == 'processing':
                        # If task is still processing, wait 1 second
                        await asyncio.sleep(1)
                        continue
                    else:
                        logger.error(f"{self.browser.wallet} unknown task status: {result['status']}")
                        return None
                else:
                    logger.error(f"{self.browser.wallet} error getting task result: {resp.status_code}")
                    await asyncio.sleep(2)
                    continue

            except Exception as e:
                logger.error(f"{self.browser.wallet} error getting task result: {str(e)}")
                return None

        logger.error(f"{self.browser.wallet} exceeded wait time for CapMonster solution")
        return None

    async def recaptcha_handle(self, html: str, websiteURL: str, websiteKey: str) -> Optional[str]:
        """
        Handle Cloudflare Turnstile captcha through CapMonster

        Args:
            html: HTML page with captcha

        Returns:
            cf_clearance token or None in case of error
        """
        max_retry = 10
        captcha_token = None

        if not Settings().actual_ua:
            raise Exception("Insert CapMonster Api Key to files/settings.yaml")

        for i in range(max_retry):
            try:
                # Get task for solving Turnstile
                task = await self.get_recaptcha_task(html=html, websiteURL=websiteURL, websiteKey=websiteKey)
                if not task:
                    logger.error(f"{self.browser.wallet} failed to create task in CapMonster, attempt {i+1}/{max_retry}")
                    await asyncio.sleep(2)
                    continue

                # Get task result
                result = await self.get_recaptcha_token(task_id=task)
                if result:
                    captcha_token = result
                    logger.success(f"{self.browser.wallet} successfully obtained captcha token")
                    break
                else:
                    logger.warning(f"{self.browser.wallet} failed to get token, attempt {i+1}/{max_retry}")
                    await asyncio.sleep(3)
                    continue

            except Exception as e:
                logger.error(f"{self.browser.wallet} error handling captcha: {str(e)}")
                await asyncio.sleep(3)
                continue

        return captcha_token

    async def handle_cloudflare_protection(self, html: str, websiteURL: str, websiteKey: str) -> str | None:
        """
        Handle Cloudflare protection

        Args:
            html: HTML page with captcha

        Returns:
            cf_clearance token
        """
        cf_clearance = await self.recaptcha_handle(html=html, websiteURL=websiteURL, websiteKey=websiteKey)

        if cf_clearance:
            logger.success(f"{self.browser.wallet} Cloudflare protection successfully bypassed")
            return cf_clearance
        else:
            return None

    async def get_recaptcha_task_turnstile(self, websiteURL: str, websiteKey: str, cdata: str = None) -> Optional[int]:
        """
        Create task for solving Cloudflare Turnstile in CapMonster

        Args:
            html: HTML page with captcha

        Returns:
            Task ID or None in case of error
        """
        try:
            # Parse proxy
            ip, port, login, password = await self.parse_proxy()


            # Data for CapMonster request
            json_data = {
                "clientKey": Settings().capmonster_api_key,
                "task": {
                    "type": "TurnstileTaskProxyless",
                    "websiteURL": f"{websiteURL}",
                    "websiteKey": f"{websiteKey}",
                }
            }
            if cdata:
                json_data["task"].update({
                    "data": cdata
                })
            # Add proxy data if available
            if ip and port:
                json_data["task"].update({
                    "proxyType": "http",
                    "proxyAddress": ip,
                    "proxyPort": port
                })

                if login and password:
                    json_data["task"].update({
                        "proxyLogin": login,
                        "proxyPassword": password
                    })

            # Create new session and make request
            resp = await self.browser.post(
                url='https://api.capmonster.cloud/createTask',
                json=json_data,
            )

            if resp.status_code == 200:
                result = resp.text
                result = json.loads(result)
                if result.get('errorId') == 0:
                    logger.info(f"{self.browser.wallet} created task in CapMonster: {result['taskId']}")
                    return result['taskId']
                else:
                    logger.error(f"{self.browser.wallet} CapMonster error: {result.get('errorDescription', 'Unknown error')}")
                    return None
            else:
                logger.error(f"{self.browser.wallet} CapMonster request error: {resp.status_code}")
                return None

        except Exception as e:
            logger.error(f"{self.browser.wallet} error creating task in CapMonster: {str(e)}")
            return None

    async def handle_turnstile_captcha(self, websiteURL: str, websiteKey: str) -> Optional[str]:
        max_retry = 10
        captcha_token = None

        if not Settings().actual_ua:
            raise Exception("Insert CapMonster Api Key to files/settings.yaml")

        for i in range(max_retry):
            try:
                # Get task for solving Turnstile
                task = await self.get_recaptcha_task_turnstile(websiteURL=websiteURL, websiteKey=websiteKey)
                if not task:
                    logger.error(f"{self.browser.wallet} failed to create task in CapMonster, attempt {i+1}/{max_retry}")
                    await asyncio.sleep(2)
                    continue

                # Get task result
                result = await self.get_recaptcha_token(task_id=task)
                if result:
                    captcha_token = result
                    logger.success(f"{self.browser.wallet} successfully obtained captcha token")
                    break
                else:
                    logger.warning(f"{self.browser.wallet} failed to get token, attempt {i+1}/{max_retry}")
                    await asyncio.sleep(3)
                    continue

            except Exception as e:
                logger.error(f"{self.browser.wallet} error handling captcha: {str(e)}")
                await asyncio.sleep(3)
                continue

        return captcha_token
