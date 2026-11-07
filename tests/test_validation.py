"""Tests for Pydantic validation models."""

import pytest
from pydantic import ValidationError

from mcp_nagios_crunchtools.models import (
    AcknowledgeInput,
    CommentInput,
    DowntimeInput,
    ListDowntimesInput,
    ScheduleCheckInput,
    to_nagios_ascii,
)


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


class TestListDowntimesInput:
    def test_host_is_optional(self) -> None:
        assert ListDowntimesInput().host_name is None

    def test_single_character_host(self) -> None:
        assert ListDowntimesInput(host_name="h").host_name == "h"

    @pytest.mark.parametrize("host", ["", "h" * 256])
    def test_bad_host_rejected(self, host: str) -> None:
        with pytest.raises(ValidationError):
            ListDowntimesInput(host_name=host)


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


class TestCommentAsciiFolding:
    """Nagios 4.5.9 crashes rendering a non-ASCII comment, so none reach it.

    See crunchtools/mcp-nagios#65. The real comment that broke production is
    the em-dash case; the rest guard the substitutions around it.
    """

    def test_em_dash_folded(self) -> None:
        inp = DowntimeInput(
            host_name="gloval.dc4.crunchtools.com",
            comment="not a backup failure \u2014 ages are inside thresholds",
            minutes=60,
        )
        assert inp.comment == "not a backup failure -- ages are inside thresholds"
        inp.comment.encode("ascii")

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("en \u2013 dash", "en - dash"),
            ("\u201csmart\u201d quotes", '"smart" quotes'),
            ("it\u2019s", "it's"),
            ("wait\u2026", "wait..."),
            ("a \u2192 b", "a -> b"),
            ("load \u2265 10", "load >= 10"),
            ("caf\u00e9", "cafe"),
            ("hard\u00a0space", "hard space"),
            ("\u2022 bullet", "* bullet"),
            ("plain ascii", "plain ascii"),
        ],
    )
    def test_substitutions(self, raw: str, expected: str) -> None:
        assert CommentInput(host_name="lotor", comment=raw).comment == expected

    def test_every_comment_field_folds(self) -> None:
        dashed = "restarting \u2014 idle seat"
        assert AcknowledgeInput(host_name="lotor", comment=dashed).comment == (
            "restarting -- idle seat"
        )
        assert CommentInput(host_name="lotor", comment=dashed).comment == (
            "restarting -- idle seat"
        )
        assert DowntimeInput(host_name="lotor", comment=dashed, minutes=5).comment == (
            "restarting -- idle seat"
        )

    def test_comment_with_no_ascii_reading_rejected(self) -> None:
        # Folding would leave an empty comment, which Nagios rejects anyway.
        with pytest.raises(ValidationError, match="no ASCII content"):
            CommentInput(host_name="lotor", comment="\U0001f6a8\U0001f6a8")

    def test_length_checked_before_folding(self) -> None:
        with pytest.raises(ValidationError):
            CommentInput(host_name="lotor", comment="\u2014" * 5001)


def test_to_nagios_ascii_leaves_ascii_untouched() -> None:
    text = "ServerBackups-Weekly-1: 10/15 fresh (worst 4d) -> OK"
    assert to_nagios_ascii(text) == text
