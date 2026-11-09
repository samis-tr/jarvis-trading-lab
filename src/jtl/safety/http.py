"""Guarded HTTP client: allowlisted hosts only, no redirects, no proxies from env, short timeouts."""

from __future__ import annotations

from typing import Any

import httpx

from jtl.errors import DestinationRejected
from jtl.safety.endpoints import Purpose, validate_destination


class GuardedClient:
    def __init__(
        self,
        purpose: Purpose,
        *,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ):
        self.purpose = purpose

        def _guard(request: httpx.Request) -> None:
            validate_destination(str(request.url), purpose)

        self._client = httpx.Client(
            headers=headers or {},
            follow_redirects=False,
            trust_env=False,  # ignore HTTP(S)_PROXY etc. from env
            timeout=timeout,
            transport=transport,
            event_hooks={"request": [_guard]},
        )

    def get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        validate_destination(url, self.purpose)
        resp = self._client.get(url, params=params)
        if resp.is_redirect or resp.has_redirect_location or 300 <= resp.status_code < 400:
            raise DestinationRejected(f"redirect ({resp.status_code}) refused")
        return resp

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GuardedClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
