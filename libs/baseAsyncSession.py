from curl_cffi import requests

FINGERPRINT_DEFAULT = {
    "impersonate": "chrome136",   
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "sec-ch-ua-platform": "Windows",
    "sec-ch-ua": 'Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99',
    "accept-language" : "en-US,en;q=0.9",
}

class BaseAsyncSession(requests.AsyncSession):
    def __init__(
            self,
            proxy: str = None,
            fingerprint: dict = FINGERPRINT_DEFAULT,
            **session_kwargs,
    ):
        headers = session_kwargs.pop("headers", {})

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