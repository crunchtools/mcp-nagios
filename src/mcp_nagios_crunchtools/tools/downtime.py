"""Scheduled downtime: schedule, list, cancel, and the history of past windows."""

import asyncio
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import config
from ..client import HTTP_INTERNAL_ERROR, _format_age, _format_timestamp, get_client
from ..errors import (
    ConfigurationError,
    NagiosApiError,
    NagiosCgiCrashError,
    NagiosQueryError,
)
from ..models import CancelDowntimeInput, DowntimeInput, HistoryInput, ListDowntimesInput

CMD_SCHEDULE_HOST_DOWNTIME = 55
CMD_SCHEDULE_SVC_DOWNTIME = 56
CMD_DEL_HOST_DOWNTIME = 78
CMD_DEL_SVC_DOWNTIME = 79
CMD_SCHEDULE_HOST_SVC_DOWNTIME = 86

# statusjson.cgi's result code for an id it does not hold. The CGI calls it
# "Option Value Invalid"; for an id this module read out of Nagios moments
# earlier it means the window ended in between.
QUERY_UNKNOWN_ID = 6
# One statusjson.cgi request is one CGI process reading the whole status file,
# so the per-id reads run a few at a time rather than one per entry at once.
DETAIL_FETCH_LIMIT = 4

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


@dataclass
class Listing:
    """The scheduled downtime statusjson.cgi was able to describe.

    `unreadable` holds the ids of entries Nagios crashed on rather than
    rendered, so a caller can say what it could not see instead of implying
    the downtime is not there. See `_one_by_one` and mcp-nagios#65.
    """

    entries: list[dict[str, Any]] = field(default_factory=list)
    unreadable: list[int] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.entries or self.unreadable)

    @property
    def total(self) -> int:
        return len(self.entries) + len(self.unreadable)


@dataclass(frozen=True)
class _Detail:
    """What asking for one downtime id returned.

    `entry` is None both when Nagios crashed rendering the entry, which sets
    `unreadable`, and when the window ended between the id list and this
    fetch, which the CGI answers as a query error rather than a crash and
    which is not a failure worth reporting.
    """

    entry: dict[str, Any] | None
    unreadable: bool = False


def _by_end_time(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=lambda entry: entry.get("end_time", 0))


def _scoped(query: dict[str, str], host_name: str | None) -> dict[str, str]:
    """Add the host selector, if there is one.

    Only the host is ever selected on, never the service: cancelling a host's
    downtime has to find the host's own window alongside its services'.
    """
    if host_name:
        query["hostname"] = host_name
    return query


async def _downtimes(host_name: str | None) -> Listing:
    """Current and future downtimes from statusjson.cgi, soonest end first.

    One request carries the whole list. When Nagios crashes rendering it the
    list is read again entry by entry, so an entry it cannot render costs that
    entry rather than every tool that reads downtime.
    """
    query = _scoped({"query": "downtimelist", "details": "true"}, host_name)
    try:
        response = await get_client().query_status(query)
    except NagiosApiError as error:
        if error.code != HTTP_INTERNAL_ERROR:
            raise
        return await _one_by_one(host_name)
    raw = response["data"].get("downtimelist", {})
    entries = list(raw.values()) if isinstance(raw, dict) else list(raw)
    return Listing(_by_end_time(entry for entry in entries if isinstance(entry, dict)))


async def _one_by_one(host_name: str | None) -> Listing:
    """Read the downtime list an entry at a time, skipping what Nagios cannot render.

    `details=false` renders none of the stored strings, so the list of ids
    survives the crash in mcp-nagios#65; each id is then asked for on its own
    and only the entries holding the offending comment are lost.
    """
    ids = await _downtime_ids(host_name)
    limit = asyncio.Semaphore(DETAIL_FETCH_LIMIT)

    async def _detail(entry_id: int) -> _Detail:
        async with limit:
            return await _downtime_detail(entry_id)

    details = await asyncio.gather(*(_detail(entry_id) for entry_id in ids))
    return Listing(
        _by_end_time(detail.entry for detail in details if detail.entry is not None),
        [entry_id for entry_id, detail in zip(ids, details, strict=True) if detail.unreadable],
    )


