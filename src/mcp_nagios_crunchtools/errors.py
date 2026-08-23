"""Error types for Nagios MCP server."""

import os

from fastmcp.exceptions import ToolError


class ConfigurationError(ToolError):
    """Raised when required configuration is missing or invalid."""


class NagiosApiError(ToolError):
    """Raised when the Nagios CGI API returns an error."""

    def __init__(self, code: int, message: str) -> None:
        password = os.environ.get("NAGIOS_PASS", "")
        safe_message = message.replace(password, "***") if password else message
        super().__init__(f"Nagios API error {code}: {safe_message}")


class NagiosQueryError(ToolError):
    """Raised when a Nagios query returns a non-success result."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Nagios query failed: {message}")
