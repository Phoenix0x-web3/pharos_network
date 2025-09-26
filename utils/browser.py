from typing import Optional

from libs.baseAsyncSession import BaseAsyncSession
from utils.db_api.models import Wallet


class Browser:
    __module__ = "Browser"

    def __init__(self, wallet: Optional[Wallet] = None):
        self.wallet: Optional[Wallet] = wallet
        self.async_session: Optional[BaseAsyncSession] = None

    async def _ensure_session(self):
        if self.async_session is None:
            proxy = self.wallet.proxy if self.wallet else None
            self.async_session = BaseAsyncSession(proxy=proxy)

    async def _close_session(self):
        if self.async_session:
            await self.async_session.close()
            self.async_session = None

    async def get(self, **kwargs):
        await self._ensure_session()
        try:
            return await self.async_session.get(**kwargs)
        finally:
            await self._close_session()

    async def post(self, **kwargs):
        await self._ensure_session()
        try:
            return await self.async_session.post(**kwargs)
        finally:
            await self._close_session()

    async def put(self, **kwargs):
        await self._ensure_session()
        try:
            return await self.async_session.put(**kwargs)
        finally:
            await self._close_session()
