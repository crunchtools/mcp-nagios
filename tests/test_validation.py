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
