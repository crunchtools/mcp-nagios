"""Tests for Nagios MCP server tools."""

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from mcp_nagios_crunchtools import client as client_mod
from mcp_nagios_crunchtools.server import mcp
from mcp_nagios_crunchtools.tools import (
    acknowledge,
    add_comment,
    alert_history,
    current_problems,
    host_status,
    notification_history,
    program_status,
    schedule_check,
    service_status,
)
from mcp_nagios_crunchtools.tools import commands as commands_mod
from mcp_nagios_crunchtools.tools import history as history_mod

from .conftest import _mock_response, _patch_client

TOOL_COUNT = 9

READ_ONLY = frozenset(
    {
        "nagios_host_status_tool",
        "nagios_service_status_tool",
        "nagios_current_problems_tool",
        "nagios_program_status_tool",
        "nagios_notification_history_tool",
        "nagios_alert_history_tool",
    }
)
# Each of these submits a Nagios external command through cmd.cgi.
WRITES = frozenset(
    {
        "nagios_acknowledge_tool",
        "nagios_add_comment_tool",
        "nagios_schedule_check_tool",
    }
)

# Arguments that satisfy each read-only tool's required parameters.
READ_ONLY_CALLS: dict[str, dict[str, Any]] = {
    "nagios_host_status_tool": {"host_name": "web01"},
    "nagios_service_status_tool": {"host_name": "web01", "service_description": "HTTPS"},
    "nagios_current_problems_tool": {},
    "nagios_program_status_tool": {},
    "nagios_notification_history_tool": {"host_name": "web01", "hours": 1},
    "nagios_alert_history_tool": {"host_name": "web01", "hours": 1},
}

# One body that answers every statusjson.cgi / archivejson.cgi query the reads make.
_ANY_QUERY_DATA: dict[str, Any] = {
    "host": {"name": "web01"},
    "service": {},
    "hostlist": {},
    "servicelist": {},
    "programstatus": {},
    "notificationlist": [],
    "alertlist": [],
}


@contextmanager
def _recording_client() -> Iterator[list[httpx.Request]]:
    """Run the real NagiosClient over a transport that records each request."""
    seen: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "format_version": 0,
                "result": {"type_code": 0, "type_text": "Success", "message": ""},
                "data": _ANY_QUERY_DATA,
            },
        )

    cfg = MagicMock()
    cfg.status_cgi_url = "https://nagios.example.com/nagios/cgi-bin/statusjson.cgi"
    cfg.archive_cgi_url = "https://nagios.example.com/nagios/cgi-bin/archivejson.cgi"
    cfg.cmd_cgi_url = "https://nagios.example.com/nagios/cgi-bin/cmd.cgi"
    nagios_client = client_mod.NagiosClient(cfg)
    nagios_client._client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    client_mod._client = nagios_client
    yield seen


class TestReadOnlyAnnotation:
    """Every registered tool is classified, and the reads really only read."""

    async def test_every_tool_is_classified(self) -> None:
        tools = await mcp.list_tools()
        assert READ_ONLY.isdisjoint(WRITES)
        assert {tool.name for tool in tools} == READ_ONLY | WRITES
        annotated = {
            tool.name
            for tool in tools
            if tool.annotations is not None
            and tool.annotations.model_dump(by_alias=True).get("readOnlyHint") is True
        }
        assert annotated == READ_ONLY

    @pytest.mark.parametrize("name", sorted(READ_ONLY))
    async def test_read_only_tool_only_sends_get(self, name: str) -> None:
        """A read never reaches cmd.cgi, which is how Nagios takes a command.

        cmd.cgi accepts a command over GET as well as POST, so the path is
        checked along with the method.
        """
        with _recording_client() as seen:
            await mcp.call_tool(name, READ_ONLY_CALLS[name])
        assert seen
        for request in seen:
            assert request.method in {"GET", "HEAD"}
            assert not request.url.path.endswith("/cmd.cgi")


def _success_result(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "format_version": 0,
        "result": {"type_code": 0, "type_text": "Success", "message": ""},
        "data": data,
    }


