
import asyncio
import logging
from typing import Any, Dict, Optional

from curl_cffi.requests import AsyncSession
from web3.constants import ADDRESS_ZERO

import settings
from utils.db_api.models import Wallet

from loguru import logger


class SolviumCaptchaSolver:

    BASE_URL = "https://captcha.solvium.io/api/v1/task"

    def __init__(
        self,
        wallet: Wallet
    ) -> None:
        self.api_key = settings.solvium_api_key
        self.wallet = wallet
        self.timeout = 5
        self.max_attempts = 50
        self.headers = {"authorization": f"Bearer {self.api_key}"}

    async def _create_task(self) -> int:

        params: Dict[str, Any] = {
            "url": "https://klokapp.ai/",
            "sitekey": "0x4AAAAAABdQypM3HkDQTuaO",
        }

        headers = {"authorization": f"Bearer {self.api_key}"}

        async with AsyncSession() as session:
            r = await session.get(
                url = f"{self.BASE_URL}/turnstile",
                params=params,
                proxy=self.wallet.proxy,
                headers=self.headers
            )

            data = r.json()

            task_id = data.get("task_id")

            if task_id is None:
                raise RuntimeError(f"Failed to create captcha task: {data}")
            return task_id

    async def solve_turnstile(self) -> str:
        """Poll Solvium until the captcha solution is ready and return it."""

        task_id = await self._create_task()
        print(task_id)


        status_url = f"{self.BASE_URL}/status/{task_id}"

        for attempt in range(1, self.max_attempts + 1):

            async with AsyncSession() as session:

                r = await session.get(
                    url = status_url,
                    headers=self.headers,
                    proxy=self.wallet.proxy
                )

                data = r.json()
                print(data)
                status = data.get("status")

                if status == "completed":
                    solution = data["result"].get("solution")
                    if solution:
                        return solution
                    raise RuntimeError("Received empty solution from Solvium.")

                if status not in ("pending", "running"):
                    raise RuntimeError(f"Captcha solving failed: {data}")

                logger.debug(
                    "[Solvium] Task %s is %s (attempt %d/%d)",
                    task_id,
                    status,
                    attempt,
                    self.max_attempts,
                )
                await asyncio.sleep(5)

        raise TimeoutError("Captcha solving timed out")

class CapsolverClient:
    BASE_URL = "https://api.capsolver.com"
    CREATE_TASK = "/createTask"
    GET_RESULT = "/getTaskResult"
    POLL_DELAY = 5  # секунд между опросами результата

    def __init__(self,
                 api_key: str = settings.capsolver,
                 proxy: str | None = None,
                 wallet: Wallet = None,
                 max_attempts: int = 5):
        self.api_key = api_key
        self.proxy = proxy
        self.max_attempts = max_attempts
        self.wallet = wallet

    def __repr__(self):
        return f"{self.wallet.name if self.wallet else 'NoName Account'} | Capsolver"

    async def solve_turnstile(
        self,
        website_url: str = "https://klokapp.ai",
        sitekey: str = '0x4AAAAAABdQypM3HkDQTuaO',
        action: str = "",
    ) -> str:
        """Возвращает токен Cloudflare Turnstile или бросает исключение."""
        payload_template = {
            "clientKey": self.api_key,
            "task": {
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": website_url,
                "websiteKey": sitekey,
                "metadata": {"action": action},
            },
        }

        for attempt in range(1, self.max_attempts + 1):
            try:
                async with AsyncSession(proxy=self.proxy) as session:
                    resp = await session.post(
                        f"{self.BASE_URL}{self.CREATE_TASK}",
                        json=payload_template,
                    )
                    data = resp.json()
                    task_id = data.get("taskId")
                    if not task_id:
                        raise RuntimeError(f"{self} Нет taskId в ответе: {data}")

                token = await self._poll_result(task_id)
                return token  # если дошли сюда — получили токен

            except Exception as exc:
                logger.warning(
                    "Попытка {}/{} не удалась: {}", attempt, self.max_attempts, exc
                )
                await asyncio.sleep(self.POLL_DELAY)

        raise RuntimeError(f"{self}: все попытки исчерпаны")

    async def _poll_result(self, task_id: int) -> str:
        """Опрос статуса задачи; возвращает токен или бросает исключение при ошибке."""
        payload = {"clientKey": self.api_key, "taskId": task_id}

        while True:
            async with AsyncSession(proxy=self.proxy) as session:
                resp = await session.post(f"{self.BASE_URL}{self.GET_RESULT}", json=payload)
                data = resp.json()
                status = data.get("status")
                logger.debug(f"{self} status: {status}")

                if status == "ready":
                    token = data.get("solution", {}).get("token")
                    if token:
                        return token
                    raise RuntimeError(f"{self} Получен статус ready, но токен пуст")

                if status == "failed" or data.get("errorId"):
                    raise RuntimeError(f"{self} CapSolver вернул ошибку: {data}")

            await asyncio.sleep(self.POLL_DELAY)
#
# async def capsolver():
#     attempt = 0
#     for attempt in range(5):
#         try:
#             payload = {
#                 "clientKey": settings.capsolver,
#                 "task": {
#                     "type": 'AntiTurnstileTaskProxyLess',
#                     "websiteKey": "0x4AAAAAABdQypM3HkDQTuaO",
#                     "websiteURL": "https://klokapp.ai/",
#                     "metadata": {
#                         "action": ""  # optional
#                     }
#                 }
#             }
#
#             async with AsyncSession() as session:
#
#                 r = await session.post(
#                     url='https://api.capsolver.com/createTask',
#                     json=payload
#                 )
#
#                 task_id = r.json().get('taskId')
#
#                 if not task_id:
#                     attempt += 1
#                     raise Exception("No task ID")
#
#
#             token = None
#
#             while not token:
#                 async with AsyncSession() as session:
#                     payload = {"clientKey": settings.capsolver, "taskId": task_id}
#                     r = await session.post(
#                         url='https://api.capsolver.com/getTaskResult',
#                         json=payload
#                     )
#                     resp = r.json()
#                     status = resp.get("status")
#
#                     logger.debug(f"solving captca... status: {status}")
#                     if status == "ready":
#                         token = resp.get("solution", {}).get('token')
#                         return token
#                     if status == "failed" or resp.get("errorId"):
#                         attempt += 1
#                         logger.error("Solve failed! response:", status)
#                         raise RuntimeError(f'Captcha Failed')
#
#
#
#                 await asyncio.sleep(5)
#         except Exception as e:
#             logger.error(e)
#             continue

    #res = requests.post("https://api.capsolver.com/createTask", json=payload)
    # resp = res.json()
    # task_id = resp.get("taskId")
    # if not task_id:
    #     print("Failed to create task:", res.text)
    #     return
    # print(f"Got taskId: {task_id} / Getting result...")
    #
    # while True:
    #     #time.sleep(1)  # delay
    #     payload = {"clientKey": api_key, "taskId": task_id}
    #     #res = requests.post("https://api.capsolver.com/getTaskResult", json=payload)
    #     #resp = res.json()
    #     status = resp.get("status")
    #     if status == "ready":
    #         return resp.get("solution", {}).get('token')
    #     if status == "failed" or resp.get("errorId"):
    #         print("Solve failed! response:", res.text)
    #         return
