import asyncio
from functools import wraps
from typing import Tuple, Type

from loguru import logger

from data.settings import Settings


def async_retry(
    retries: int = Settings().retry,
    delay: int = 3,
    to_raise: bool = True,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            attempt = 0
            last_exc: BaseException | None = None

            wallet_name = getattr(self, "wallet", None)
            # chain = getattr(getattr(getattr(self, "client", None), "network", None), "name", "unknown").capitalize()
            module = getattr(self, "__module_name__", self.__class__.__name__)

            last_msg = None

            while attempt < retries:
                try:
                    return await func(self, *args, **kwargs)

                except asyncio.CancelledError:
                    raise

                except exceptions as e:
                    last_exc = e
                    attempt += 1
                    msg = f"{wallet_name} | {module} | {func.__name__} | Failed | attempt {attempt}/{retries}: {e}"
                    last_msg = f"{func.__name__} | attempt {attempt}/{retries}: {e}"
                    logger.warning(msg)
                    if attempt < retries:
                        await asyncio.sleep(delay)

            if to_raise and last_exc is not None:
                raise last_exc

            raise Exception(last_msg)

        return wrapper

    return decorator
