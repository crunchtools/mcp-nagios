"""Scheduled downtime: schedule, list, cancel, and the history of past windows."""

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config
from ..client import _format_age, _format_timestamp, get_client
from ..errors import ConfigurationError
from ..models import CancelDowntimeInput, DowntimeInput, HistoryInput, ListDowntimesInput

CMD_SCHEDULE_HOST_DOWNTIME = 55
CMD_SCHEDULE_SVC_DOWNTIME = 56
CMD_DEL_HOST_DOWNTIME = 78
CMD_DEL_SVC_DOWNTIME = 79
CMD_SCHEDULE_HOST_SVC_DOWNTIME = 86

# Every service on a host, not the host's own check: the marker used for
# SCHEDULE_HOST_SVC_DOWNTIME when attributing a window to the command behind it.
ALL_SERVICES = "*"
# host;start;end;fixed;trigger;duration;author;comment
SCHEDULE_FIELDS = 8

_LOG_LINE = re.compile(r"^\[(\d+)\] (.*)$")
_SCHEDULE = re.compile(r"^EXTERNAL COMMAND: (SCHEDULE_(?:HOST|SVC|HOST_SVC)_DOWNTIME);(.*)$")
_HOST_ALERT = re.compile(r"^HOST DOWNTIME ALERT: ([^;]+);(STARTED|STOPPED|CANCELLED);")
_SERVICE_ALERT = re.compile(
    r"^SERVICE DOWNTIME ALERT: ([^;]+);([^;]+);(STARTED|STOPPED|CANCELLED);"
)


def _wall_clock(epoch: float) -> str:
    # cmd.cgi parses times as naive wall-clock in the Nagios server's own zone,
    # the same constraint schedule_check documents.
    return time.strftime("%m-%d-%Y %H:%M:%S", time.localtime(epoch))


