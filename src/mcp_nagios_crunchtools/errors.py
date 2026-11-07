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
        self.code = code
        super().__init__(f"Nagios API error {code}: {safe_message}")


class NagiosQueryError(ToolError):
    """Raised when a Nagios query returns a non-success result."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Nagios query failed: {message}")


class NagiosCgiCrashError(ToolError):
    """Raised when the JSON CGI dies mid-query instead of answering it.

    An HTTP 500 from statusjson.cgi is a crashed CGI, not a Nagios error
    response, so it arrives as an Apache HTML page with nothing in it to read.
    The cause we have seen is a stored comment holding a character outside
    ASCII: Nagios 4.5.9 aborts in __mbstowcs_chk while rendering it.
    """

    def __init__(self, query: str) -> None:
        super().__init__(
            f"Nagios' JSON CGI crashed on the '{query}' query (HTTP 500 from "
            "Apache, no Nagios error body). The known cause is a stored comment "
            "holding a character outside ASCII, which makes Nagios 4.5.9 abort "
            "in __mbstowcs_chk while rendering it; the crash also takes "
            "cancel_downtime down, so the offending comment cannot be removed "
            "until it expires. Confirm with 'statusjson.cgi ... dumped core' in "
            "the Nagios host's journal. downtime_history reads nagios.log "
            "directly and still works. See crunchtools/mcp-nagios#65."
        )
