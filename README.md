# mcp-nagios-crunchtools

Secure MCP server for Nagios Core monitoring. Query host and service status, acknowledge problems, add comments, schedule forced checks, and read notification history.

## Installation

```bash
uvx mcp-nagios-crunchtools
```

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `NAGIOS_URL` | Yes | Base URL (e.g., `https://nagios.crunchtools.com`) |
| `NAGIOS_USER` | Yes | HTTP Basic Auth username |
| `NAGIOS_PASS` | Yes | HTTP Basic Auth password |
| `TZ` | Effectively yes | The container's local timezone. Must match the Nagios server's own timezone. |

### Why `TZ` matters

`schedule_check` submits a `start_time` to `cmd.cgi`, which parses it as naive
wall-clock time in the Nagios server's local timezone — there is no offset field
to send. The value is therefore built with `time.localtime()`, so this container
must run in the same timezone as the Nagios server.

When it does not, forced checks are silently scheduled into the future by the
offset between the two — four hours against an EDT server — and "check now"
appears to do nothing at all. No error is raised. This was a real defect, fixed
in 0.1.2 by switching from `gmtime()` to `localtime()`; the timezone assumption
it introduced is why `TZ` belongs in this table rather than being left implicit.

## Tools

| Tool | Description |
|------|-------------|
| `nagios_host_status` | Query a single host's status |
| `nagios_service_status` | Query a single service's status |
| `nagios_current_problems` | All hosts/services not in OK state |
| `nagios_acknowledge` | Acknowledge a host or service problem |
| `nagios_add_comment` | Add a comment to a host or service |
| `nagios_schedule_check` | Force an immediate re-check |
| `nagios_notification_history` | Recent notifications |

## License

AGPL-3.0-or-later
