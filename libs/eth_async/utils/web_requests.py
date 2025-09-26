from curl_cffi.requests import AsyncSession

from libs.eth_async import exceptions


def request_params(params: dict[str, ...] | None) -> dict[str, str | int | float] | None:
    """
    Convert requests params to aiohttp params.

    Args:
        params (Optional[Dict[str, Any]]): requests params.

    Returns:
        Optional[Dict[str, Union[str, int, float]]]: aiohttp params.

    """
    new_params = params.copy()
    if not params:
        return

    for key, value in params.items():
        if value is None:
            del new_params[key]

        if isinstance(value, bool):
            new_params[key] = str(value).lower()

        elif isinstance(value, bytes):
            new_params[key] = value.decode("utf-8")

    return new_params


def aiohttp_params(params: dict[str, ...] | None) -> dict[str, str | int | float] | None:
    """
    Convert requests params to aiohttp params.

    Args:
        params (Optional[Dict[str, Any]]): requests params.

    Returns:
        Optional[Dict[str, Union[str, int, float]]]: aiohttp params.

    """
    new_params = params.copy()
    if not params:
        return

    for key, value in params.items():
        if value is None:
            del new_params[key]

        if isinstance(value, bool):
            new_params[key] = str(value).lower()

        elif isinstance(value, bytes):
            new_params[key] = value.decode("utf-8")

    return new_params


async def async_get(url: str, headers: dict | None = None, **kwargs) -> dict | None:
    """
    Make a GET request and check if it was successful.

    Args:
        url (str): a URL.
        headers (Optional[dict]): the headers. (None)
        **kwargs: arguments for a GET request, e.g. 'params', 'headers', 'data' or 'json'.

    Returns:
        Optional[dict]: received dictionary in response.

    """
    async with AsyncSession() as session:
        response = await session.get(
            url=url,
            headers=headers,
            impersonate="chrome120",
            **kwargs,
            # params=params,
            # proxy=proxy_url
        )
        status_code = response.status_code

        if status_code <= 202:
            try:
                response = response.json()
                return response

            except:
                return response.text
        raise exceptions.HTTPException(response=response, status_code=status_code)


async def async_put(url: str, headers: dict | None = None, **kwargs) -> dict | None:
    """
    Make a GET request and check if it was successful.

    Args:
        url (str): a URL.
        headers (Optional[dict]): the headers. (None)
        **kwargs: arguments for a GET request, e.g. 'params', 'headers', 'data' or 'json'.

    Returns:
        Optional[dict]: received dictionary in response.

    """
    async with AsyncSession() as session:
        response = await session.put(
            url=url,
            headers=headers,
            **kwargs,
            # params=params,
            # proxy=proxy_url
        )
        status_code = response.status_code

        if status_code <= 202:
            response = response.json()
            return response
        raise exceptions.HTTPException(response=response, status_code=status_code)


async def async_post(url: str, headers: dict | None = None, cookies_return=False, **kwargs) -> dict | None:
    """
    Make a POST request and check if it was successful.

    Args:
        url (str): a URL.
        headers (Optional[dict]): the headers. (None)
        **kwargs: arguments for a GET request, e.g. 'params', 'headers', 'data' or 'json'.

    Returns:
        Optional[dict]: received dictionary in response.

    """
    async with AsyncSession() as session:
        response = await session.post(
            url=url,
            headers=headers,
            impersonate="chrome136",
            **kwargs,
            # params=params,
            # proxy=proxy_url
        )

        status_code = response.status_code

        if status_code <= 202:
            if cookies_return:
                cookies = response.cookies
                return response.json(), cookies

            else:
                return response.json()

        # if status_code <= 401:
        #     return response

        raise exceptions.HTTPException(response=response, status_code=status_code)
