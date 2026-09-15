"""Nagios status query tools."""

from typing import Any

from ..client import (
    HOST_NON_PROBLEM_STATES,
    SERVICE_NON_PROBLEM_STATES,
    STATE_TYPE_MAP,
    STATUS_MAP_HOST,
    STATUS_MAP_SERVICE,
    _format_timestamp,
    get_client,
)

# Nagios rewrites its status data every status_update_interval seconds
# (default 10). 60s is a 6x margin: loose enough not to trip on one slow write
# under load, tight enough that a wedged daemon is caught within a single
# 5-minute poll cycle.
DEFAULT_MAX_STALENESS_SECONDS = 60


async def host_status(host_name: str) -> str:
    """Query the status of a specific host."""
    client = get_client()
    data = await client.query_status({"query": "host", "hostname": host_name})
    host = data["data"]["host"]

    status_code = host.get("status", 0)
    status_text = STATUS_MAP_HOST.get(status_code, f"UNKNOWN({status_code})")
    state_type = STATE_TYPE_MAP.get(host.get("state_type", 0), "UNKNOWN")

    lines = [
        f"Host: {host['name']}",
        f"Status: {status_text} ({state_type})",
        f"Output: {host.get('plugin_output', '')}",
        f"Last Check: {_format_timestamp(host.get('last_check', 0))}",
        f"Next Check: {_format_timestamp(host.get('next_check', 0))}",
        f"Attempt: {host.get('current_attempt', 0)}/{host.get('max_attempts', 0)}",
        f"Last State Change: {_format_timestamp(host.get('last_state_change', 0))}",
    ]
    return "\n".join(lines)


async def service_status(host_name: str, service_description: str) -> str:
    """Query the status of a specific service on a host."""
    client = get_client()
    data = await client.query_status({
        "query": "service",
        "hostname": host_name,
        "servicedescription": service_description,
    })
    svc = data["data"]["service"]

    status_code = svc.get("status", 0)
    status_text = STATUS_MAP_SERVICE.get(status_code, f"UNKNOWN({status_code})")
    state_type = STATE_TYPE_MAP.get(svc.get("state_type", 0), "UNKNOWN")

    lines = [
        f"Host: {svc.get('host_name', host_name)}",
        f"Service: {svc.get('description', service_description)}",
        f"Status: {status_text} ({state_type})",
        f"Output: {svc.get('plugin_output', '')}",
        f"Last Check: {_format_timestamp(svc.get('last_check', 0))}",
        f"Attempt: {svc.get('current_attempt', 0)}/{svc.get('max_attempts', 0)}",
        f"Last State Change: {_format_timestamp(svc.get('last_state_change', 0))}",
        f"Acknowledged: {svc.get('problem_has_been_acknowledged', False)}",
    ]
    return "\n".join(lines)


async def current_problems() -> str:
    """List all hosts and services currently in a non-OK state."""
    client = get_client()

    host_data = await client.query_status({"query": "hostlist"})
    hosts = host_data["data"].get("hostlist", {})
    down_hosts = [
        (name, STATUS_MAP_HOST.get(code, f"UNKNOWN({code})"))
        for name, code in hosts.items()
        if code not in HOST_NON_PROBLEM_STATES
    ]

    svc_data = await client.query_status({"query": "servicelist"})
    services = svc_data["data"].get("servicelist", {})
    problem_services = []
    for hostname, svcs in services.items():
        for svc_name, code in svcs.items():
            if code not in SERVICE_NON_PROBLEM_STATES:
                status_text = STATUS_MAP_SERVICE.get(code, f"UNKNOWN({code})")
                problem_services.append((hostname, svc_name, status_text))

    if not down_hosts and not problem_services:
        return "No current problems. All hosts UP, all services OK."

    lines = []
    if down_hosts:
        lines.append("=== Host Problems ===")
        for name, status in down_hosts:
            lines.append(f"  {name}: {status}")

    if problem_services:
        lines.append("=== Service Problems ===")
        for hostname, svc_name, status in problem_services:
            lines.append(f"  {hostname} / {svc_name}: {status}")

    lines.append(f"\nTotal: {len(down_hosts)} host(s), {len(problem_services)} service(s)")
    return "\n".join(lines)


