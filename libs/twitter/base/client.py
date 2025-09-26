from .session import BaseAsyncSession


class BaseHTTPClient:
    _DEFAULT_HEADERS = None

    def __init__(self, **session_kwargs):
        headers = session_kwargs.pop("headers", None)
        if headers:
            for k, v in self._DEFAULT_HEADERS.items():
                headers.setdefault(k, v)

        self._session = BaseAsyncSession(
            headers=headers or self._DEFAULT_HEADERS,
            **session_kwargs,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        await self._session.close()
