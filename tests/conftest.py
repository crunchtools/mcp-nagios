"""Test fixtures for Nagios MCP server."""

from collections.abc import Iterator
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
    import json as json_mod

    if json_data is not None:
        content = json_mod.dumps(json_data).encode()
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
def _patch_client(*responses: httpx.Response) -> Iterator[None]:
    """Patch the Nagios client to return one or more mock responses.

    A single response is reused for every call. Several are returned in order,
    which lets tools that make more than one request (current_problems fetches
    the host list, then the service list) be tested properly.
    """
    if not responses:
        raise ValueError("_patch_client requires at least one response")
    cfg = MagicMock()
    cfg.url = "https://nagios.example.com"
    cfg.username = "admin"
    cfg.password = "secret"
    cfg.status_cgi_url = "https://nagios.example.com/nagios/cgi-bin/statusjson.cgi"
    cfg.archive_cgi_url = "https://nagios.example.com/nagios/cgi-bin/archivejson.cgi"
    cfg.cmd_cgi_url = "https://nagios.example.com/nagios/cgi-bin/cmd.cgi"
    with patch.object(config_mod, "get_config", return_value=cfg):
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        if len(responses) == 1:
            mock_http.get = AsyncMock(return_value=responses[0])
            mock_http.post = AsyncMock(return_value=responses[0])
        else:
            mock_http.get = AsyncMock(side_effect=list(responses))
            mock_http.post = AsyncMock(side_effect=list(responses))
        mock_http.aclose = AsyncMock()

        nagios_client = client_mod.NagiosClient(cfg)
        nagios_client._client = mock_http
        client_mod._client = nagios_client
        yield
