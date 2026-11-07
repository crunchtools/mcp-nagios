"""Test fixtures for Nagios MCP server."""

import json
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_nagios_crunchtools import client as client_mod
from mcp_nagios_crunchtools import config as config_mod


@pytest.fixture(autouse=True)
def _reset_client_singleton() -> Iterator[None]:
    """Reset global singletons between tests."""
    client_mod._client = None
    config_mod._config = None
    yield
    client_mod._client = None
    config_mod._config = None


def _mock_response(
    status_code: int = 200,
    json_data: dict[str, Any] | None = None,
    text: str = "",
) -> httpx.Response:
    if json_data is not None:
        content = json.dumps(json_data).encode()
        headers = {"content-type": "application/json"}
    else:
        content = text.encode()
        headers = {"content-type": "text/html"}
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers,
        request=httpx.Request("GET", "https://nagios.example.com/test"),
    )


@contextmanager
def _install_mock_http() -> Iterator[AsyncMock]:
    """Put a mock transport behind the Nagios client singleton and hand it over."""
    cfg = MagicMock()
    cfg.url = "https://nagios.example.com"
    cfg.username = "admin"
    cfg.password = "secret"
    cfg.status_cgi_url = "https://nagios.example.com/nagios/cgi-bin/statusjson.cgi"
    cfg.archive_cgi_url = "https://nagios.example.com/nagios/cgi-bin/archivejson.cgi"
    cfg.cmd_cgi_url = "https://nagios.example.com/nagios/cgi-bin/cmd.cgi"
    cfg.comment_author = "josui"
    cfg.log_path = None
    with patch.object(config_mod, "get_config", return_value=cfg):
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.aclose = AsyncMock()
        nagios_client = client_mod.NagiosClient(cfg)
        nagios_client._client = mock_http
        client_mod._client = nagios_client
        yield mock_http


@contextmanager
def _patch_client(*responses: httpx.Response) -> Iterator[AsyncMock]:
    """Patch the Nagios client to return one or more mock responses.

    A single response is reused for every call. Several are returned in order,
    which lets tools that make more than one request (current_problems fetches
    the host list, then the service list) be tested properly. The transport is
    handed back so a test can count the requests a tool made.
    """
    if not responses:
        raise ValueError("_patch_client requires at least one response")
    with _install_mock_http() as mock_http:
        if len(responses) == 1:
            mock_http.get = AsyncMock(return_value=responses[0])
            mock_http.post = AsyncMock(return_value=responses[0])
        else:
            mock_http.get = AsyncMock(side_effect=list(responses))
            mock_http.post = AsyncMock(side_effect=list(responses))
        yield mock_http


@contextmanager
def _patch_dispatching_client(
    reply: Callable[[dict[str, str]], Awaitable[httpx.Response]],
) -> Iterator[AsyncMock]:
    """Patch the Nagios client to choose each reply from the query it was asked.

    `_patch_client` answers in call order, which cannot describe a tool that
    fans out: the per-id downtime fetches are awaited together and may arrive
    in any order.
    """
    with _install_mock_http() as mock_http:

        async def _get(_url: str, params: dict[str, str] | None = None) -> httpx.Response:
            return await reply(params or {})

        mock_http.get = AsyncMock(side_effect=_get)
        # cmd.cgi is not a query, so it answers the same way whatever is asked.
        mock_http.post = AsyncMock(
            return_value=_mock_response(
                text="Your command request was successfully submitted to Nagios"
            )
        )
        yield mock_http
