"""Nagios command tools — acknowledge, comment, schedule check."""

import time

from ..client import get_client

CMD_ACKNOWLEDGE_SERVICE = 34
CMD_ACKNOWLEDGE_HOST = 33
CMD_ADD_SERVICE_COMMENT = 3
CMD_ADD_HOST_COMMENT = 1
CMD_SCHEDULE_FORCED_SERVICE_CHECK = 7
CMD_SCHEDULE_FORCED_HOST_CHECK = 17


async def acknowledge(
    host_name: str,
    comment: str,
    service_description: str | None = None,
    sticky: bool = True,
    notify: bool = True,
) -> str:
    """Acknowledge a host or service problem."""
    client = get_client()

    if service_description:
        form_data = {
            "host": host_name,
            "service": service_description,
            "com_author": "Hermes",
            "com_data": comment,
            "sticky_ack": "on" if sticky else "",
            "send_notification": "on" if notify else "",
        }
        result = await client.submit_command(CMD_ACKNOWLEDGE_SERVICE, form_data)
        return f"Acknowledged service '{service_description}' on '{host_name}': {result}"
    form_data = {
        "host": host_name,
        "com_author": "Hermes",
        "com_data": comment,
        "sticky_ack": "on" if sticky else "",
        "send_notification": "on" if notify else "",
    }
    result = await client.submit_command(CMD_ACKNOWLEDGE_HOST, form_data)
    return f"Acknowledged host '{host_name}': {result}"


async def add_comment(
    host_name: str,
    comment: str,
    service_description: str | None = None,
) -> str:
    """Add a comment to a host or service."""
    client = get_client()

    if service_description:
        form_data = {
            "host": host_name,
            "service": service_description,
            "com_author": "Hermes",
            "com_data": comment,
            "persistent": "on",
        }
        result = await client.submit_command(CMD_ADD_SERVICE_COMMENT, form_data)
        return f"Comment added to service '{service_description}' on '{host_name}': {result}"
    form_data = {
        "host": host_name,
        "com_author": "Hermes",
        "com_data": comment,
        "persistent": "on",
    }
    result = await client.submit_command(CMD_ADD_HOST_COMMENT, form_data)
    return f"Comment added to host '{host_name}': {result}"


async def schedule_check(
    host_name: str,
    service_description: str | None = None,
) -> str:
    """Schedule a forced immediate re-check of a host or service."""
    client = get_client()
    now = time.strftime("%m-%d-%Y %H:%M:%S", time.gmtime())

    if service_description:
        form_data = {
            "host": host_name,
            "service": service_description,
            "start_time": now,
            "force_check": "on",
        }
        result = await client.submit_command(CMD_SCHEDULE_FORCED_SERVICE_CHECK, form_data)
        return f"Forced check scheduled for '{service_description}' on '{host_name}': {result}"
    form_data = {
        "host": host_name,
        "start_time": now,
        "force_check": "on",
    }
    result = await client.submit_command(CMD_SCHEDULE_FORCED_HOST_CHECK, form_data)
    return f"Forced check scheduled for host '{host_name}': {result}"
