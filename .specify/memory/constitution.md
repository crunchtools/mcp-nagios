# mcp-nagios-crunchtools Constitution

> **Version:** 1.1.0
> **Ratified:** 2026-08-23
> **Amended:** 2026-10-02
> **Status:** Active
> **Inherits:** [crunchtools/constitution](https://github.com/crunchtools/constitution) v1.26.0
> **Profile:** MCP Server

This file holds what is specific to mcp-nagios. The fleet rules and the MCP
Server profile (five-layer security model, two-layer tools, distribution
channels, quality gates, Gourmand) apply at the inherited version and are
checked against this repo's files by `constitution.yml`. They are not
restated here.

## Security Model Specifics

- **Credentials:** Nagios CGI HTTP Basic Auth username and password, held as
  `SecretStr`, read from the environment only and scrubbed from error
  messages.
- **Input limits:** hostnames, service descriptions and comments are
  length-bounded in the Pydantic models (`extra="forbid"`).
- **API:** auth travels in the Basic Auth header, never the URL; TLS
  certificates are always validated; requests time out after 30s.
- **Surface:** the Nagios CGI JSON API (`statusjson.cgi`, `archivejson.cgi`,
  `cmd.cgi`), plus one optional read-only file: `nagios.log` at
  `NAGIOS_LOG_PATH`. archivejson.cgi reads downtime log entries only for
  availability and never lists them, so the log is the only source of
  downtime history. The path is set by the operator, never by a tool caller,
  and the file is only ever opened for reading. No other filesystem access,
  no shell execution, no code evaluation.
- **Identity:** `NAGIOS_COMMENT_AUTHOR` is this server's name on what it
  records in Nagios. `nagios_cancel_downtime` acts only on downtime recorded
  under it, so each deployment sets an author no human uses. That filter
  guards against ending someone else's window by accident; it is not an
  authorization boundary, because the CGI user can delete any downtime anyway.

## Instance

| Context | Name |
|---------|------|
| GitHub repo | `crunchtools/mcp-nagios` |
| PyPI package | `mcp-nagios-crunchtools` |
| Container image | `quay.io/crunchtools/mcp-nagios` |
| systemd service | `mcp-nagios.service` |
| HTTP port | 8026 |

## History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-08-23 | Initial constitution (RT #1459, Zabbix-to-Nagios migration) |
| 1.1.0 | 2026-10-02 | Manifest under constitution v1.18.0: profile restatement removed, mcp-nagios specifics kept |
| 1.2.0 | 2026-10-26 | Surface: optional read-only `nagios.log` for downtime history; Identity: comment author bounds cancellation |
