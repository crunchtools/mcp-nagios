"""Nagios notification history tools."""

from ..client import _format_timestamp, get_client


async def notification_history(
    host_name: str | None = None,
    hours: int = 24,
) -> str:
    """Retrieve recent notification history."""
    client = get_client()

    params: dict[str, str] = {
        "query": "notificationlist",
        "starttime": f"-{hours * 3600}",
        "endtime": "+0",
    }
    if host_name:
        params["hostname"] = host_name

    data = await client.query_archive(params)
    notifications = data["data"].get("notificationlist", [])

    if not notifications:
        scope = f" for host '{host_name}'" if host_name else ""
        return f"No notifications in the last {hours} hour(s){scope}."

    lines = [f"Notifications (last {hours}h):"]
    for notif in notifications:
        ts = _format_timestamp(notif.get("timestamp", 0))
        obj_type = "Host" if notif.get("object_type") == 1 else "Service"
        name = notif.get("name", "unknown")
        contact = notif.get("contact", "unknown")
        method = notif.get("method", "unknown")
        message = notif.get("message", "")
        lines.append(f"  [{ts}] {obj_type} {name} → {contact} via {method}: {message}")

    return "\n".join(lines)
