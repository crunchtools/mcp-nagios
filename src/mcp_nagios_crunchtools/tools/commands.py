"""Nagios command tools — acknowledge, comment, schedule check."""

import time

from ..client import get_client
from ..models import AcknowledgeInput, CommentInput, ScheduleCheckInput

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
    params = AcknowledgeInput(
        host_name=host_name,
        comment=comment,
        service_description=service_description,
        sticky=sticky,
        notify=notify,
    )
    client = get_client()

    if params.service_description:
        form_data = {
            "host": params.host_name,
            "service": params.service_description,
            "com_author": "Hermes",
            "com_data": params.comment,
            "sticky_ack": "on" if params.sticky else "",
            "send_notification": "on" if params.notify else "",
        }
        result = await client.submit_command(CMD_ACKNOWLEDGE_SERVICE, form_data)
        return (
            f"Acknowledged service '{params.service_description}' "
            f"on '{params.host_name}': {result}"
        )
    form_data = {
        "host": params.host_name,
        "com_author": "Hermes",
        "com_data": params.comment,
        "sticky_ack": "on" if params.sticky else "",
        "send_notification": "on" if params.notify else "",
    }
    result = await client.submit_command(CMD_ACKNOWLEDGE_HOST, form_data)
    return f"Acknowledged host '{params.host_name}': {result}"


async def add_comment(
    host_name: str,
    comment: str,
    service_description: str | None = None,
) -> str:
    """Add a comment to a host or service."""
    params = CommentInput(
        host_name=host_name,
        comment=comment,
        service_description=service_description,
    )
    client = get_client()

    if params.service_description:
        form_data = {
            "host": params.host_name,
            "service": params.service_description,
            "com_author": "Hermes",
            "com_data": params.comment,
            "persistent": "on",
        }
        result = await client.submit_command(CMD_ADD_SERVICE_COMMENT, form_data)
        return (
            f"Comment added to service '{params.service_description}' "
            f"on '{params.host_name}': {result}"
        )
    form_data = {
        "host": params.host_name,
        "com_author": "Hermes",
        "com_data": params.comment,
        "persistent": "on",
    }
    result = await client.submit_command(CMD_ADD_HOST_COMMENT, form_data)
    return f"Comment added to host '{params.host_name}': {result}"


async def schedule_check(
    host_name: str,
    service_description: str | None = None,
) -> str:
    """Schedule a forced immediate re-check of a host or service."""
    params = ScheduleCheckInput(
        host_name=host_name,
        service_description=service_description,
    )
    client = get_client()
    # cmd.cgi parses start_time as naive wall-clock in the Nagios server's own
    # local timezone -- there is no offset field to send. gmtime() therefore
    # scheduled every forced check UTC-offset hours into the future (4h against
    # an EDT server), so "check now" silently did nothing. This container must
    # run in the same timezone as the Nagios server for localtime() to match.
    now = time.strftime("%m-%d-%Y %H:%M:%S", time.localtime())

    if params.service_description:
        form_data = {
            "host": params.host_name,
            "service": params.service_description,
            "start_time": now,
            "force_check": "on",
        }
        result = await client.submit_command(CMD_SCHEDULE_FORCED_SERVICE_CHECK, form_data)
        return (
            f"Forced check scheduled for '{params.service_description}' "
            f"on '{params.host_name}': {result}"
        )
    form_data = {
        "host": params.host_name,
        "start_time": now,
        "force_check": "on",
    }
    result = await client.submit_command(CMD_SCHEDULE_FORCED_HOST_CHECK, form_data)
    return f"Forced check scheduled for host '{params.host_name}': {result}"