class TestStatusTools:
    async def test_host_status(self) -> None:
        response = _mock_response(
            json_data=_success_result(
                {
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
                }
            ),
        )
        with _patch_client(response):
            result = await host_status("lotor")
        assert "lotor" in result
        assert "UP" in result
        assert "TCP OK" in result

    async def test_service_status(self) -> None:
        response = _mock_response(
            json_data=_success_result(
                {
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
                }
            ),
        )
        with _patch_client(response):
            result = await service_status("lotor", "HTTPS crunchtools.com")
        assert "HTTPS crunchtools.com" in result
        assert "OK" in result

    async def test_current_problems_none(self) -> None:
        host_resp = _mock_response(
            json_data=_success_result({"hostlist": {"lotor": {"status": 2}}}),
        )
        with _patch_client(host_resp):
            result = await current_problems()
        assert "No current problems" in result

    async def test_current_problems_with_issues(self) -> None:
        host_resp = _mock_response(
            json_data=_success_result({"hostlist": {"lotor": {"status": 4}}}),
        )
        with _patch_client(host_resp):
            result = await current_problems()
        assert "DOWN" in result

    async def test_pending_host_is_not_a_problem(self) -> None:
        """statusjson.cgi returns 1 for a host that has never been checked."""
        host_resp = _mock_response(
            json_data=_success_result({"hostlist": {"lotor": {"status": 1}}}),
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
            json_data=_success_result({"hostlist": {"lotor": {"status": 2}}}),
        )
        svc_resp = _mock_response(
            json_data=_success_result(
                {
                    "servicelist": {
                        "ctr-rootsofthevalley.org": {
                            "Train tracker": {"status": 1},
                            "Water taxi tracker": {"status": 1},
                            "HTTPS": {"status": 2},
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
            json_data=_success_result({"hostlist": {"lotor": {"status": 2}}}),
        )
        svc_resp = _mock_response(
            json_data=_success_result(
                {
                    "servicelist": {
                        "ctr-rootsofthevalley.org": {
                            "Train tracker": {"status": 1},
                            "HTTPS external": {"status": 16},
                            "Container memory": {"status": 4},
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

    async def test_current_problem_carries_its_detail(self) -> None:
        """State alone is not actionable: say since when, how sure, and what the plugin said."""
        three_hours_ago = int((time.time() - 3 * 3600 - 300) * 1000)
        host_resp = _mock_response(
            json_data=_success_result({"hostlist": {"lotor": {"status": 2}}}),
        )
        disk = {
            "status": 4,
            "state_type": 1,
            "current_attempt": 3,
            "max_attempts": 3,
            "last_state_change": three_hours_ago,
            "problem_has_been_acknowledged": True,
            "scheduled_downtime_depth": 1,
            "plugin_output": "DISK WARNING - free space: / 9GB (12%)",
        }
        svc_resp = _mock_response(
            json_data=_success_result({"servicelist": {"lotor": {"Host disk root": disk}}}),
        )
        with _patch_client(host_resp, svc_resp):
            result = await current_problems()
        assert "lotor / Host disk root: WARNING for 3h 5m (since " in result
        assert "HARD 3/3, acknowledged, in downtime" in result
        assert "DISK WARNING - free space: / 9GB (12%)" in result

    async def test_current_problem_without_optional_detail(self) -> None:
        """A soft, unacknowledged problem with no state-change time claims none of them."""
        host_resp = _mock_response(
            json_data=_success_result({"hostlist": {"lotor": {"status": 2}}}),
        )
        soft = {"status": 16, "state_type": 0, "current_attempt": 1, "max_attempts": 3}
        svc_resp = _mock_response(
            json_data=_success_result({"servicelist": {"lotor": {"HTTPS": soft}}}),
        )
        with _patch_client(host_resp, svc_resp):
            result = await current_problems()
        assert "  lotor / HTTPS: CRITICAL, SOFT 1/3 | " in result
        assert "acknowledged" not in result
        assert "in downtime" not in result
        assert " for " not in result

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
            json_data=_success_result(
                {
                    "notificationlist": [
                        {
                            "timestamp": 1700000000000,
                            "object_type": 2,
                            "host_name": "lotor",
                            "description": "HTTPS crunchtools.com",
                            "contact": "hermes",
                            "notification_type": 1,
                            "method": "notify-hermes-service",
                            "message": "CRITICAL - Connection refused",
                        },
                    ],
                }
            ),
        )
        with _patch_client(response):
            result = await notification_history(hours=1)
        assert "hermes" in result
        assert "CRITICAL" in result
        # Regression: the row read a `name` field archivejson.cgi does not
        # return, so every notification was reported as "Service unknown".
        assert "lotor / HTTPS crunchtools.com → hermes" in result
        assert "unknown" not in result

    async def test_notification_history_empty(self) -> None:
        response = _mock_response(
            json_data=_success_result({"notificationlist": []}),
        )
        with _patch_client(response):
            result = await notification_history(hours=1)
        assert "No notifications" in result


def _alert(minute: int, service: str, state: int, state_type: int, output: str) -> dict[str, Any]:
    return {
        "timestamp": 1700000000000 + minute * 60000,
        "object_type": 2,
        "host_name": "lotor",
        "description": service,
        "state_type": state_type,
        "state": state,
        "plugin_output": output,
    }


class TestAlertHistory:
    async def test_rolls_up_per_service_noisiest_first(self) -> None:
        alerts = [
            _alert(0, "RT FastCGI", 32, 2, "CRITICAL - 0 processes"),
            _alert(1, "RT FastCGI", 8, 2, "OK - 1 processes running"),
            _alert(2, "Host disk root", 16, 1, "DISK WARNING - 12% free"),
            _alert(5, "RT FastCGI", 32, 1, "CRITICAL - 0 processes (minimum 1)"),
            _alert(6, "RT FastCGI", 8, 1, "OK - 1 processes running"),
        ]
        response = _mock_response(json_data=_success_result({"alertlist": alerts}))
        with _patch_client(response):
            lines = (await alert_history(hours=168)).splitlines()
        assert "2 host(s)/service(s)" in lines[0]
        assert lines[1].startswith("  lotor / RT FastCGI: 2 problem event(s) (2 CRITICAL; 1 hard),")
        assert "last seen OK | CRITICAL - 0 processes (minimum 1)" in lines[1]
        assert lines[2].startswith("  lotor / Host disk root: 1 problem event(s) (1 WARNING;")
        assert "last seen WARNING" in lines[2]

    async def test_a_host_alert_is_named_by_host_alone(self) -> None:
        alert = {
            "timestamp": 1700000000000,
            "object_type": 1,
            "host_name": "web01",
            "state": 2,
            "state_type": 1,
        }
        response = _mock_response(json_data=_success_result({"alertlist": [alert]}))
        with _patch_client(response):
            result = await alert_history(hours=24)
        assert "  web01: 1 problem event(s) (1 DOWN; 1 hard)" in result

    async def test_order_comes_from_timestamps_not_from_the_response(self) -> None:
        alerts = [
            _alert(6, "RT FastCGI", 8, 1, "OK - 1 processes running"),
            _alert(5, "RT FastCGI", 32, 1, "CRITICAL - later"),
            _alert(0, "RT FastCGI", 32, 2, "CRITICAL - earlier"),
        ]
        response = _mock_response(json_data=_success_result({"alertlist": alerts}))
        with _patch_client(response):
            result = await alert_history(hours=24)
        assert "last seen OK | CRITICAL - later" in result

    async def test_only_the_noisiest_objects_are_listed(self) -> None:
        count = history_mod.MAX_ALERT_OBJECTS + 3
        alerts = [_alert(i, f"svc-{i}", 32, 1, "CRITICAL") for i in range(count)]
        response = _mock_response(json_data=_success_result({"alertlist": alerts}))
        with _patch_client(response):
            lines = (await alert_history(hours=24)).splitlines()
        assert len(lines) == history_mod.MAX_ALERT_OBJECTS + 2
        assert lines[-1] == "  ... and 3 quieter one(s) not shown"

    @pytest.mark.parametrize("hours", [0, 745])
    async def test_range_is_bounded(self, hours: int) -> None:
        with pytest.raises(ValidationError):
            await alert_history(hours=hours)
        with pytest.raises(ValidationError):
            await notification_history(hours=hours)

    async def test_host_name_is_length_bounded(self) -> None:
        with pytest.raises(ValidationError):
            await alert_history(host_name="h" * 256)

    async def test_recoveries_alone_are_not_reported(self) -> None:
        alerts = [_alert(0, "HTTPS", 8, 1, "OK")]
        response = _mock_response(json_data=_success_result({"alertlist": alerts}))
        with _patch_client(response):
            result = await alert_history(hours=24)
        assert "No problem alerts" in result


async def test_tool_count() -> None:
    tools = await mcp.list_tools()
    names = [t.name for t in tools]
    assert len(tools) == TOOL_COUNT, f"Expected {TOOL_COUNT}, got {len(tools)}: {names}"
