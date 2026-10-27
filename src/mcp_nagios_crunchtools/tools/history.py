"""Nagios notification and alert history tools."""

import time
from typing import Any

from ..client import (
    ARCHIVE_OBJECT_HOST,
    ARCHIVE_RECOVERED_STATES,
    ARCHIVE_STATE_MAP,
    ARCHIVE_STATE_TYPE_HARD,
    _format_timestamp,
    get_client,
)
from ..models import HistoryInput
from .downtime import downtime_windows

# A week of alerts on a busy host runs to thousands of rows; the rollup is what
# a reader needs, and the noisiest objects come first.
MAX_ALERT_OBJECTS = 40


def _object_label(entry: dict[str, Any]) -> str:
    """Name the host or service an archive entry is about.

    archivejson.cgi names a host entry's host in `name` and a service entry's
    host in `host_name` (read from the live CGI, 4.5.9).
    """
    if entry.get("object_type") == ARCHIVE_OBJECT_HOST:
        return entry.get("name") or "unknown host"
    host = entry.get("host_name") or "unknown host"
    return f"{host} / {entry.get('description') or 'unknown service'}"


def _archive_params(query: str, host_name: str | None, hours: int) -> dict[str, str]:
    """Validate the range and build the archivejson.cgi query."""
    window = HistoryInput(host_name=host_name, hours=hours)
    params = {"query": query, "starttime": f"-{window.hours * 3600}", "endtime": "+0"}
    if window.host_name:
        params["hostname"] = window.host_name
    return params


async def notification_history(
    host_name: str | None = None,
    hours: int = 24,
) -> str:
    """Retrieve recent notification history."""
    params = _archive_params("notificationlist", host_name, hours)
    archive = await get_client().query_archive(params)
    notifications = archive["data"].get("notificationlist", [])

    if not notifications:
        scope = f" for host '{host_name}'" if host_name else ""
        return f"No notifications in the last {hours} hour(s){scope}."

    lines = [f"Notifications (last {hours}h):"]
    for notif in notifications:
        ts = _format_timestamp(notif.get("timestamp", 0))
        contact = notif.get("contact", "unknown")
        method = notif.get("method", "unknown")
        message = notif.get("message", "")
        lines.append(f"  [{ts}] {_object_label(notif)} → {contact} via {method}: {message}")

    return "\n".join(lines)


def _in_downtime(windows: dict[str, list[tuple[int, int]]], label: str, timestamp: int) -> bool:
    return any(start <= timestamp <= end for start, end in windows.get(label, ()))


def _rollup(
    alerts: list[dict[str, Any]],
    windows: dict[str, list[tuple[int, int]]] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Fold a chronological alert list into one record per host or service.

    Problems raised inside a scheduled downtime window for that object are planned
    work, not noise: they are counted per object in the second return value and
    kept out of the record.
    """
    objects: dict[str, dict[str, Any]] = {}
    planned: dict[str, int] = {}
    for alert in sorted(alerts, key=lambda item: item.get("timestamp", 0)):
        state = alert.get("state", 0)
        record = objects.setdefault(
            _object_label(alert),
            {
                "problems": 0,
                "hard": 0,
                "states": {},
                "first": 0,
                "last": 0,
                "output": "",
                "ended": state,
            },
        )
        record["ended"] = state
        if state in ARCHIVE_RECOVERED_STATES:
            continue
        label = _object_label(alert)
        if windows and _in_downtime(windows, label, alert.get("timestamp", 0)):
            planned[label] = planned.get(label, 0) + 1
            continue
        name = ARCHIVE_STATE_MAP.get(state, f"UNKNOWN({state})")
        record["problems"] += 1
        record["hard"] += alert.get("state_type") == ARCHIVE_STATE_TYPE_HARD
        record["states"][name] = record["states"].get(name, 0) + 1
        record["first"] = record["first"] or alert.get("timestamp", 0)
        record["last"] = alert.get("timestamp", 0)
        record["output"] = alert.get("plugin_output", "")
    return {label: record for label, record in objects.items() if record["problems"]}, planned


async def _windows_by_label(hours: int) -> dict[str, list[tuple[int, int]]] | None:
    since_ms = int(time.time() * 1000) - hours * 3600 * 1000
    windows = await downtime_windows(since_ms)
    if windows is None:
        return None
    by_label: dict[str, list[tuple[int, int]]] = {}
    for window in windows:
        by_label.setdefault(window.label, []).append((window.start, window.end or window.start))
    return by_label


async def alert_history(
    host_name: str | None = None,
    hours: int = 168,
) -> str:
    """Roll up state changes per host and service: what failed, how often, did it recover."""
    params = _archive_params("alertlist", host_name, hours)
    archive = await get_client().query_archive(params)
    windows = await _windows_by_label(hours)
    objects, planned = _rollup(archive["data"].get("alertlist", []), windows)
    planned_line = ""
    if planned:
        planned_line = (
            f"  plus {sum(planned.values())} event(s) on {len(planned)} host(s)/service(s) "
            "during scheduled downtime"
        )

    if not objects:
        scope = f" for host '{host_name}'" if host_name else ""
        empty = f"No problem alerts in the last {hours} hour(s){scope}."
        return f"{empty}\n{planned_line}" if planned_line else empty

    ranked = sorted(objects.items(), key=lambda item: item[1]["problems"], reverse=True)
    lines = [f"Problem alerts (last {hours}h), {len(ranked)} host(s)/service(s), noisiest first:"]
    for label, record in ranked[:MAX_ALERT_OBJECTS]:
        states = ", ".join(f"{count} {name}" for name, count in sorted(record["states"].items()))
        ended = ARCHIVE_STATE_MAP.get(record["ended"], f"UNKNOWN({record['ended']})")
        first, last = _format_timestamp(record["first"]), _format_timestamp(record["last"])
        lines.append(
            f"  {label}: {record['problems']} problem event(s) ({states}; {record['hard']} hard), "
            f"first {first}, last {last}, last seen {ended} | {record['output']}"
        )
    if len(ranked) > MAX_ALERT_OBJECTS:
        lines.append(f"  ... and {len(ranked) - MAX_ALERT_OBJECTS} quieter one(s) not shown")
    if planned_line:
        lines.append(planned_line)
    return "\n".join(lines)
