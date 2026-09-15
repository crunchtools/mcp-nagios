"""Tests for Nagios MCP server tools."""

import os
import time
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mcp_nagios_crunchtools.server import mcp
from mcp_nagios_crunchtools.tools import (
    acknowledge,
    add_comment,
    current_problems,
    host_status,
    notification_history,
    program_status,
    schedule_check,
    service_status,
)
from mcp_nagios_crunchtools.tools import commands as commands_mod

from .conftest import _mock_response, _patch_client

TOOL_COUNT = 8


def _success_result(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "format_version": 0,
        "result": {"type_code": 0, "type_text": "Success", "message": ""},
        "data": data,
    }


class TestStatusTools:
    async def test_host_status(self) -> None:
        response = _mock_response(
            json_data=_success_result({
                "host": {
                    "name": "lotor",
                    "status": 2,
                    "state_type": 1,
                    "plugin_output": "TCP OK",
                    "last_check": 1700000000000,
                    "next_check": 1700000300000,
                    "current_attempt": 1,
                    "max_attempts": 3,
                    "last_state_change": 1699999000000,
                },
            }),
        )
        with _patch_client(response):
            result = await host_status("lotor")
        assert "lotor" in result
        assert "UP" in result
        assert "TCP OK" in result

    async def test_service_status(self) -> None:
        response = _mock_response(
            json_data=_success_result({
                "service": {
                    "host_name": "lotor",
                    "description": "HTTPS crunchtools.com",
                    "status": 2,
                    "state_type": 1,
                    "plugin_output": "HTTP OK",
                    "last_check": 1700000000000,
                    "current_attempt": 1,
                    "max_attempts": 1,
                    "last_state_change": 1699999000000,
                    "problem_has_been_acknowledged": False,
                },
            }),
        )
        with _patch_client(response):
            result = await service_status("lotor", "HTTPS crunchtools.com")
        assert "HTTPS crunchtools.com" in result
        assert "OK" in result

    async def test_current_problems_none(self) -> None:
        host_resp = _mock_response(
            json_data=_success_result({"hostlist": {"lotor": 2}}),
        )
        with _patch_client(host_resp):
            result = await current_problems()
        assert "No current problems" in result

    async def test_current_problems_with_issues(self) -> None:
        host_resp = _mock_response(
            json_data=_success_result({"hostlist": {"lotor": 4}}),
        )
        with _patch_client(host_resp):
            result = await current_problems()
        assert "DOWN" in result

    async def test_pending_host_is_not_a_problem(self) -> None:
        """statusjson.cgi returns 1 for a host that has never been checked."""
        host_resp = _mock_response(
            json_data=_success_result({"hostlist": {"lotor": 1}}),
        )
        with _patch_client(host_resp):
            result = await current_problems()
        assert "No current problems" in result
        assert "UNKNOWN(1)" not in result

    async def test_pending_service_is_not_a_problem(self) -> None:
        """A service outside its check_period is PENDING (1), not a problem.

        Regression: PENDING was mapped to 0, so a real code of 1 fell through
        to "UNKNOWN(1)" and every not-yet-checked service was reported as an
        outage -- notably after any Nagios restart.
        """
        host_resp = _mock_response(
            json_data=_success_result({"hostlist": {"lotor": 2}}),
        )
        svc_resp = _mock_response(
            json_data=_success_result(
                {
                    "servicelist": {
                        "ctr-rootsofthevalley.org": {
                            "Train tracker": 1,
                            "Water taxi tracker": 1,
                            "HTTPS": 2,
                        }
                    }
                }
            ),
        )
        with _patch_client(host_resp, svc_resp):
            result = await current_problems()
        assert "No current problems" in result
        assert "Train tracker" not in result
        assert "UNKNOWN(1)" not in result

    async def test_real_problems_still_reported_alongside_pending(self) -> None:
        host_resp = _mock_response(
            json_data=_success_result({"hostlist": {"lotor": 2}}),
        )
        svc_resp = _mock_response(
            json_data=_success_result(
                {
                    "servicelist": {
                        "ctr-rootsofthevalley.org": {
                            "Train tracker": 1,
                            "HTTPS external": 16,
                            "Container memory": 4,
                        }
                    }
                }
            ),
        )
        with _patch_client(host_resp, svc_resp):
            result = await current_problems()
        assert "CRITICAL" in result
        assert "WARNING" in result
        assert "Train tracker" not in result
        assert "1 service(s)" not in result
        assert "2 service(s)" in result

    async def test_pending_renders_as_pending_in_service_status(self) -> None:
        response = _mock_response(
            json_data=_success_result(
                {
                    "service": {
                        "host_name": "ctr-rootsofthevalley.org",
                        "description": "Train tracker",
                        "status": 1,
                        "state_type": 1,
                        "plugin_output": "",
                    }
                }
            ),
        )
        with _patch_client(response):
            result = await service_status("ctr-rootsofthevalley.org", "Train tracker")
        assert "PENDING" in result
        assert "UNKNOWN(1)" not in result


