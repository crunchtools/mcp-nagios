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
