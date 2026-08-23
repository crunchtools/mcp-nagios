"""Nagios CGI JSON API client."""

import logging
import time
from typing import Any

import httpx

from .config import Config, get_config
from .errors import NagiosApiError, NagiosQueryError

logger = logging.getLogger(__name__)


class NagiosClient:
    """Async client for the Nagios CGI JSON API."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                auth=httpx.BasicAuth(self._config.username, self._config.password),
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def query_status(self, params: dict[str, str]) -> dict[str, Any]:
        """Query the statusjson.cgi endpoint."""
        client = await self._get_client()
        response = await client.get(self._config.status_cgi_url, params=params)
        if response.status_code != 200:
            raise NagiosApiError(response.status_code, response.text[:200])
        data: dict[str, Any] = response.json()
        result = data.get("result", {})
        if result.get("type_code", -1) != 0:
            raise NagiosQueryError(result.get("message", "Unknown error"))
        return data

    async def query_archive(self, params: dict[str, str]) -> dict[str, Any]:
        """Query the archivejson.cgi endpoint."""
        client = await self._get_client()
        response = await client.get(self._config.archive_cgi_url, params=params)
        if response.status_code != 200:
            raise NagiosApiError(response.status_code, response.text[:200])
        data: dict[str, Any] = response.json()
        result = data.get("result", {})
        if result.get("type_code", -1) != 0:
            raise NagiosQueryError(result.get("message", "Unknown error"))
        return data

    async def submit_command(self, cmd_typ: int, form_data: dict[str, str]) -> str:
        """Submit a command via cmd.cgi POST."""
        client = await self._get_client()
        payload = {
            "cmd_typ": str(cmd_typ),
            "cmd_mod": "2",
            "btnSubmit": "Commit",
            **form_data,
        }
        response = await client.post(self._config.cmd_cgi_url, data=payload)
        if response.status_code != 200:
            raise NagiosApiError(response.status_code, response.text[:200])
        body = response.text
        if "error" in body.lower() and "successfully" not in body.lower():
            raise NagiosApiError(200, body[:300])
        return "Command submitted successfully"


_client: NagiosClient | None = None


def get_client() -> NagiosClient:
    global _client
    if _client is None:
        _client = NagiosClient(get_config())
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def _format_timestamp(epoch_ms: int) -> str:
    """Convert Nagios millisecond timestamp to readable string."""
    if epoch_ms <= 0:
        return "never"
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(epoch_ms / 1000))


STATUS_MAP_HOST = {0: "PENDING", 2: "UP", 4: "DOWN", 8: "UNREACHABLE"}
STATUS_MAP_SERVICE = {0: "PENDING", 2: "OK", 4: "WARNING", 8: "UNKNOWN", 16: "CRITICAL"}
STATE_TYPE_MAP = {0: "SOFT", 1: "HARD"}
