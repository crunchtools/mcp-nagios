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
from mcp_nagios_crunchtools import config as config_mod
from mcp_nagios_crunchtools.config import Config
from mcp_nagios_crunchtools.models import MAX_HISTORY_HOURS
from mcp_nagios_crunchtools.server import mcp
from mcp_nagios_crunchtools.tools import (
    acknowledge,
    add_comment,
    alert_history,
    cancel_downtime,
    current_problems,
    downtime_history,
    host_status,
    list_downtimes,
    notification_history,
    program_status,
    schedule_check,
    schedule_downtime,
    service_status,
)
from mcp_nagios_crunchtools.tools import commands as commands_mod
from mcp_nagios_crunchtools.tools import downtime as downtime_mod
from mcp_nagios_crunchtools.tools import history as history_mod

from .conftest import _mock_response, _patch_client

TOOL_COUNT = 13

READ_ONLY = frozenset(
    {
        "nagios_host_status_tool",
        "nagios_service_status_tool",
        "nagios_current_problems_tool",
        "nagios_program_status_tool",
        "nagios_notification_history_tool",
        "nagios_alert_history_tool",
        "nagios_list_downtimes_tool",
        "nagios_downtime_history_tool",
    }
)
# Each of these submits a Nagios external command through cmd.cgi.
WRITES = frozenset(
    {
        "nagios_acknowledge_tool",
        "nagios_add_comment_tool",
        "nagios_schedule_check_tool",
        "nagios_schedule_downtime_tool",
        "nagios_cancel_downtime_tool",
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
    "nagios_list_downtimes_tool": {"host_name": "web01"},
}
# Reads nagios.log rather than a CGI, so it sends no request at all.
FILE_READS = frozenset({"nagios_downtime_history_tool"})

# One body that answers every statusjson.cgi / archivejson.cgi query the reads make.
_ANY_QUERY_DATA: dict[str, Any] = {
    "host": {"name": "web01"},
    "service": {},
    "hostlist": {},
    "servicelist": {},
    "programstatus": {},
    "notificationlist": [],
    "alertlist": [],
    "downtimelist": {},
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
    cfg.log_path = None
    nagios_client = client_mod.NagiosClient(cfg)
    nagios_client._client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    client_mod._client = nagios_client
    with patch.object(config_mod, "get_config", return_value=cfg):
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

    @pytest.mark.parametrize("name", sorted(READ_ONLY - FILE_READS))
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


class TestCgiPrefix:
    @pytest.mark.parametrize(
        ("prefix", "base"),
        [
            (None, "https://nagios.example.com/nagios/cgi-bin"),
            ("/cgi-bin", "https://nagios.example.com/cgi-bin"),
            ("/custom/cgi-bin/", "https://nagios.example.com/custom/cgi-bin"),
        ],
    )
    def test_cgi_urls_use_prefix(
        self, monkeypatch: pytest.MonkeyPatch, prefix: str | None, base: str
    ) -> None:
        monkeypatch.setenv("NAGIOS_URL", "https://nagios.example.com")
        monkeypatch.setenv("NAGIOS_USER", "admin")
        monkeypatch.setenv("NAGIOS_PASS", "secret")
        if prefix is None:
            monkeypatch.delenv("NAGIOS_CGI_PREFIX", raising=False)
        else:
            monkeypatch.setenv("NAGIOS_CGI_PREFIX", prefix)

        cfg = Config()
        assert cfg.status_cgi_url == f"{base}/statusjson.cgi"
        assert cfg.archive_cgi_url == f"{base}/archivejson.cgi"
        assert cfg.cmd_cgi_url == f"{base}/cmd.cgi"


class TestCommentAuthor:
    @pytest.mark.parametrize(
        ("env", "expected"),
        [
            ({"NAGIOS_COMMENT_AUTHOR": "oncall", "NAGIOS_USER": "admin"}, "oncall"),
            ({"NAGIOS_USER": "admin"}, "admin"),
        ],
    )
    async def test_author_from_environment(
        self, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str
    ) -> None:
        monkeypatch.delenv("NAGIOS_COMMENT_AUTHOR", raising=False)
        monkeypatch.setenv("NAGIOS_URL", "https://nagios.example.com")
        monkeypatch.setenv("NAGIOS_PASS", "secret")
        for key, value in env.items():
            monkeypatch.setenv(key, value)

        sent: list[dict[str, str]] = []

        async def _capture(_cmd_typ: int, form_data: dict[str, str]) -> str:
            sent.append(form_data)
            return "ok"

        client = MagicMock()
        client.submit_command = _capture
        with patch.object(commands_mod, "get_client", return_value=client):
            await acknowledge("lotor", "Investigating")
            await add_comment("lotor", "Note", "HTTPS")
        assert [form["com_author"] for form in sent] == [expected, expected]


class TestReadSchemaBounds:
    async def test_hours_bounds_are_published(self) -> None:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        for name in ("nagios_notification_history_tool", "nagios_alert_history_tool"):
            hours = tools[name].parameters["properties"]["hours"]
            assert hours["minimum"] == 1
            assert hours["maximum"] == MAX_HISTORY_HOURS

    async def test_negative_hours_rejected(self) -> None:
        with pytest.raises(Exception, match="hours"):
            await mcp.call_tool("nagios_alert_history_tool", {"hours": -5})


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

    async def test_a_host_notification_is_named_by_its_host(self) -> None:
        """Regression: host entries carry `name`, not `host_name`, and read "unknown host"."""
        entry = {
            "timestamp": 1700000000000,
            "object_type": 1,
            "name": "ctr-rt.fatherlinux.com",
            "contact": "hermes",
            "method": "notify-hermes-host",
            "message": "CRITICAL - Container rt.fatherlinux.com not found",
        }
        response = _mock_response(json_data=_success_result({"notificationlist": [entry]}))
        with _patch_client(response):
            result = await notification_history(hours=1)
        assert "] ctr-rt.fatherlinux.com → hermes" in result

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
            "name": "web01",
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


def _capturing_client(sent: list[tuple[int, dict[str, str]]]) -> MagicMock:
    async def _capture(cmd_typ: int, form_data: dict[str, str]) -> str:
        sent.append((cmd_typ, form_data))
        return "Command submitted successfully"

    client = MagicMock()
    client.submit_command = _capture
    return client


class TestScheduleDowntime:
    async def test_host_downtime_covers_the_host_and_its_services(self) -> None:
        sent: list[tuple[int, dict[str, str]]] = []
        with (
            _patch_client(_mock_response(text="ok")),
            patch.object(downtime_mod, "get_client", return_value=_capturing_client(sent)),
        ):
            result = await schedule_downtime("ctr-mcp-trove", 90, "Josui: deploying trove")
        assert [cmd for cmd, _ in sent] == [
            downtime_mod.CMD_SCHEDULE_HOST_DOWNTIME,
            downtime_mod.CMD_SCHEDULE_HOST_SVC_DOWNTIME,
        ]
        form = sent[0][1]
        assert form["host"] == "ctr-mcp-trove"
        assert form["com_author"] == "josui"
        assert form["fixed"] == "1"
        assert (form["hours"], form["minutes"]) == ("1", "30")
        assert "service" not in form
        assert "and all its services" in result

    async def test_service_downtime_names_the_service(self) -> None:
        sent: list[tuple[int, dict[str, str]]] = []
        with (
            _patch_client(_mock_response(text="ok")),
            patch.object(downtime_mod, "get_client", return_value=_capturing_client(sent)),
        ):
            await schedule_downtime("lotor", 30, "deploy", "Host failed systemd units")
        assert len(sent) == 1
        cmd, form = sent[0]
        assert cmd == downtime_mod.CMD_SCHEDULE_SVC_DOWNTIME
        assert form["service"] == "Host failed systemd units"

    async def test_window_is_local_wall_clock(self) -> None:
        sent: list[tuple[int, dict[str, str]]] = []
        original_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        try:
            with (
                _patch_client(_mock_response(text="ok")),
                patch.object(downtime_mod, "get_client", return_value=_capturing_client(sent)),
            ):
                await schedule_downtime("lotor", 60, "deploy", "HTTPS")
            start = time.strftime("%m-%d-%Y %H:%M", time.localtime())
            end = time.strftime("%m-%d-%Y %H:%M", time.localtime(time.time() + 3600))
        finally:
            if original_tz is None:
                del os.environ["TZ"]
            else:
                os.environ["TZ"] = original_tz
            time.tzset()
        assert sent[0][1]["start_time"][:16] == start
        assert sent[0][1]["end_time"][:16] == end

    @pytest.mark.parametrize("minutes", [4, 481])
    async def test_length_is_bounded(self, minutes: int) -> None:
        with pytest.raises(ValidationError):
            await schedule_downtime("lotor", minutes, "deploy")

    async def test_comment_is_required(self) -> None:
        with pytest.raises(ValidationError):
            await schedule_downtime("lotor", 30, "")


def _downtime(down_id: int, host: str, author: str, service: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "downtime_id": down_id,
        "host_name": host,
        "author": author,
        "comment": "deploy",
        "start_time": 1700000000000,
        "end_time": 1700003600000 + down_id,
        "is_in_effect": True,
    }
    if service:
        entry["service_description"] = service
    return entry


class TestListAndCancelDowntime:
    async def test_list(self) -> None:
        data = {"downtimelist": {"7": _downtime(7, "ctr-mcp-trove", "josui", "MCP port")}}
        with _patch_client(_mock_response(json_data=_success_result(data))):
            result = await list_downtimes()
        assert "#7 ctr-mcp-trove / MCP port: in effect" in result
        assert "josui: deploy" in result

    async def test_list_empty(self) -> None:
        data: dict[str, Any] = {"downtimelist": {}}
        with _patch_client(_mock_response(json_data=_success_result(data))):
            assert await list_downtimes("web01") == "No scheduled downtime for host 'web01'."

    async def test_cancel_touches_only_our_downtime_on_that_host(self) -> None:
        listing = {
            "downtimelist": {
                "1": _downtime(1, "ctr-mcp-trove", "josui"),
                "2": _downtime(2, "ctr-mcp-trove", "josui", "MCP port"),
                "3": _downtime(3, "ctr-mcp-trove", "admin", "Index run"),
                "4": _downtime(4, "ctr-mcp-trove-other", "josui"),
            }
        }
        sent: list[tuple[int, dict[str, str]]] = []
        recorder = _capturing_client(sent)
        with _patch_client(_mock_response(json_data=_success_result(listing))):
            recorder.query_status = client_mod.get_client().query_status
            with patch.object(downtime_mod, "get_client", return_value=recorder):
                result = await cancel_downtime("ctr-mcp-trove")
        assert sent == [
            (downtime_mod.CMD_DEL_HOST_DOWNTIME, {"down_id": "1"}),
            (downtime_mod.CMD_DEL_SVC_DOWNTIME, {"down_id": "2"}),
        ]
        assert "Cancelled 2 downtime(s)" in result

    async def test_cancel_one_service(self) -> None:
        listing = {
            "downtimelist": {
                "1": _downtime(1, "lotor", "josui"),
                "2": _downtime(2, "lotor", "josui", "Host failed systemd units"),
            }
        }
        sent: list[tuple[int, dict[str, str]]] = []
        recorder = _capturing_client(sent)
        with _patch_client(_mock_response(json_data=_success_result(listing))):
            recorder.query_status = client_mod.get_client().query_status
            with patch.object(downtime_mod, "get_client", return_value=recorder):
                await cancel_downtime("lotor", "Host failed systemd units")
        assert sent == [(downtime_mod.CMD_DEL_SVC_DOWNTIME, {"down_id": "2"})]

    async def test_nothing_to_cancel(self) -> None:
        listing = {"downtimelist": {"3": _downtime(3, "lotor", "admin")}}
        with _patch_client(_mock_response(json_data=_success_result(listing))):
            result = await cancel_downtime("lotor")
        assert result == "No downtime by 'josui' to cancel on lotor."


# Epoch seconds an hour ago, so every window falls inside a 24h history range.
_T0 = int(time.time()) - 3600

_GRAFANA = f"ctr-grafana;{_T0};{_T0 + 900};1;0;900;josui;tig deploy; part 2"
_SYSTEMD = f"lotor;Host failed systemd units;{_T0 + 1000};{_T0 + 1600};1;0;600;admin;restart"
_LOG = "\n".join(
    f"[{ts}] {text}"
    for ts, text in [
        (_T0 - 10, "SERVICE ALERT: lotor;HTTPS;CRITICAL;HARD;3;refused"),
        (_T0, f"EXTERNAL COMMAND: SCHEDULE_HOST_SVC_DOWNTIME;{_GRAFANA}"),
        (_T0, f"EXTERNAL COMMAND: SCHEDULE_HOST_DOWNTIME;{_GRAFANA}"),
        (_T0, "HOST DOWNTIME ALERT: ctr-grafana;STARTED; Host has entered ..."),
        (_T0, "SERVICE DOWNTIME ALERT: ctr-grafana;Grafana port;STARTED; Service has ..."),
        (_T0, "SERVICE DOWNTIME ALERT: ctr-grafana;HTTPS external;STARTED; Service has ..."),
        (_T0 + 600, "SERVICE DOWNTIME ALERT: ctr-grafana;Grafana port;STOPPED; Service ..."),
        (_T0 + 700, "SERVICE DOWNTIME ALERT: ctr-grafana;HTTPS external;CANCELLED; ..."),
        (_T0 + 900, "HOST DOWNTIME ALERT: ctr-grafana;STOPPED; Host has exited ..."),
        (_T0 + 1000, f"EXTERNAL COMMAND: SCHEDULE_SVC_DOWNTIME;{_SYSTEMD}"),
        (_T0 + 1000, "SERVICE DOWNTIME ALERT: lotor;Host failed systemd units;STARTED; ..."),
    ]
)


@pytest.fixture
def nagios_log(tmp_path: Any) -> Iterator[str]:
    path = tmp_path / "nagios.log"
    path.write_text(_LOG)
    cfg = MagicMock()
    cfg.log_path = str(path)
    with patch.object(config_mod, "get_config", return_value=cfg):
        yield str(path)


class TestDowntimeHistory:
    def test_windows_are_rebuilt_from_the_log(self, nagios_log: str) -> None:
        windows = {w.label: w for w in downtime_mod._read_windows(nagios_log, (_T0 + 1200) * 1000)}
        assert set(windows) == {
            "ctr-grafana",
            "ctr-grafana / Grafana port",
            "ctr-grafana / HTTPS external",
            "lotor / Host failed systemd units",
        }
        port = windows["ctr-grafana / Grafana port"]
        assert (port.start, port.end) == (_T0 * 1000, (_T0 + 600) * 1000)
        # The service window takes its reason from SCHEDULE_HOST_SVC_DOWNTIME,
        # and a ';' inside the comment survives.
        assert (port.author, port.comment) == ("josui", "tig deploy; part 2")
        assert windows["ctr-grafana / HTTPS external"].end == (_T0 + 700) * 1000
        # Still open: ongoing, and keeps its scheduled end rather than now.
        systemd = windows["lotor / Host failed systemd units"]
        assert (systemd.end, systemd.ongoing) == ((_T0 + 1600) * 1000, True)
        assert not port.ongoing

    def test_range_keeps_windows_that_overlap_it(self, tmp_path: Any) -> None:
        path = tmp_path / "nagios.log"
        path.write_text(
            "\n".join(
                [
                    "[100] SERVICE DOWNTIME ALERT: h;before;STARTED; x",
                    "[200] SERVICE DOWNTIME ALERT: h;before;STOPPED; x",
                    "[300] SERVICE DOWNTIME ALERT: h;spanning;STARTED; x",
                    "[600] SERVICE DOWNTIME ALERT: h;spanning;STOPPED; x",
                    "[700] SERVICE DOWNTIME ALERT: h;after;STARTED; x",
                    "[800] SERVICE DOWNTIME ALERT: h;after;CANCELLED; x",
                ]
            )
        )
        windows = downtime_mod._read_windows(str(path), 900_000, since_ms=500_000)
        assert sorted(w.service or "" for w in windows) == ["after", "spanning"]

    async def test_one_scheduling_logged_across_seconds_is_one_line(self, tmp_path: Any) -> None:
        cmd = f"ctr-x;{_T0};{_T0 + 600};1;0;600;josui;deploy"
        path = tmp_path / "nagios.log"
        path.write_text(
            "\n".join(
                [
                    f"[{_T0}] EXTERNAL COMMAND: SCHEDULE_HOST_DOWNTIME;{cmd}",
                    f"[{_T0}] HOST DOWNTIME ALERT: ctr-x;STARTED; x",
                    f"[{_T0 + 1}] EXTERNAL COMMAND: SCHEDULE_HOST_SVC_DOWNTIME;{cmd}",
                    f"[{_T0 + 1}] SERVICE DOWNTIME ALERT: ctr-x;MCP port;STARTED; x",
                ]
            )
        )
        with patch.object(config_mod, "get_config", return_value=MagicMock(log_path=str(path))):
            lines = (await downtime_history(hours=24)).splitlines()
        assert lines[0].endswith("1 scheduling(s):")
        assert lines[1].startswith("  ctr-x [host; MCP port]: ")

    def test_a_repeated_start_keeps_the_original_window(self, tmp_path: Any) -> None:
        path = tmp_path / "nagios.log"
        path.write_text(
            "\n".join(
                [
                    "[100] SERVICE DOWNTIME ALERT: h;svc;STARTED; x",
                    "[150] SERVICE DOWNTIME ALERT: h;svc;STARTED; x",
                    "[200] SERVICE DOWNTIME ALERT: h;svc;STOPPED; x",
                ]
            )
        )
        windows = downtime_mod._read_windows(str(path), 900_000)
        assert [(w.start, w.end) for w in windows] == [(100_000, 200_000)]

    def test_unreadable_log_names_the_setting(self, tmp_path: Any) -> None:
        with pytest.raises(Exception, match="NAGIOS_LOG_PATH"):
            downtime_mod._read_windows(str(tmp_path / "missing.log"), 0)

    @pytest.mark.usefixtures("nagios_log")
    async def test_history_groups_one_scheduling_per_line(self) -> None:
        lines = (await downtime_history(hours=24)).splitlines()
        assert lines[0] == "Downtime windows (last 24h), 2 scheduling(s):"
        assert lines[1].startswith("  ctr-grafana [host; Grafana port; HTTPS external]: ")
        assert lines[1].endswith("(15m) | josui: tig deploy; part 2")
        assert lines[2].startswith("  lotor [Host failed systemd units]: ")
        assert lines[2].endswith("(10m, ongoing) | admin: restart")

    @pytest.mark.usefixtures("nagios_log")
    async def test_history_host_filter(self) -> None:
        result = await downtime_history(host_name="lotor", hours=24)
        assert "ctr-grafana" not in result

    async def test_history_needs_the_log(self) -> None:
        cfg = MagicMock()
        cfg.log_path = None
        with (
            patch.object(config_mod, "get_config", return_value=cfg),
            pytest.raises(Exception, match="NAGIOS_LOG_PATH"),
        ):
            await downtime_history()

    async def test_alert_history_sets_planned_work_aside(self, nagios_log: str) -> None:
        def _at(epoch: int, host: str, service: str) -> dict[str, Any]:
            return {
                "timestamp": epoch * 1000,
                "object_type": 2,
                "host_name": host,
                "description": service,
                "state_type": 1,
                "state": 32,
                "plugin_output": "CRITICAL - refused",
            }

        alerts = [
            _at(_T0 - 10, "lotor", "HTTPS"),
            _at(_T0 + 60, "ctr-grafana", "Grafana port"),
            _at(_T0 + 120, "ctr-grafana", "Grafana port"),
            _at(_T0 + 650, "ctr-grafana", "Grafana port"),
        ]
        response = _mock_response(json_data=_success_result({"alertlist": alerts}))
        with (
            _patch_client(response),
            patch.object(config_mod, "get_config", return_value=MagicMock(log_path=nagios_log)),
        ):
            lines = (await alert_history(hours=24)).splitlines()
        assert "2 host(s)/service(s)" in lines[0]
        # One unplanned event each: the two before and after the window.
        assert sorted(line.split(":")[0] for line in lines[1:3]) == [
            "  ctr-grafana / Grafana port",
            "  lotor / HTTPS",
        ]
        assert all(": 1 problem event(s)" in line for line in lines[1:3])
        assert lines[-1] == "  plus 2 event(s) on 1 host(s)/service(s) during scheduled downtime"

    async def test_alert_history_when_every_problem_was_planned(self, nagios_log: str) -> None:
        alert = {
            "timestamp": (_T0 + 60) * 1000,
            "object_type": 2,
            "host_name": "ctr-grafana",
            "description": "Grafana port",
            "state_type": 1,
            "state": 32,
            "plugin_output": "CRITICAL - refused",
        }
        response = _mock_response(json_data=_success_result({"alertlist": [alert]}))
        with (
            _patch_client(response),
            patch.object(config_mod, "get_config", return_value=MagicMock(log_path=nagios_log)),
        ):
            result = await alert_history(hours=24)
        assert result == (
            "No problem alerts in the last 24 hour(s).\n"
            "  plus 1 event(s) on 1 host(s)/service(s) during scheduled downtime"
        )


async def test_tool_count() -> None:
    tools = await mcp.list_tools()
    names = [t.name for t in tools]
    assert len(tools) == TOOL_COUNT, f"Expected {TOOL_COUNT}, got {len(tools)}: {names}"
