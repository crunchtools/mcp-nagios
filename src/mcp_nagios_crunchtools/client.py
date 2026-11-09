"""Nagios CGI JSON API client."""

import json
import logging
import re
import time
from importlib.metadata import version
from typing import Any

import httpx

from .config import Config, get_config
from .errors import NagiosApiError, NagiosQueryError

logger = logging.getLogger(__name__)

HTTP_OK = 200
HTTP_INTERNAL_ERROR = 500

# A `statusjson.cgi` dump of a large fleet is the biggest body here, and it is
# the one that has to stay under the limit rather than the one that defines it.
MAX_RESPONSE_SIZE = 10 * 1024 * 1024
BODY_SNIPPET_CHARS = 200
ELLIPSIS = "..."

# Identify this client by name. httpx otherwise sends `python-httpx/<version>`,
# which bot protection answers with an HTML challenge page instead of the API --
# the failure that cost an afternoon on mcp-wordpress (RT #1596). The version
# comes from installed package metadata so it cannot drift from pyproject.toml.
USER_AGENT = (
    f"mcp-nagios-crunchtools/{version('mcp-nagios-crunchtools')} "
    "(+https://github.com/crunchtools/mcp-nagios)"
)


def _body_snippet(body: bytes) -> str:
    """A short, single-line excerpt of a response body, for an error message."""
    prefix = body[: BODY_SNIPPET_CHARS * 4]
    collapsed = " ".join(prefix.decode("utf-8", errors="replace").split())
    if not collapsed:
        return "<empty body>"
    if len(collapsed) > BODY_SNIPPET_CHARS or len(body) > len(prefix):
        return collapsed[: BODY_SNIPPET_CHARS - len(ELLIPSIS)] + ELLIPSIS
    return collapsed


def _where(response: httpx.Response) -> str:
    """Which request a response answered, for an error message.

    The URL actually requested, which matters here because this client follows
    redirects: a CGI behind an SSO proxy answers from somewhere else entirely,
    and that is the case a bare status code cannot describe.
    """
    return (
        f"{response.request.method} {response.request.url} "
        f"(HTTP {response.status_code}, {response.headers.get('content-type', 'no content-type')})"
    )


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
                headers={"User-Agent": USER_AGENT},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> tuple[httpx.Response, bytes]:
        """Send one request and return it with its bounded body.

        One way out of this module, so the agent string, the ceiling and the
        error detail cannot be forgotten in one of the three call sites -- which
        is how the previous version had no ceiling at all.
        """
        client = await self._get_client()
        request = client.build_request(method, url, params=params, data=data)
        try:
            response = await client.send(request, stream=True)
            try:
                body = await self._read_capped(response)
            finally:
                await response.aclose()
        except httpx.TimeoutException as e:
            raise NagiosApiError(0, f"Request timeout: {e}") from e
        except httpx.RequestError as e:
            raise NagiosApiError(0, f"Request failed: {e}") from e

        if response.status_code != HTTP_OK:
            raise NagiosApiError(
                response.status_code, f"{_where(response)} returned {_body_snippet(body)}"
            )
        return response, body

    @staticmethod
    async def _read_capped(response: httpx.Response) -> bytes:
        """Read the body, aborting as soon as it would pass MAX_RESPONSE_SIZE.

        There was no limit here at all: a `statusjson.cgi` query that selected
        too much, or anything else answering on that URL, was read whole into
        the process. Measured before each chunk is copied in, because
        `aiter_bytes()` promises nothing about chunk size.
        """
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_SIZE:
            raise NagiosApiError(
                response.status_code,
                f"{_where(response)} declared {declared} bytes, over the "
                f"{MAX_RESPONSE_SIZE} byte limit",
            )
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > MAX_RESPONSE_SIZE:
                raise NagiosApiError(
                    response.status_code,
                    f"{_where(response)} sent over the {MAX_RESPONSE_SIZE} byte limit. "
                    "Narrow the query.",
                )
            body += chunk
        return bytes(body)

    @staticmethod
    def _envelope(response: httpx.Response, body: bytes) -> dict[str, Any]:
        """The decoded CGI envelope, or an error saying what came back instead."""
        try:
            envelope: dict[str, Any] = json.loads(body)
        except ValueError as e:
            raise NagiosApiError(
                response.status_code,
                f"{_where(response)} is not JSON ({e}): {_body_snippet(body)}",
            ) from e
        return envelope

    async def query_status(self, params: dict[str, str]) -> dict[str, Any]:
        """Query the statusjson.cgi endpoint."""
        response, body = await self._request("GET", self._config.status_cgi_url, params=params)
        envelope = self._envelope(response, body)
        result = envelope.get("result", {})
        code = result.get("type_code", -1)
        if code != 0:
            raise NagiosQueryError(result.get("message", "Unknown error"), code)
        return envelope

    async def query_archive(self, params: dict[str, str]) -> dict[str, Any]:
        """Query the archivejson.cgi endpoint."""
        response, body = await self._request("GET", self._config.archive_cgi_url, params=params)
        envelope = self._envelope(response, body)
        result = envelope.get("result", {})
        code = result.get("type_code", -1)
        if code != 0:
            raise NagiosQueryError(result.get("message", "Unknown error"), code)
        return envelope

    async def submit_command(self, cmd_typ: int, form_data: dict[str, str]) -> str:
        """Submit a command via cmd.cgi POST."""
        payload = {
            "cmd_typ": str(cmd_typ),
            "cmd_mod": "2",
            "btnSubmit": "Commit",
            **form_data,
        }
        _, raw = await self._request("POST", self._config.cmd_cgi_url, data=payload)
        # cmd.cgi answers with an HTML page, not JSON: the text is the result.
        body = raw.decode("utf-8", errors="replace")
        if "successfully submitted" in body.lower():
            return "Command submitted successfully"
        if "errorMessage" in body:
            errors = re.findall(r"errorMessage'>([^<]+)", body)
            msg = "; ".join(errors) if errors else "Unknown command error"
            raise NagiosApiError(HTTP_OK, msg)
        return "Command submitted"


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


