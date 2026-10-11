"""Pydantic validation models for Nagios MCP server tool inputs."""

from pydantic import BaseModel, ConfigDict, Field

MAX_COMMENT_LENGTH = 5000
MAX_HOSTNAME_LENGTH = 255
MAX_SERVICE_DESC_LENGTH = 255
# One month. The archive CGI returns every row in the range in one response.
MAX_HISTORY_HOURS = 744


class AcknowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_name: str = Field(min_length=1, max_length=MAX_HOSTNAME_LENGTH)
    service_description: str | None = Field(default=None, max_length=MAX_SERVICE_DESC_LENGTH)
    comment: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH)
    sticky: bool = True
    notify: bool = True


class CommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_name: str = Field(min_length=1, max_length=MAX_HOSTNAME_LENGTH)
    service_description: str | None = Field(default=None, max_length=MAX_SERVICE_DESC_LENGTH)
    comment: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH)


class ScheduleCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_name: str = Field(min_length=1, max_length=MAX_HOSTNAME_LENGTH)
    service_description: str | None = Field(default=None, max_length=MAX_SERVICE_DESC_LENGTH)


class HistoryInput(BaseModel):
    """A history query: an optional host filter and a range of 1 to 744 hours."""

    model_config = ConfigDict(extra="forbid")

    host_name: str | None = Field(default=None, min_length=1, max_length=MAX_HOSTNAME_LENGTH)
    hours: int = Field(ge=1, le=MAX_HISTORY_HOURS)
