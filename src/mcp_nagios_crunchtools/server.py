"""FastMCP server for Nagios Core monitoring."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from . import __version__
from .client import close_client
from .models import (
    MAX_DOWNTIME_MINUTES,
    MAX_HISTORY_HOURS,
    MAX_HOSTNAME_LENGTH,
    MAX_SERVICE_DESC_LENGTH,
    MIN_DOWNTIME_MINUTES,
)
from .tools import (
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

logger = logging.getLogger(__name__)

# Published in each read tool's JSON schema so a client sees the bounds up front.
HostName = Annotated[str, Field(min_length=1, max_length=MAX_HOSTNAME_LENGTH)]
OptionalHostName = Annotated[str | None, Field(min_length=1, max_length=MAX_HOSTNAME_LENGTH)]
ServiceDescription = Annotated[str, Field(min_length=1, max_length=MAX_SERVICE_DESC_LENGTH)]
Hours = Annotated[int, Field(ge=1, le=MAX_HISTORY_HOURS)]
Minutes = Annotated[int, Field(ge=MIN_DOWNTIME_MINUTES, le=MAX_DOWNTIME_MINUTES)]

# A gateway drops an invalid optional argument only on a tool annotated read-only;
# on anything else it refuses the call. Only tools that change nothing in Nagios
# get this: the three that submit an external command through cmd.cgi do not.
READ_ONLY = {"readOnlyHint": True}


@asynccontextmanager
async def lifespan(_mcp: FastMCP) -> AsyncIterator[None]:
    logger.info("Starting Nagios MCP server")
    yield
    await close_client()
    logger.info("Nagios MCP server stopped")


mcp = FastMCP(
    name="mcp-nagios-crunchtools",
    # Sourced from __version__ rather than hardcoded: this literal silently
    # drifted to 0.1.0 while the package moved on to 0.1.2.
    version=__version__,
    lifespan=lifespan,
    instructions=(
        "MCP server for Nagios Core monitoring. Query host and service status, "
        "acknowledge problems, add comments, schedule forced checks, and "
        "read notification and alert history. Before planned work that will make "
        "checks fail (a deploy, a restart, a long work session), schedule downtime "
        "with nagios_schedule_downtime_tool and cancel it when done, so the work "
        "neither pages nor counts as noise. Notifications only fire on what "
        "Nagios is configured to page for; nagios_alert_history_tool shows every "
        "state change, including warnings and problems that recovered by "
        "themselves. To check whether Nagios ITSELF is alive and "
        "functioning -- as opposed to what it is reporting about other hosts -- "
        "use nagios_program_status_tool, not nagios_current_problems_tool."
    ),
)


@mcp.tool(annotations=READ_ONLY)
async def nagios_host_status_tool(host_name: HostName) -> str:
    """Get the current status of a Nagios host.

    Args:
        host_name: The Nagios hostname to query.

    Returns:
        Host status details including state, output, and check timing.
    """
    return await host_status(host_name)


@mcp.tool(annotations=READ_ONLY)
async def nagios_service_status_tool(
    host_name: HostName, service_description: ServiceDescription
) -> str:
    """Get the current status of a specific service on a host.

    Args:
        host_name: The Nagios hostname.
        service_description: The service description (e.g., 'HTTPS crunchtools.com').

    Returns:
        Service status details including state, output, and acknowledgement status.
    """
    return await service_status(host_name, service_description)


@mcp.tool(annotations=READ_ONLY)
async def nagios_current_problems_tool() -> str:
    """List all hosts and services currently in a non-OK state.

    Returns:
        One line per problem with its state, how long it has been in that state,
        attempt count, acknowledgement and plugin output, or confirmation that
        everything is OK.
    """
    return await current_problems()


@mcp.tool(annotations=READ_ONLY)
async def nagios_program_status_tool(
    max_staleness_seconds: Annotated[int, Field(ge=1)] = 60,
) -> str:
    """Check whether the Nagios daemon itself is alive and actually working.

    Use this to verify the monitoring system, NOT to find outages. It is the
    right tool for a watchdog asking "is Nagios still able to tell me about
    problems?" -- nagios_current_problems_tool answers a different question and
    returns "no problems" both when all is well and when Nagios has silently
    stopped working.

    Detects a wedged daemon (CGI still returns 200 but status data is stale),
    globally disabled notifications (monitoring everything, alerting nobody),
    and disabled check execution. Raises on connection failure, so a dead
    Nagios can never be read as healthy.

    Args:
        max_staleness_seconds: How old Nagios's status data may be before the
            daemon is considered wedged. Default 60 (it refreshes every ~10s).

    Returns:
        'NAGIOS HEALTH: OK' or 'NAGIOS HEALTH: DEGRADED' on the first line,
        followed by any problems found and the daemon's operating flags.
    """
    return await program_status(max_staleness_seconds)


@mcp.tool()
async def nagios_acknowledge_tool(
    host_name: str,
    comment: str,
    service_description: str | None = None,
    sticky: bool = True,
    notify: bool = True,
) -> str:
    """Acknowledge a host or service problem in Nagios.

    Args:
        host_name: The hostname with the problem.
        comment: Acknowledgement comment (e.g., 'Hermes is investigating').
        service_description: Service name. Omit for host acknowledgement.
        sticky: Keep acknowledged even if state changes. Default True.
        notify: Send notification about the acknowledgement. Default True.

    Returns:
        Confirmation that the problem was acknowledged.
    """
    return await acknowledge(host_name, comment, service_description, sticky, notify)


@mcp.tool()
async def nagios_add_comment_tool(
    host_name: str,
    comment: str,
    service_description: str | None = None,
) -> str:
    """Add a persistent comment to a host or service in Nagios.

    Args:
        host_name: The hostname.
        comment: Comment text (e.g., 'Restarting service to resolve issue').
        service_description: Service name. Omit for host comment.

    Returns:
        Confirmation that the comment was added.
    """
    return await add_comment(host_name, comment, service_description)


@mcp.tool()
async def nagios_schedule_check_tool(
    host_name: str,
    service_description: str | None = None,
) -> str:
    """Schedule a forced immediate re-check of a host or service.

    Args:
        host_name: The hostname to check.
        service_description: Service name. Omit for host check.

    Returns:
        Confirmation that the check was scheduled.
    """
    return await schedule_check(host_name, service_description)


@mcp.tool()
async def nagios_schedule_downtime_tool(
    host_name: str,
    minutes: Minutes,
    comment: str,
    service_description: str | None = None,
) -> str:
    """Schedule fixed downtime starting now, before planned work makes checks fail.

    Notifications stop for the window, and alert history counts problems inside
    it as planned work rather than noise. Cancel it with
    nagios_cancel_downtime_tool when the work is done.

    Args:
        host_name: The host. Without service_description, the host and every
            service on it go into downtime.
        minutes: Length of the window, 5 to 480. It expires on its own.
        comment: What the work is and why, e.g. 'Josui: deploying mcp-trove 1.0.7 (RT #1550)'.
        service_description: One service to put into downtime instead of the whole host.

    Returns:
        Confirmation with the window's end time.
    """
    return await schedule_downtime(host_name, minutes, comment, service_description)


@mcp.tool(annotations=READ_ONLY)
async def nagios_list_downtimes_tool(host_name: OptionalHostName = None) -> str:
    """List scheduled downtime that is in effect or still to come.

    Args:
        host_name: Filter to a specific host. Omit for all hosts.

    Returns:
        One line per downtime: id, host or service, in effect or pending,
        start and end, author and comment.
    """
    return await list_downtimes(host_name)


@mcp.tool()
async def nagios_cancel_downtime_tool(
    host_name: str,
    service_description: str | None = None,
) -> str:
    """End downtime this server scheduled, once the planned work is done.

    Only downtime recorded under this server's own author is cancelled.

    Args:
        host_name: The host. Without service_description, its host and service
            downtimes are all cancelled.
        service_description: Cancel only this service's downtime.

    Returns:
        What was cancelled, or that there was nothing to cancel.
    """
    return await cancel_downtime(host_name, service_description)


@mcp.tool(annotations=READ_ONLY)
async def nagios_downtime_history_tool(
    host_name: OptionalHostName = None,
    hours: Hours = 168,
) -> str:
    """List past and current downtime windows, read from nagios.log.

    Args:
        host_name: Filter to a specific host. Omit for all hosts.
        hours: How many hours back to look, 1 to 744. Default 168 (one week).

    Returns:
        One line per scheduling: host, the objects it covered, start, end,
        length, author and comment.
    """
    return await downtime_history(host_name, hours)


@mcp.tool(annotations=READ_ONLY)
async def nagios_notification_history_tool(
    host_name: OptionalHostName = None,
    hours: Hours = 24,
) -> str:
    """Retrieve recent notification history from Nagios.

    Args:
        host_name: Filter to a specific host. Omit for all hosts.
        hours: How many hours of history to retrieve, 1 to 744. Default 24.

    Returns:
        List of recent notifications with timestamps, contacts, and messages.
    """
    return await notification_history(host_name, hours)


@mcp.tool(annotations=READ_ONLY)
async def nagios_alert_history_tool(
    host_name: OptionalHostName = None,
    hours: Hours = 168,
) -> str:
    """Roll up Nagios state changes per host and service over a period.

    Unlike notification history, this includes warnings, soft states and
    problems that recovered without paging anyone, so it is where flapping shows.

    Args:
        host_name: Filter to a specific host. Omit for all hosts.
        hours: How many hours of history to roll up, 1 to 744. Default 168 (one week).

    Returns:
        One line per host or service that had a problem: how many times, in
        which states, first and last time, the last state seen, and the last
        problem output. Noisiest first. Problems inside a scheduled downtime
        window are left out of those lines and totalled on a final "plus N
        event(s) ... during scheduled downtime" line.
    """
    return await alert_history(host_name, hours)
