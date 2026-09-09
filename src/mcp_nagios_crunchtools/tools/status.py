"""Nagios status query tools."""

from ..client import (
    HOST_NON_PROBLEM_STATES,
    SERVICE_NON_PROBLEM_STATES,
    STATE_TYPE_MAP,
    STATUS_MAP_HOST,
    STATUS_MAP_SERVICE,
    _format_timestamp,
    get_client,
)


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
