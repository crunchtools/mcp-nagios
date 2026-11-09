"""The outbound HTTP contract (constitution v1.36.0, MCP Server profile Layer 3).

A real `httpx.AsyncClient` over a `MockTransport`, rather than the shared mock:
the agent string is a header the client adds and the ceiling is enforced while
the client reads, so a mock standing in for the client cannot see either.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from importlib.metadata import version
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mcp_nagios_crunchtools import client as client_mod
from mcp_nagios_crunchtools import config as config_mod
from mcp_nagios_crunchtools.errors import NagiosApiError

Handler = Callable[[httpx.Request], httpx.Response]
STATUS_URL = "https://nagios.example.com/nagios/cgi-bin/statusjson.cgi"
ARCHIVE_URL = "https://nagios.example.com/nagios/cgi-bin/archivejson.cgi"
CMD_URL = "https://nagios.example.com/nagios/cgi-bin/cmd.cgi"


async def _chunks(chunk: bytes, times: int) -> AsyncIterator[bytes]:
    """A chunked body, which carries no content-length -- what a header check misses."""
    for _ in range(times):
        yield chunk


@contextmanager
def _serving(handler: Handler) -> Iterator[None]:
    """Let the client build itself, on a mock transport."""
    cfg = MagicMock()
    cfg.username = "admin"
    cfg.password = "secret"  # gatehouse: allow-secret
    cfg.status_cgi_url = STATUS_URL
    cfg.archive_cgi_url = ARCHIVE_URL
    cfg.cmd_cgi_url = CMD_URL
    cfg.comment_author = "josui"
    cfg.log_path = None
    real = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real(transport=httpx.MockTransport(handler), **kwargs)

    # The singleton is built here rather than left to `get_client()`: the
    # module binds `get_config` at import, so patching it on the config module
    # does not reach the already-bound name.
    with (
        patch.object(config_mod, "get_config", return_value=cfg),
        patch.object(httpx, "AsyncClient", factory),
    ):
        client_mod._client = client_mod.NagiosClient(cfg)
        yield
        client_mod._client = None


class TestUserAgent:
    """A request says what it is, and the version cannot drift from the release."""

    @pytest.mark.asyncio
    async def test_outgoing_request_names_the_product_and_version(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["User-Agent"])
            return httpx.Response(200, json={"result": {"type_code": 0}})

        with _serving(handler):
            await client_mod.get_client().query_status({"query": "hostlist"})

        expected = (
            f"mcp-nagios-crunchtools/{version('mcp-nagios-crunchtools')} "
            "(+https://github.com/crunchtools/mcp-nagios)"
        )
        assert seen == [expected]
        assert "python-httpx" not in seen[0]


class TestResponseCeiling:
    """There was no limit here at all before this."""

    @pytest.mark.asyncio
    async def test_chunked_body_over_the_cap_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_mod, "MAX_RESPONSE_SIZE", 4096)

        def handler(_request: httpx.Request) -> httpx.Response:
            response = httpx.Response(
                200, headers={"content-type": "application/json"}, content=_chunks(b"x" * 1024, 16)
            )
            assert "content-length" not in response.headers
            return response

        with _serving(handler), pytest.raises(NagiosApiError) as caught:
            await client_mod.get_client().query_status({"query": "servicelist"})

        message = str(caught.value)
        assert "over the 4096 byte limit" in message
        assert "statusjson.cgi" in message
        # The remediation, because a wide query is how this gets hit.
        assert "Narrow the query" in message

    @pytest.mark.asyncio
    async def test_a_single_oversized_chunk_is_refused_before_it_is_copied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_mod, "MAX_RESPONSE_SIZE", 1024)

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=_chunks(b"x" * 8192, 1)
            )

        with _serving(handler), pytest.raises(NagiosApiError) as caught:
            await client_mod.get_client().query_status({"query": "hostlist"})

        assert "over the 1024 byte limit" in str(caught.value)


class TestErrorNamesTheSite:
    """RT #1596: the message has to say which site answered, and with what."""

    @pytest.mark.asyncio
    async def test_an_sso_page_is_quoted_with_the_request(self) -> None:
        """This client follows redirects, so the body can come from elsewhere."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, headers={"content-type": "text/html"}, text="<title>Sign in</title>"
            )

        with _serving(handler), pytest.raises(NagiosApiError) as caught:
            await client_mod.get_client().query_status({"query": "hostlist"})

        message = str(caught.value)
        assert "Sign in" in message
        assert "text/html" in message
        assert "statusjson.cgi" in message

    @pytest.mark.asyncio
    async def test_a_non_200_quotes_what_came_back(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                503, headers={"content-type": "text/html"}, text="<h1>Service Unavailable</h1>"
            )

        with _serving(handler), pytest.raises(NagiosApiError) as caught:
            await client_mod.get_client().query_status({"query": "hostlist"})

        message = str(caught.value)
        assert "Service Unavailable" in message
        assert "HTTP 503" in message


class TestEveryEndpointGoesThroughIt:
    """All three call sites share `_request`, so all three are worth asserting.

    Three copies of the transport handling is how this module ended up with no
    ceiling in any of them; a test for one of three would be the same mistake
    in test form.
    """

    @pytest.mark.asyncio
    async def test_the_archive_endpoint_sends_the_agent_and_bounds_its_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_mod, "MAX_RESPONSE_SIZE", 4096)
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["User-Agent"])
            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=_chunks(b"x" * 1024, 16)
            )

        with _serving(handler), pytest.raises(NagiosApiError) as caught:
            await client_mod.get_client().query_archive({"query": "alertlist"})

        assert "mcp-nagios-crunchtools/" in seen[0]
        assert "archivejson.cgi" in str(caught.value)

    @pytest.mark.asyncio
    async def test_the_command_endpoint_sends_the_agent_and_bounds_its_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_mod, "MAX_RESPONSE_SIZE", 4096)
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["User-Agent"])
            return httpx.Response(
                200, headers={"content-type": "text/html"}, content=_chunks(b"x" * 1024, 16)
            )

        with _serving(handler), pytest.raises(NagiosApiError) as caught:
            await client_mod.get_client().submit_command(55, {"host": "web01"})

        assert "mcp-nagios-crunchtools/" in seen[0]
        assert "cmd.cgi" in str(caught.value)

    @pytest.mark.asyncio
    async def test_the_command_endpoint_returns_its_html_result(self) -> None:
        """cmd.cgi answers with a page, not JSON: the text is the result."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="Your command request was successfully submitted to Nagios",
            )

        with _serving(handler):
            result = await client_mod.get_client().submit_command(55, {"host": "web01"})

        assert result == "Command submitted successfully"