async def _downtime_ids(host_name: str | None) -> list[int]:
    """Every scheduled downtime's id, from the one query that cannot crash."""
    query = _scoped({"query": "downtimelist", "details": "false"}, host_name)
    try:
        response = await get_client().query_status(query)
    except NagiosApiError as error:
        if error.code == HTTP_INTERNAL_ERROR:
            raise NagiosCgiCrashError("downtimelist") from error
        raise
    raw = response["data"].get("downtimelist") or []
    if not isinstance(raw, list):
        raise NagiosQueryError(f"downtimelist without details answered {type(raw).__name__}")
    try:
        return [int(entry_id) for entry_id in raw]
    except (TypeError, ValueError) as error:
        raise NagiosQueryError(f"downtimelist holds an id that is not a number: {error}") from error


async def _downtime_detail(downtime_id: int) -> _Detail:
    """One downtime's fields, or why they could not be read."""
    query = {"query": "downtime", "downtimeid": str(downtime_id)}
    try:
        response = await get_client().query_status(query)
    except NagiosApiError as error:
        if error.code != HTTP_INTERNAL_ERROR:
            raise
        return _Detail(None, unreadable=True)
    except NagiosQueryError as error:
        if error.code != QUERY_UNKNOWN_ID:
            raise
        # The window ended between the id list and this fetch, so the CGI no
        # longer holds the id. It is not scheduled any more; nothing is wrong.
        return _Detail(None)
    entry = response["data"].get("downtime")
    return _Detail(entry if isinstance(entry, dict) else None)


def _unreadable_note(ids: list[int]) -> str:
    """One line naming the entries Nagios could not render, and what to do instead."""
    listed = ", ".join(f"#{entry_id}" for entry_id in ids)
    subject = "entry" if len(ids) == 1 else "entries"
    return (
        f"  {len(ids)} {subject} Nagios could not render ({listed}): the stored comment holds "
        "a character outside ASCII, which crashes statusjson.cgi (mcp-nagios#65). "
        "nagios_downtime_history reads nagios.log and still shows them."
    )


def _label(entry: dict[str, Any]) -> str:
    host = entry.get("host_name") or "unknown host"
    service = entry.get("service_description")
    return f"{host} / {service}" if service else host


async def list_downtimes(host_name: str | None = None) -> str:
    """List scheduled downtimes that are active or still to come."""
    params = ListDowntimesInput(host_name=host_name)
    listing = await _downtimes(params.host_name)
    if not listing:
        scope = f" for host '{host_name}'" if host_name else ""
        return f"No scheduled downtime{scope}."

    total = listing.total
    lines = [f"Scheduled downtime, {total} entr{'y' if total == 1 else 'ies'}:"]
    for entry in listing.entries:
        state = "in effect" if entry.get("is_in_effect") else "pending"
        start = _format_timestamp(entry.get("start_time", 0))
        end = _format_timestamp(entry.get("end_time", 0))
        lines.append(
            f"  #{entry.get('downtime_id', '?')} {_label(entry)}: {state}, {start} → {end} | "
            f"{entry.get('author', '')}: {entry.get('comment', '')}"
        )
    if listing.unreadable:
        lines.append(_unreadable_note(listing.unreadable))
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
    listing = await _downtimes(params.host_name)
    matches = [
        entry
        for entry in listing.entries
        if entry.get("host_name") == params.host_name
        and entry.get("author") == author
        and (
            params.service_description is None
            or entry.get("service_description") == params.service_description
        )
    ]
    # An entry Nagios cannot render cannot be checked against the author, and
    # the author filter is the whole reason this tool is safe to point at a
    # host. In steady state every window this server opens has an ASCII
    # comment, so an unrenderable one was opened by a person -- exactly the
    # window the filter exists to leave alone. Name it and leave it.
    # The ids are only known to be on this host: an entry Nagios will not
    # render names neither its service nor its author, so whether it is even
    # the window asked for is unknown. Say that rather than claim a match.
    blocked = (
        f" Left {len(listing.unreadable)} alone on '{params.host_name}' "
        f"({', '.join(f'#{i}' for i in listing.unreadable)}): Nagios cannot render "
        "the entry, so neither its service nor its author can be checked. "
        "nagios_downtime_history names who opened it, and the Nagios web UI can end it."
        if listing.unreadable
        else ""
    )
    if not matches:
        target = params.service_description or params.host_name
        return f"No downtime by '{author}' to cancel on {target}.{blocked}"

    client = get_client()
    for entry in matches:
        cmd = CMD_DEL_SVC_DOWNTIME if entry.get("service_description") else CMD_DEL_HOST_DOWNTIME
        await client.submit_command(cmd, {"down_id": str(entry.get("downtime_id", ""))})
    return (
        f"Cancelled {len(matches)} downtime(s): " + ", ".join(_label(e) for e in matches) + blocked
    )


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
