from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
import time
import requests

T = TypeVar("T")

DEFAULT_HEADERS = {
    "User-Agent": (
        "HCM-Readiness-Extractor/1.0 "
        "(documentation research; +https://docs.oracle.com)"
    ),
    "Accept": "text/html,application/javascript,application/json;q=0.9,*/*;q=0.8",
}

RETRYABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def request_with_retry(send: Callable[[], T], attempts: int = 3, pause: float = 1.25) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return send()
        except RETRYABLE as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(pause * attempt)
    assert last_error is not None
    raise last_error


def is_connection_drop(exc: BaseException | str) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "connection aborted",
            "remotedisconnected",
            "connection reset",
            "timed out",
            "read timed out",
            "remote end closed",
        )
    )


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

        def send() -> requests.Response:
            return self.session.get(url, timeout=self.timeout)

        response = request_with_retry(send)
        self._last_request = time.monotonic()
        response.raise_for_status()
        if not response.encoding:
            response.encoding = response.apparent_encoding or "utf-8"
        return response

    def get_bytes(self, url: str) -> bytes:
        return self.get(url).content