def _format_age(elapsed_ms: int) -> str:
    """Render a duration as its two largest units, e.g. "2d 3h" or "5h 12m"."""
    minutes = max(elapsed_ms, 0) // 60000
    days, hours, mins = minutes // 1440, minutes % 1440 // 60, minutes % 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


# Bitmask values used by statusjson.cgi. PENDING is 1, not 0 -- a service that
# has never been checked returns 1, which previously fell through the map and
# was rendered as the literal "UNKNOWN(1)".
STATUS_MAP_HOST = {1: "PENDING", 2: "UP", 4: "DOWN", 8: "UNREACHABLE"}
STATUS_MAP_SERVICE = {1: "PENDING", 2: "OK", 4: "WARNING", 8: "UNKNOWN", 16: "CRITICAL"}
STATE_TYPE_MAP = {0: "SOFT", 1: "HARD"}

# States that are not problems: a host that is UP / service that is OK, and
# anything still PENDING (scheduled but not yet checked -- normal after a
# Nagios restart, or for a service whose check_period has not opened yet).
HOST_NON_PROBLEM_STATES = frozenset({1, 2})
SERVICE_NON_PROBLEM_STATES = frozenset({1, 2})

# archivejson.cgi uses a different bitmask from statusjson.cgi, one that puts
# host and service states in the same field. Read from the live CGI (4.5.9).
ARCHIVE_STATE_MAP = {
    1: "UP",
    2: "DOWN",
    4: "UNREACHABLE",
    8: "OK",
    16: "WARNING",
    32: "CRITICAL",
    64: "UNKNOWN",
}
ARCHIVE_RECOVERED_STATES = frozenset({1, 8})
ARCHIVE_STATE_TYPE_HARD = 1
ARCHIVE_OBJECT_HOST = 1
