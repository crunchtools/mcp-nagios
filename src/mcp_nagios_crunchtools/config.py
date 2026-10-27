"""Secure configuration handling for Nagios MCP server."""

import logging
import os

from pydantic import SecretStr

from .errors import ConfigurationError

logger = logging.getLogger(__name__)


class Config:
    """Configuration from environment variables. Passwords stored as SecretStr."""

    def __init__(self) -> None:
        url = os.environ.get("NAGIOS_URL")
        if not url:
            raise ConfigurationError("NAGIOS_URL environment variable required.")

        username = os.environ.get("NAGIOS_USER")
        if not username:
            raise ConfigurationError("NAGIOS_USER environment variable required.")

        password = os.environ.get("NAGIOS_PASS")
        if not password:
            raise ConfigurationError("NAGIOS_PASS environment variable required.")

        self._url = url.rstrip("/")
        self._username = username
        self._password = SecretStr(password)
        cgi_prefix = os.environ.get("NAGIOS_CGI_PREFIX", "/nagios/cgi-bin").strip("/")
        self._cgi_prefix = f"/{cgi_prefix}" if cgi_prefix else ""
        # Set by the operator, never by the tool caller: the caller must not
        # choose whose name goes on the record.
        self._comment_author = os.environ.get("NAGIOS_COMMENT_AUTHOR") or username or "Hermes"
        # Optional read-only path to nagios.log. archivejson.cgi never returns
        # downtime start/stop entries (it reads them only for availability), so
        # downtime history comes from the log itself.
        self._log_path = os.environ.get("NAGIOS_LOG_PATH") or None

        logger.info("Configuration loaded successfully")

    @property
    def url(self) -> str:
        return self._url

    @property
    def username(self) -> str:
        return self._username

    @property
    def comment_author(self) -> str:
        return self._comment_author

    @property
    def log_path(self) -> str | None:
        return self._log_path

    @property
    def password(self) -> str:
        return self._password.get_secret_value()

    @property
    def status_cgi_url(self) -> str:
        return f"{self._url}{self._cgi_prefix}/statusjson.cgi"

    @property
    def archive_cgi_url(self) -> str:
        return f"{self._url}{self._cgi_prefix}/archivejson.cgi"

    @property
    def cmd_cgi_url(self) -> str:
        return f"{self._url}{self._cgi_prefix}/cmd.cgi"

    def __repr__(self) -> str:
        return f"Config(url={self._url!r}, user={self._username!r}, password=***)"

    def __str__(self) -> str:
        return f"Config(url={self._url!r}, user={self._username!r}, password=***)"


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