def _programstatus_response(
    query_time_ms: int = 1_789_487_149_000,
    last_data_update_ms: int = 1_789_487_147_000,
    **overrides: Any,
) -> httpx.Response:
    """Build a statusjson.cgi programstatus reply.

    query_time / last_data_update live in the `result` block, not `data` --
    that pair is what freshness is measured from.
    """
    prog: dict[str, Any] = {
        "version": "4.5.9",
        "nagios_pid": 46,
        "daemon_mode": True,
        "program_start": 1_789_464_008_000,
        "enable_notifications": True,
        "execute_service_checks": True,
        "accept_passive_service_checks": True,
        "execute_host_checks": True,
        "accept_passive_host_checks": True,
        "enable_event_handlers": True,
        "enable_flap_detection": True,
    }
    prog.update(overrides)
    result: dict[str, Any] = {"type_code": 0, "type_text": "Success", "message": ""}
    if query_time_ms:
        result["query_time"] = query_time_ms
    if last_data_update_ms:
        result["last_data_update"] = last_data_update_ms
    return _mock_response(
        json_data={
            "format_version": 0,
            "result": result,
            "data": {"programstatus": prog},
        },
    )


class TestProgramStatus:
    """The monitoring system's own health -- distinct from what it monitors."""

    async def test_healthy_daemon(self) -> None:
        with _patch_client(_programstatus_response()):
            result = await program_status()
        assert result.startswith("NAGIOS HEALTH: OK")
        assert "DEGRADED" not in result
        assert "4.5.9" in result

    async def test_wedged_daemon_is_degraded(self) -> None:
        """CGI answers 200 but status data has stopped advancing.

        This is the failure current_problems cannot see: it would cheerfully
        return "no problems" from data frozen hours ago.
        """
        response = _programstatus_response(
            query_time_ms=1_789_487_149_000,
            last_data_update_ms=1_789_486_549_000,  # 600s earlier
        )
        with _patch_client(response):
            result = await program_status()
        assert result.startswith("NAGIOS HEALTH: DEGRADED")
        assert "600s stale" in result
        assert "wedged" in result

    async def test_staleness_threshold_is_configurable(self) -> None:
        response = _programstatus_response(
            query_time_ms=1_789_487_149_000,
            last_data_update_ms=1_789_487_029_000,  # 120s earlier
        )
        with _patch_client(response):
            lenient = await program_status(max_staleness_seconds=300)
        with _patch_client(response):
            strict = await program_status(max_staleness_seconds=60)
        assert lenient.startswith("NAGIOS HEALTH: OK")
        assert strict.startswith("NAGIOS HEALTH: DEGRADED")

    async def test_notifications_globally_disabled_is_degraded(self) -> None:
        """Nagios up, checking, and telling nobody -- the quietest failure."""
        with _patch_client(_programstatus_response(enable_notifications=False)):
            result = await program_status()
        assert result.startswith("NAGIOS HEALTH: DEGRADED")
        assert "alerting nobody" in result

    @pytest.mark.parametrize(
        ("flag", "expected"),
        [
            ("execute_host_checks", "Active host checks are DISABLED"),
            ("execute_service_checks", "Active service checks are DISABLED"),
        ],
    )
    async def test_disabled_check_execution_is_degraded(self, flag: str, expected: str) -> None:
        with _patch_client(_programstatus_response(**{flag: False})):
            result = await program_status()
        assert result.startswith("NAGIOS HEALTH: DEGRADED")
        assert expected in result

    async def test_missing_flags_do_not_false_alarm(self) -> None:
        """A key Nagios never sent is not evidence of a problem.

        A health check that cries wolf gets ignored, and an ignored health
        check is worse than none.
        """
        prog = {"version": "4.5.9", "nagios_pid": 46}
        response = _mock_response(
            json_data={
                "format_version": 0,
                "result": {
                    "type_code": 0,
                    "type_text": "Success",
                    "message": "",
                    "query_time": 1_789_487_149_000,
                    "last_data_update": 1_789_487_147_000,
                },
                "data": {"programstatus": prog},
            },
        )
        with _patch_client(response):
            result = await program_status()
        assert result.startswith("NAGIOS HEALTH: OK")

    async def test_missing_timestamps_are_degraded_not_ok(self) -> None:
        """Unverifiable freshness must never be reported as healthy."""
        with _patch_client(_programstatus_response(query_time_ms=0, last_data_update_ms=0)):
            result = await program_status()
        assert result.startswith("NAGIOS HEALTH: DEGRADED")
        assert "freshness cannot be verified" in result

    async def test_staleness_ignores_local_clock(self) -> None:
        """Regression guard tied to the 0.1.2 timezone bug.

        Freshness is derived from two timestamps Nagios itself produced, so a
        container running in the wrong timezone -- or with a skewed clock --
        cannot turn a healthy daemon into a fake alarm.
        """
        response = _programstatus_response()
        original_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Pacific/Kiritimati"  # UTC+14
        time.tzset()
        try:
            with _patch_client(response):
                result = await program_status()
        finally:
            if original_tz is None:
                del os.environ["TZ"]
            else:
                os.environ["TZ"] = original_tz
            time.tzset()
        assert result.startswith("NAGIOS HEALTH: OK")
        assert "Status Data Age: 2s" in result


