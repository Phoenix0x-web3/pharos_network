from curl_cffi import requests

FINGERPRINT_DEFAULT = {
    "impersonate": "chrome",
    "headers": {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "sec-ch-ua-platform": "Windows",
        "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
        "accept-language": "en-US,en;q=0.9",
    },
}

FINGERPRINT_MAC136 = {
    "impersonate": "chrome136",
    "user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"),
    "sec-ch-ua-platform": "macOS",
    "sec-ch-ua": '"Google Chrome";v="136", "Chromium";v="136", "Not_A Brand";v="24"',
    "accept-language": "en-US,en;q=0.9",
}


class BaseAsyncSession(requests.AsyncSession):
    def __init__(
        self,
        proxy: str | None = None,
        fingerprint: dict = FINGERPRINT_DEFAULT,
        **session_kwargs,
    ):
        headers = session_kwargs.pop("headers", {})

        headers.update(fingerprint.get("headers", {}))

        init_kwargs = {
            "headers": headers,
            "impersonate": fingerprint.get("impersonate"),
            **session_kwargs,
        }

        if proxy:
            init_kwargs["proxies"] = {"http": proxy, "https": proxy}

        super().__init__(**init_kwargs)

    @property
    def user_agent(self) -> str:
        return self.headers["user-agent"]
