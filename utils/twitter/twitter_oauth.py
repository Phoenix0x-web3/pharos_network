import uuid
import base64
import secrets
from data.config import logger
from curl_cffi import requests


DEFAULT_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

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

class Twitter:

    def __init__(self, auth_token, address, version: str, session: BaseAsyncSession):
        self.auth_token = auth_token
        self.address = address
        self.version = version
        self.platfrom = '136'
        self.ct0 = secrets.token_hex(16)

        self.async_session = session

    async def request_oauth2_auth_code(
            self,
            oauth_data
    ) -> str:

        cookies = {
            'auth_token': self.auth_token,
            'ct0': self.ct0
        }

        url = "https://x.com/i/api/2/oauth2/authorize"
        headers = self.base_headers()

        headers['x-csrf-token'] = self.ct0

        params = {
            "response_type": oauth_data.get('response_type'),
            "client_id": oauth_data.get('client_id'),
            "redirect_uri":  oauth_data.get('redirect_uri'),
            "state": oauth_data.get('state'),
            "code_challenge": oauth_data.get('code_challenge'),
            "code_challenge_method": oauth_data.get('code_challenge_method'),
            "scope": oauth_data.get('scope'),
        }

        response = await self.async_session.get(url, headers=headers, params=params, cookies=cookies)

        if response.status_code <= 202:
            auth_code = response.json().get('auth_code')
            return auth_code

        logger.error(f'Status code {response.status_code}. Response: {response.text}')
        raise Exception(f'Status code {response.status_code}. Response: {response.text}')

    async def confirm_auth_code(self, oauth_data, auth_code):

        x_uuid = self.generate_client_uuid()
        transaction_id = self.generate_client_transaction_id()

        cookies = {
            'auth_token': self.auth_token,
            'ct0': self.ct0
        }

        client_id = oauth_data.get('client_id')
        redirect_uri = oauth_data.get('redirect_uri')
        state = oauth_data.get('state')
        response_type = oauth_data.get('response_type')
        code_challenge = oauth_data.get('code_challenge')
        code_challenge_method = oauth_data.get('code_challenge_method')
        scope = oauth_data.get('scope')

        referer = f'https://twitter.com/i/oauth2/authorize?response_type={response_type}&client_id={client_id}&redirect_uri={redirect_uri}&state={state}&code_challenge={code_challenge}&code_challenge_method={code_challenge_method}&scope={scope}'

        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://x.com',
            'priority': 'u=1, i',
            'referer': referer,
            'sec-ch-ua': f'"Google Chrome";v="{self.version}", "Chromium";v="{self.version}", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f'"{self.platfrom}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': DEFAULT_UA,
            'x-client-transaction-id': transaction_id,
            'x-client-uuid': x_uuid,
            'x-csrf-token': self.ct0,
            'x-twitter-active-user': 'yes',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'en',
        }

        data = {
            'approval': 'true',
            'code': auth_code,
        }


        response = await self.async_session.post('https://twitter.com/i/api/2/oauth2/authorize', headers=headers, cookies=cookies, data=data)

        if response.status_code <= 202:
            return response.json().get("redirect_uri")

        logger.error(f'Status code {response.status_code}. Response: {response.text}')
        raise Exception(f'Status code {response.status_code}. Response: {response.text}')

    @staticmethod
    def generate_client_transaction_id():
        random_bytes = secrets.token_bytes(70)
        transaction_id = base64.b64encode(random_bytes).decode('ascii').rstrip('=')

        return transaction_id

    @staticmethod
    def generate_client_uuid():
        return str(uuid.uuid4())

    def base_headers(self):
        return {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'priority': 'u=1, i',
            'sec-ch-ua': f'"Google Chrome";v="{self.version}", "Chromium";v="{self.version}", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f'"{self.platfrom}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': DEFAULT_UA,
            'x-client-transaction-id': self.generate_client_transaction_id(),
            'x-client-uuid': self.generate_client_uuid(),
            'x-twitter-active-user': 'yes',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'en',
        }