class TestCommandTools:
    async def test_acknowledge_service(self) -> None:
        response = _mock_response(text="Your command was successfully submitted")
        with _patch_client(response):
            result = await acknowledge("lotor", "Working on it", "HTTPS crunchtools.com")
        assert "Acknowledged" in result

    async def test_acknowledge_host(self) -> None:
        response = _mock_response(text="Your command was successfully submitted")
        with _patch_client(response):
            result = await acknowledge("lotor", "Investigating")
        assert "Acknowledged" in result

    async def test_add_comment(self) -> None:
        response = _mock_response(text="Your command was successfully submitted")
        with _patch_client(response):
            result = await add_comment("lotor", "Restarting service", "HTTPS crunchtools.com")
        assert "Comment added" in result

    async def test_schedule_check(self) -> None:
        response = _mock_response(text="Your command was successfully submitted")
        with _patch_client(response):
            result = await schedule_check("lotor", "HTTPS crunchtools.com")
        assert "Forced check scheduled" in result

    @pytest.mark.parametrize("service", [None, "HTTPS crunchtools.com"])
    async def test_schedule_check_sends_local_wall_clock(self, service: str | None) -> None:
        """Regression: start_time must be local wall-clock, never UTC.

        cmd.cgi has no timezone field -- it parses start_time in the Nagios
        server's own zone. Sending gmtime() scheduled every forced check
        UTC-offset hours into the future (4h against an EDT server), so
        "check now" silently did nothing until that time rolled around.
        """
        captured: dict[str, str] = {}

        async def _capture(_cmd_typ: int, form_data: dict[str, str]) -> str:
            captured.update(form_data)
            return "Your command was successfully submitted"

        client = MagicMock()
        client.submit_command = _capture

        original_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        try:
            with patch.object(commands_mod, "get_client", return_value=client):
                await schedule_check("lotor", service)
            local = time.strftime("%m-%d-%Y %H:%M:%S", time.localtime())
            utc = time.strftime("%m-%d-%Y %H:%M:%S", time.gmtime())
        finally:
            if original_tz is None:
                del os.environ["TZ"]
            else:
                os.environ["TZ"] = original_tz
            time.tzset()

        # Compare to the minute so a second ticking over mid-test cannot flake.
        assert captured["start_time"][:16] == local[:16]
        assert captured["start_time"][:16] != utc[:16]


class TestHistoryTools:
    async def test_notification_history(self) -> None:
        response = _mock_response(
            json_data=_success_result({
                "notificationlist": [
                    {
                        "timestamp": 1700000000000,
                        "object_type": 2,
                        "name": "lotor/HTTPS crunchtools.com",
                        "contact": "hermes",
                        "notification_type": 1,
                        "method": "notify-hermes-service",
                        "message": "CRITICAL - Connection refused",
                    },
                ],
            }),
        )
        with _patch_client(response):
            result = await notification_history(hours=1)
        assert "hermes" in result
        assert "CRITICAL" in result

    async def test_notification_history_empty(self) -> None:
        response = _mock_response(
            json_data=_success_result({"notificationlist": []}),
        )
        with _patch_client(response):
            result = await notification_history(hours=1)
        assert "No notifications" in result


async def test_tool_count() -> None:
    tools = await mcp.list_tools()
    names = [t.name for t in tools]
    assert len(tools) == TOOL_COUNT, f"Expected {TOOL_COUNT}, got {len(tools)}: {names}"
