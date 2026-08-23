# mcp-nagios-crunchtools

MCP server for Nagios Core monitoring on lotor. Part of RT #1459 (Zabbix-to-Nagios migration).

## Quick Start

```bash
uv sync --all-extras
NAGIOS_URL=https://nagios.crunchtools.com NAGIOS_USER=admin NAGIOS_PASS=secret uv run mcp-nagios-crunchtools
```

## Environment Variables

- `NAGIOS_URL` (required) — Nagios base URL
- `NAGIOS_USER` (required) — HTTP Basic Auth username
- `NAGIOS_PASS` (required) — HTTP Basic Auth password

## Tools (7)

### Status
- `nagios_host_status` — query host status
- `nagios_service_status` — query service status
- `nagios_current_problems` — all non-OK hosts/services

### Commands
- `nagios_acknowledge` — acknowledge a problem
- `nagios_add_comment` — add comment to host/service
- `nagios_schedule_check` — force immediate re-check

### History
- `nagios_notification_history` — recent notifications

## Dev Commands

```bash
uv run ruff check src tests
uv run mypy src
uv run pytest -v
podman build -f Containerfile .
```

## Architecture

Two-layer tools: `server.py` (@mcp.tool wrappers) → `tools/*.py` (pure async) → `client.py` (httpx).
Nagios CGI JSON API: statusjson.cgi (reads), archivejson.cgi (history), cmd.cgi (commands).
