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
    """Raised when a Nagios query returns a non-success result.

    `code` is the CGI's own `type_code`, kept so a caller can tell one failure
    from another instead of having to read the message.
    """

    def __init__(self, message: str, code: int = -1) -> None:
        self.code = code
        super().__init__(f"Nagios query failed: {message}")


class NagiosCgiCrashError(ToolError):
    """Raised when the JSON CGI dies on a query that renders no stored string.

    An HTTP 500 from statusjson.cgi is a crashed CGI, not a Nagios error
    response, so it arrives as an Apache HTML page with nothing in it to read.
    The cause we have seen is a stored comment holding a character outside
    ASCII: Nagios 4.5.9 aborts in __mbstowcs_chk while rendering it.

    A single such comment no longer reaches this error. The downtime read path
    falls back to listing ids and fetching each one, which costs only the
    entries that cannot be rendered. This is raised when even the id list
    crashes, and the id list renders nothing a comment can poison -- so it
    means the CGI itself is broken rather than one stored comment.
    """

    def __init__(self, query: str) -> None:
        super().__init__(
            f"Nagios' JSON CGI crashed on the '{query}' id list (HTTP 500 from "
            "Apache, no Nagios error body). That query renders no stored string, "
            "so this is not the single bad comment behind mcp-nagios#65 -- which "
            "is handled by skipping the entry -- but the CGI failing outright. "
            "The crash we have on record is Nagios 4.5.9 aborting in "
            "__mbstowcs_chk over a comment holding a character outside ASCII; "
            "confirm with 'statusjson.cgi ... dumped core' in the Nagios host's "
            "journal, and check Apache's error_log for anything else. "
            "nagios_downtime_history reads nagios.log directly and still works."
        )
