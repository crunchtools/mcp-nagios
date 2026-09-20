"""Tests for Pydantic validation models."""

import pytest
from pydantic import ValidationError

from mcp_nagios_crunchtools.models import AcknowledgeInput, CommentInput, ScheduleCheckInput


class TestAcknowledgeInput:
    def test_valid_service(self) -> None:
        inp = AcknowledgeInput(
            host_name="lotor",
            service_description="HTTPS crunchtools.com",
            comment="Working on it",
        )
        assert inp.host_name == "lotor"
        assert inp.sticky is True

    def test_valid_host_only(self) -> None:
        inp = AcknowledgeInput(host_name="lotor", comment="Investigating")
        assert inp.service_description is None

    def test_empty_hostname_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AcknowledgeInput(host_name="", comment="test")

    def test_empty_comment_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AcknowledgeInput(host_name="lotor", comment="")

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AcknowledgeInput(host_name="lotor", comment="test", extra_field="bad")  # type: ignore[call-arg]


class TestCommentInput:
    def test_valid(self) -> None:
        inp = CommentInput(host_name="lotor", comment="Test comment")
        assert inp.host_name == "lotor"

    def test_long_comment_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CommentInput(host_name="lotor", comment="x" * 5001)


class TestScheduleCheckInput:
    def test_valid_service(self) -> None:
        inp = ScheduleCheckInput(host_name="lotor", service_description="HTTPS crunchtools.com")
        assert inp.service_description == "HTTPS crunchtools.com"

    def test_valid_host_only(self) -> None:
        inp = ScheduleCheckInput(host_name="lotor")
        assert inp.service_description is None


class TestWritePathValidation:
    """The validation models are wired into the write tools, not just defined.

    These models existed and were unit-tested from the day they were written, but
    nothing in production ever instantiated them — the tools posted raw strings
    straight to cmd.cgi. Gourmand's DC004-dead_structs check is what surfaced it.
    Each test below calls the real tool and asserts it rejects the input before it
    ever reaches the client, which is the behaviour that was missing.
    """

    @pytest.mark.asyncio
    async def test_acknowledge_rejects_empty_host(self) -> None:
        from mcp_nagios_crunchtools.tools.commands import acknowledge

        with pytest.raises(ValidationError):
            await acknowledge(host_name="", comment="test")

    @pytest.mark.asyncio
    async def test_acknowledge_rejects_oversized_comment(self) -> None:
        from mcp_nagios_crunchtools.tools.commands import acknowledge

        with pytest.raises(ValidationError):
            await acknowledge(host_name="lotor", comment="x" * 5001)

    @pytest.mark.asyncio
    async def test_add_comment_rejects_empty_comment(self) -> None:
        from mcp_nagios_crunchtools.tools.commands import add_comment

        with pytest.raises(ValidationError):
            await add_comment(host_name="lotor", comment="")

    @pytest.mark.asyncio
    async def test_schedule_check_rejects_oversized_hostname(self) -> None:
        from mcp_nagios_crunchtools.tools.commands import schedule_check

        with pytest.raises(ValidationError):
            await schedule_check(host_name="h" * 256)
