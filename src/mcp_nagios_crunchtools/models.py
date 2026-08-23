"""Pydantic validation models for Nagios MCP server write operations."""

from pydantic import BaseModel, ConfigDict, Field

MAX_COMMENT_LENGTH = 5000
MAX_HOSTNAME_LENGTH = 255
MAX_SERVICE_DESC_LENGTH = 255


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