async def schedule_downtime(
    host_name: str,
    minutes: int,
    comment: str,
    service_description: str | None = None,
) -> str:
    """Schedule fixed downtime starting now, on one service or on a host and all its services."""
    params = DowntimeInput(
        host_name=host_name,
        service_description=service_description,
        comment=comment,
        minutes=minutes,
    )
    client = get_client()
    now = time.time()
    form_data = {
        "host": params.host_name,
        "com_author": config.get_config().comment_author,
        "com_data": params.comment,
        "trigger": "0",
        "start_time": _wall_clock(now),
        "end_time": _wall_clock(now + params.minutes * 60),
        "fixed": "1",
        "hours": str(params.minutes // 60),
        "minutes": str(params.minutes % 60),
    }
    until = _format_timestamp(int((now + params.minutes * 60) * 1000))

    if params.service_description:
        form_data["service"] = params.service_description
        result = await client.submit_command(CMD_SCHEDULE_SVC_DOWNTIME, form_data)
        return (
            f"Downtime scheduled for '{params.service_description}' on "
            f"'{params.host_name}' until {until}: {result}"
        )
    form_data["childoptions"] = "0"
    result = await client.submit_command(CMD_SCHEDULE_HOST_DOWNTIME, form_data)
    services = await client.submit_command(CMD_SCHEDULE_HOST_SVC_DOWNTIME, form_data)
    return (
        f"Downtime scheduled for host '{params.host_name}' and all its services "
        f"until {until}: {result}; services: {services}"
    )


async def _downtimes(host_name: str | None) -> list[dict[str, Any]]:
    """Current and future downtimes from statusjson.cgi, soonest end first."""
    query = {"query": "downtimelist", "details": "true"}
    if host_name:
        query["hostname"] = host_name
    response = await get_client().query_status(query)
    raw = response["data"].get("downtimelist", {})
    entries = list(raw.values()) if isinstance(raw, dict) else list(raw)
    return sorted(
        (entry for entry in entries if isinstance(entry, dict)),
        key=lambda entry: entry.get("end_time", 0),
    )


def _label(entry: dict[str, Any]) -> str:
    host = entry.get("host_name") or "unknown host"
    service = entry.get("service_description")
    return f"{host} / {service}" if service else host


async def list_downtimes(host_name: str | None = None) -> str:
    """List scheduled downtimes that are active or still to come."""
    params = ListDowntimesInput(host_name=host_name)
    entries = await _downtimes(params.host_name)
    if not entries:
        scope = f" for host '{host_name}'" if host_name else ""
        return f"No scheduled downtime{scope}."

    lines = [f"Scheduled downtime, {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}:"]
    for entry in entries:
        state = "in effect" if entry.get("is_in_effect") else "pending"
        start = _format_timestamp(entry.get("start_time", 0))
        end = _format_timestamp(entry.get("end_time", 0))
        lines.append(
            f"  #{entry.get('downtime_id', '?')} {_label(entry)}: {state}, {start} → {end} | "
            f"{entry.get('author', '')}: {entry.get('comment', '')}"
        )
    return "\n".join(lines)


async def cancel_downtime(host_name: str, service_description: str | None = None) -> str:
    """Cancel this server's downtimes on a host (and its services), or on one service.

    Only downtimes recorded under this server's own comment author are touched,
    so cleaning up after planned work cannot end a window a person opened by
    hand. This is a guard against accidents, not an authorization boundary: the
    Nagios CGI user this server logs in as can already delete any downtime
    through cmd.cgi, so the filter grants nothing that user lacks.
    """
    params = CancelDowntimeInput(host_name=host_name, service_description=service_description)
    author = config.get_config().comment_author
    matches = [
        entry
        for entry in await _downtimes(params.host_name)
        if entry.get("host_name") == params.host_name
        and entry.get("author") == author
        and (
            params.service_description is None
            or entry.get("service_description") == params.service_description
        )
    ]
    if not matches:
        target = params.service_description or params.host_name
        return f"No downtime by '{author}' to cancel on {target}."

    client = get_client()
    for entry in matches:
        cmd = CMD_DEL_SVC_DOWNTIME if entry.get("service_description") else CMD_DEL_HOST_DOWNTIME
        await client.submit_command(cmd, {"down_id": str(entry.get("downtime_id", ""))})
    return f"Cancelled {len(matches)} downtime(s): " + ", ".join(_label(e) for e in matches)


@dataclass
class Window:
    """One object's downtime window, in epoch milliseconds."""

    label: str
    host: str
    service: str | None
    start: int
    end: int | None
    author: str
    comment: str
    ongoing: bool = False
    # The end time the SCHEDULE_*_DOWNTIME command asked for, 0 if unknown. The
    # host and service commands of one scheduling share it, whatever second each
    # was logged in, so it identifies the scheduling.
    scheduled_end: int = 0


ObjectKey = tuple[str, str | None]


def _parse_schedule(text: str) -> tuple[ObjectKey, tuple[str, str, int]] | None:
    """A logged SCHEDULE_*_DOWNTIME command: its object, and (author, comment, end ms)."""
    command = _SCHEDULE.match(text)
    if not command:
        return None
    kind, fields = command.group(1), command.group(2).split(";")
    service: str | None = None
    if kind == "SCHEDULE_SVC_DOWNTIME" and len(fields) > 1:
        service, fields = fields[1], [fields[0], *fields[2:]]
    elif kind == "SCHEDULE_HOST_SVC_DOWNTIME":
        service = ALL_SERVICES
    # host;start;end;fixed;trigger;duration;author;comment -- the comment may hold ';'
    if len(fields) < SCHEDULE_FIELDS:
        return None
    end = int(fields[2]) * 1000 if fields[2].isdigit() else 0
    return (fields[0], service), (fields[6], ";".join(fields[7:]), end)


def _parse_alert(text: str) -> tuple[ObjectKey, str] | None:
    """A HOST or SERVICE DOWNTIME ALERT: its object and STARTED/STOPPED/CANCELLED."""
    if alert := _HOST_ALERT.match(text):
        return (alert.group(1), None), alert.group(2)
    if alert := _SERVICE_ALERT.match(text):
        return (alert.group(1), alert.group(2)), alert.group(3)
    return None


class _WindowBuilder:
    """Pairs downtime STARTED alerts with their STOPPED or CANCELLED, one log line at a time.

    The author and comment come from the most recent SCHEDULE_*_DOWNTIME command
    for that object, which Nagios logs with log_external_commands. Only windows
    that end at or after `since_ms` are kept, so memory follows the range asked
    for rather than the length of the log.
    """

    def __init__(self, since_ms: int) -> None:
        self._since_ms = since_ms
        self._scheduled: dict[ObjectKey, tuple[str, str, int]] = {}
        self._open: dict[ObjectKey, Window] = {}
        self.windows: list[Window] = []

    def feed(self, ts: int, text: str) -> None:
        if command := _parse_schedule(text):
            self._scheduled[command[0]] = command[1]
            return
        alert = _parse_alert(text)
        if not alert:
            return
        key, action = alert
        if action != "STARTED":
            window = self._open.pop(key, None)
            if window and ts >= self._since_ms:
                window.end = ts
                self.windows.append(window)
            return
        # A restart can log STARTED again for a window already open; keep the first.
        if key in self._open:
            return
        author, comment, planned_end = (
            self._scheduled.get(key) or self._scheduled.get((key[0], ALL_SERVICES)) or ("", "", 0)
        )
        self._open[key] = Window(
            label=f"{key[0]} / {key[1]}" if key[1] else key[0],
            host=key[0],
            service=key[1],
            start=ts,
            end=planned_end or None,
            author=author,
            comment=comment,
            scheduled_end=planned_end,
        )

    def finish(self, now_ms: int) -> list[Window]:
        """Close out the windows the log never stopped.

        One whose scheduled end has passed ended then: Nagios restarted inside it
        and never logged the STOPPED. Otherwise it is ongoing, ending at its
        scheduled end, or now if that is unknown.
        """
        for window in self._open.values():
            window.ongoing = not window.end or window.end > now_ms
            window.end = window.end or now_ms
            if window.end >= self._since_ms:
                self.windows.append(window)
        self._open = {}
        return self.windows


def _read_windows(log_path: str, now_ms: int, since_ms: int = 0) -> list[Window]:
    """Rebuild downtime windows from nagios.log, streaming it line by line."""
    builder = _WindowBuilder(since_ms)
    try:
        with Path(log_path).open(encoding="utf-8", errors="replace") as log:
            for raw in log:
                line = _LOG_LINE.match(raw.rstrip("\n")) if "DOWNTIME" in raw else None
                if line:
                    builder.feed(int(line.group(1)) * 1000, line.group(2))
    except OSError as exc:
        raise ConfigurationError(f"NAGIOS_LOG_PATH {log_path!r} is unreadable: {exc}") from exc
    return builder.finish(now_ms)


async def downtime_windows(since_ms: int) -> list[Window] | None:
    """Windows that overlap the range, or None when no log path is configured.

    The scan runs in a worker thread so a large log never blocks the event loop.
    """
    log_path = config.get_config().log_path
    if not log_path:
        return None
    now_ms = int(time.time() * 1000)
    return await asyncio.to_thread(_read_windows, log_path, now_ms, since_ms)


async def downtime_history(host_name: str | None = None, hours: int = 168) -> str:
    """Past and current downtime windows, one line per scheduling with its objects."""
    window_range = HistoryInput(host_name=host_name, hours=hours)
    since_ms = int(time.time() * 1000) - window_range.hours * 3600 * 1000
    windows = await downtime_windows(since_ms)
    if windows is None:
        raise ConfigurationError("NAGIOS_LOG_PATH is not set; downtime history needs nagios.log.")
    if window_range.host_name:
        windows = [w for w in windows if w.host == window_range.host_name]
    if not windows:
        scope = f" for host '{host_name}'" if host_name else ""
        return f"No scheduled downtime in the last {hours} hour(s){scope}."

    # One scheduling covers a host and each of its services; group them back
    # together by host, author, comment and the end the commands asked for. A
    # window with no logged command falls back to its own start.
    groups: dict[tuple[str, str, str, int], list[Window]] = {}
    for window in sorted(windows, key=lambda w: w.start):
        scheduling = window.scheduled_end or window.start
        groups.setdefault((window.host, window.author, window.comment, scheduling), []).append(
            window
        )

    lines = [f"Downtime windows (last {hours}h), {len(groups)} scheduling(s):"]
    for (host, author, comment, _scheduling), members in groups.items():
        start = min(w.start for w in members)
        end = max(w.end or start for w in members)
        ordered = sorted(members, key=lambda w: (w.service is not None, w.service or ""))
        objects = "; ".join("host" if w.service is None else w.service for w in ordered)
        ongoing = ", ongoing" if any(w.ongoing for w in members) else ""
        lines.append(
            f"  {host} [{objects}]: {_format_timestamp(start)} → {_format_timestamp(end)} "
            f"({_format_age(end - start)}{ongoing}) | {author or 'unknown'}: {comment}"
        )
    return "\n".join(lines)
