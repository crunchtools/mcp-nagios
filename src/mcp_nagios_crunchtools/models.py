"""Pydantic validation models for Nagios MCP server tool inputs."""

import unicodedata
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

MAX_COMMENT_LENGTH = 5000
MAX_HOSTNAME_LENGTH = 255
MAX_SERVICE_DESC_LENGTH = 255
# One month. The archive CGI returns every row in the range in one response.
MAX_HISTORY_HOURS = 744
MIN_DOWNTIME_MINUTES = 5
MAX_DOWNTIME_MINUTES = 480

# Nagios 4.5.9's statusjson.cgi aborts in __mbstowcs_chk (SIGABRT, core dumped)
# while rendering a comment that holds a byte outside ASCII. The abort takes the
# whole downtimelist/commentlist query with it, so list_downtimes and
# cancel_downtime return a bare HTTP 500 until that comment expires -- and
# cancel_downtime is the one tool that could have removed it. Scheduling goes
# through cmd.cgi and succeeds, so the break only appears on the way back out.
# Every comment is therefore folded to ASCII before it is submitted.
# See crunchtools/mcp-nagios#65.
_ASCII_SUBSTITUTIONS = {
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "--",
    "\u2015": "--",
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u201f": '"',
    "\u2026": "...",
    "\u2022": "*",
    "\u00b7": "*",
    "\u2190": "<-",
    "\u2192": "->",
    "\u21d2": "=>",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2260": "!=",
    "\u00d7": "x",
    "\u00b1": "+/-",
    "\u00b0": " deg",
    "\u2713": "[ok]",
    "\u2714": "[ok]",
    "\u2717": "[x]",
    "\u2718": "[x]",
    "\u00a9": "(c)",
    "\u00ae": "(r)",
    "\u2122": "(tm)",
    "\u00bd": "1/2",
    "\u00bc": "1/4",
    "\u00be": "3/4",
    "\u20ac": "EUR",
    "\u00a3": "GBP",
    "\u00a5": "JPY",
    "\u00a0": " ",
    "\u202f": " ",
    "\u2007": " ",
    "\u2009": " ",
    "\u200a": " ",
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\ufeff": "",
}


def to_nagios_ascii(text: str) -> str:
    """Fold prose to the ASCII subset Nagios can render.

    Punctuation that carries meaning is spelled out ("--", "...", "->") rather
    than dropped. Accented letters survive as their base letter, because NFKD
    splits them into letter plus combining mark and only the mark is lost.
    Anything with no ASCII reading at all -- an emoji, a CJK character -- is
    removed, which is why callers check the result is not empty.
    """
    substituted = "".join(_ASCII_SUBSTITUTIONS.get(char, char) for char in text)
    decomposed = unicodedata.normalize("NFKD", substituted)
    return decomposed.encode("ascii", "ignore").decode("ascii")


def _ascii_comment(value: str) -> str:
    folded = to_nagios_ascii(value).strip()
    if not folded:
        raise ValueError(
            "comment has no ASCII content. Nagios cannot store a comment outside "
            "ASCII without crashing the CGI that reads it back, so rewrite this "
            "comment in ASCII."
        )
    return folded


# Length is checked on the text as given, so a caller is told its comment is too
# long before folding quietly shortens or lengthens it.
NagiosComment = Annotated[
    str,
    Field(min_length=1, max_length=MAX_COMMENT_LENGTH),
    AfterValidator(_ascii_comment),
]


class AcknowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_name: str = Field(min_length=1, max_length=MAX_HOSTNAME_LENGTH)
    service_description: str | None = Field(default=None, max_length=MAX_SERVICE_DESC_LENGTH)
    comment: NagiosComment
    sticky: bool = True
    notify: bool = True


class CommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_name: str = Field(min_length=1, max_length=MAX_HOSTNAME_LENGTH)
    service_description: str | None = Field(default=None, max_length=MAX_SERVICE_DESC_LENGTH)
    comment: NagiosComment


class ScheduleCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_name: str = Field(min_length=1, max_length=MAX_HOSTNAME_LENGTH)
    service_description: str | None = Field(default=None, max_length=MAX_SERVICE_DESC_LENGTH)


class DowntimeInput(BaseModel):
    """A fixed downtime window starting now. Capped at 8h so a forgotten one expires."""

    model_config = ConfigDict(extra="forbid")

    host_name: str = Field(min_length=1, max_length=MAX_HOSTNAME_LENGTH)
    service_description: str | None = Field(default=None, max_length=MAX_SERVICE_DESC_LENGTH)
    comment: NagiosComment
    minutes: int = Field(ge=MIN_DOWNTIME_MINUTES, le=MAX_DOWNTIME_MINUTES)


class ListDowntimesInput(BaseModel):
    """Listing scheduled downtime, optionally only for one host."""

    model_config = ConfigDict(extra="forbid")

    host_name: str | None = Field(default=None, min_length=1, max_length=MAX_HOSTNAME_LENGTH)


class CancelDowntimeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_name: str = Field(min_length=1, max_length=MAX_HOSTNAME_LENGTH)
    service_description: str | None = Field(default=None, max_length=MAX_SERVICE_DESC_LENGTH)


class HistoryInput(BaseModel):
    """A history query: an optional host filter and a range of 1 to 744 hours."""

    model_config = ConfigDict(extra="forbid")

    host_name: str | None = Field(default=None, min_length=1, max_length=MAX_HOSTNAME_LENGTH)
    hours: int = Field(ge=1, le=MAX_HISTORY_HOURS)
