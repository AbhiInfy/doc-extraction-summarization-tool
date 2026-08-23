from __future__ import annotations

import time
import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "HCM-Readiness-Extractor/1.0 "
        "(documentation research; +https://docs.oracle.com)"
    ),
    "Accept": "text/html,application/javascript,application/json;q=0.9,*/*;q=0.8",
}


class HttpClient:
    def __init__(self, delay_seconds: float = 0.35, timeout: int = 45) -> None:
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._last_request = 0.0

    def get(self, url: str) -> requests.Response:
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        response = self.session.get(url, timeout=self.timeout)
        self._last_request = time.monotonic()
        response.raise_for_status()
        if not response.encoding:
            response.encoding = response.apparent_encoding or "utf-8"
        return response

    def get_bytes(self, url: str) -> bytes:
        return self.get(url).content
