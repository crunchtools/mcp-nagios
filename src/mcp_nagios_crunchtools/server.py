"""FastMCP server for Nagios Core monitoring."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from .client import close_client
from .tools import (
    acknowledge,
    add_comment,
    current_problems,
    host_status,
    notification_history,
    schedule_check,
    service_status,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_mcp: FastMCP) -> AsyncIterator[None]:
    logger.info("Starting Nagios MCP server")
    yield
    await close_client()
    logger.info("Nagios MCP server stopped")


mcp = FastMCP(
    name="mcp-nagios-crunchtools",
    version="0.1.0",
    lifespan=lifespan,
    instructions=(
        "MCP server for Nagios Core monitoring. Query host and service status, "
        "acknowledge problems, add comments, schedule forced checks, and "
        "read notification history."
    ),
)


@mcp.tool()
async def nagios_host_status_tool(host_name: str) -> str:
    """Get the current status of a Nagios host.

    Args:
        host_name: The Nagios hostname to query.

    Returns:
        Host status details including state, output, and check timing.
    """
    return await host_status(host_name)


@mcp.tool()
async def nagios_service_status_tool(host_name: str, service_description: str) -> str:
    """Get the current status of a specific service on a host.

    Args:
        host_name: The Nagios hostname.
        service_description: The service description (e.g., 'HTTPS crunchtools.com').

    Returns:
        Service status details including state, output, and acknowledgement status.
    """
    return await service_status(host_name, service_description)


@mcp.tool()
async def nagios_current_problems_tool() -> str:
    """List all hosts and services currently in a non-OK state.

    Returns:
        Summary of all current problems, or confirmation that everything is OK.
    """
    return await current_problems()


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
async def nagios_notification_history_tool(
    host_name: str | None = None,
    hours: int = 24,
) -> str:
    """Retrieve recent notification history from Nagios.

    Args:
        host_name: Filter to a specific host. Omit for all hosts.
        hours: How many hours of history to retrieve. Default 24.

    Returns:
        List of recent notifications with timestamps, contacts, and messages.
    """
    return await notification_history(host_name, hours)