def _enabled(prog: dict[str, Any], flag: str) -> bool:
    """Read a Nagios on/off flag, treating a missing key as 'on'.

    Absent keys must not raise an alarm. A health check that cries wolf over a
    field Nagios simply did not emit gets ignored, and an ignored health check
    is worse than none. Every flag read here is present in 4.5.9; if a future
    version drops one, the correct failure mode is silence, not noise.
    """
    return prog.get(flag, True) is not False


async def program_status(max_staleness_seconds: int = DEFAULT_MAX_STALENESS_SECONDS) -> str:
    """Report whether the Nagios daemon itself is alive and actually working.

    This is a supply-chain check on the monitoring system, deliberately separate
    from the state of the things it monitors. It answers "can I still trust
    Nagios to tell me about outages?" -- not "are there outages?".

    It catches three silent failures that querying for problems cannot. A wedged
    daemon still serves the CGI over HTTP 200 while its data goes stale. A
    global notification disable leaves Nagios checking everything and telling
    nobody. A check-execution disable leaves it notifying on state it has
    stopped refreshing. In all three cases "no problems reported" is a lie, and
    a caller polling for problems reads that lie as good news.

    Connection failures and non-200 responses raise rather than return, so a
    dead Nagios surfaces as an error and can never be mistaken for healthy.
    """
    client = get_client()
    data = await client.query_status({"query": "programstatus"})
    prog = data["data"]["programstatus"]
    result = data.get("result", {})

    # Both timestamps come from Nagios itself, so staleness is immune to clock
    # skew between this container and the Nagios server -- the same class of bug
    # that made forced checks fire four hours late (fixed in 0.1.2).
    query_time_ms = result.get("query_time", 0)
    last_update_ms = result.get("last_data_update", 0)
    measurable = bool(query_time_ms) and bool(last_update_ms)
    staleness = (query_time_ms - last_update_ms) / 1000 if measurable else -1.0

    problems = []
    if not measurable:
        problems.append("Nagios returned no status-data timestamp; freshness cannot be verified")
    elif staleness > max_staleness_seconds:
        problems.append(
            f"Status data is {staleness:.0f}s stale (threshold {max_staleness_seconds}s) -- "
            "the CGI is answering but the daemon may be wedged"
        )
    if not _enabled(prog, "enable_notifications"):
        problems.append(
            "Notifications are globally DISABLED -- Nagios is monitoring but alerting nobody"
        )
    if not _enabled(prog, "execute_host_checks"):
        problems.append(
            "Active host checks are DISABLED -- host state is no longer being refreshed"
        )
    if not _enabled(prog, "execute_service_checks"):
        problems.append(
            "Active service checks are DISABLED -- service state is no longer being refreshed"
        )

    # First line is a stable, greppable verdict: callers that run without an
    # agent (the Kagetora watchdog) match on it rather than parsing the body.
    lines = [f"NAGIOS HEALTH: {'OK' if not problems else 'DEGRADED'}"]
    if problems:
        lines.append("Problems:")
        lines.extend(f"  - {p}" for p in problems)

    freshness = f"{staleness:.0f}s" if measurable else "unknown"
    version = prog.get("version", "unknown")
    pid = prog.get("nagios_pid", "?")
    daemon = prog.get("daemon_mode", "?")
    active_host = prog.get("execute_host_checks", "unknown")
    active_svc = prog.get("execute_service_checks", "unknown")
    passive_host = prog.get("accept_passive_host_checks", "unknown")
    passive_svc = prog.get("accept_passive_service_checks", "unknown")
    lines.extend([
        f"Version: {version} (pid {pid}, daemon_mode={daemon})",
        f"Status Data Age: {freshness} (threshold {max_staleness_seconds}s)",
        f"Program Start: {_format_timestamp(prog.get('program_start', 0))}",
        f"Notifications Enabled: {prog.get('enable_notifications', 'unknown')}",
        f"Active Checks: host={active_host} service={active_svc}",
        f"Passive Checks: host={passive_host} service={passive_svc}",
        f"Event Handlers Enabled: {prog.get('enable_event_handlers', 'unknown')}",
        f"Flap Detection Enabled: {prog.get('enable_flap_detection', 'unknown')}",
    ])
    return "\n".join(lines)