class TestDeclaredLength:
    """The header is an early reject, not the limit itself."""

    @pytest.mark.asyncio
    async def test_a_declared_length_over_the_cap_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_mod, "MAX_RESPONSE_SIZE", 64)

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=b"x" * 128
            )

        with _serving(handler), pytest.raises(NagiosApiError) as caught:
            await client_mod.get_client().query_status({"query": "hostlist"})

        assert "declared 128 bytes" in str(caught.value)

    @pytest.mark.asyncio
    async def test_a_malformed_declared_length_does_not_crash(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            response = httpx.Response(200, json={"result": {"type_code": 0}})
            response.headers["content-length"] = "not-a-number"
            return response

        with _serving(handler):
            envelope = await client_mod.get_client().query_status({"query": "hostlist"})

        assert envelope["result"]["type_code"] == 0


class TestTransportFailures:
    """All three endpoints share these two branches."""

    @pytest.mark.asyncio
    async def test_a_timeout_becomes_an_api_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timeout")

        with _serving(handler), pytest.raises(NagiosApiError) as caught:
            await client_mod.get_client().query_status({"query": "hostlist"})

        assert "Request timeout" in str(caught.value)

    @pytest.mark.asyncio
    async def test_a_connection_failure_becomes_an_api_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("unreachable")

        with _serving(handler), pytest.raises(NagiosApiError) as caught:
            await client_mod.get_client().query_status({"query": "hostlist"})

        assert "Request failed" in str(caught.value)

    @pytest.mark.asyncio
    async def test_a_failure_mid_stream_becomes_an_api_error(self) -> None:
        """The streaming read is a new failure point: the old code read eagerly."""

        async def failing_stream() -> AsyncIterator[bytes]:
            yield b'{"result"'
            raise httpx.ReadTimeout("timeout")

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=failing_stream()
            )

        with _serving(handler), pytest.raises(NagiosApiError) as caught:
            await client_mod.get_client().query_status({"query": "hostlist"})

        assert "Request timeout" in str(caught.value)
