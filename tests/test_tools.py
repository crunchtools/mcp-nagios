"""Tests for Nagios MCP server tools."""

from mcp_nagios_crunchtools.server import mcp
from mcp_nagios_crunchtools.tools import (
    acknowledge,
    add_comment,
    current_problems,
    host_status,
    notification_history,
    schedule_check,
    service_status,
)

from .conftest import _mock_response, _patch_client

TOOL_COUNT = 7


def _success_result(data: dict) -> dict:  # type: ignore[type-arg]
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
