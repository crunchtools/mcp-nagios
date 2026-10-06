# mcp-nagios-crunchtools Constitution

> **Version:** 1.1.0
> **Ratified:** 2026-08-23
> **Amended:** 2026-10-02
> **Status:** Active
> **Inherits:** [crunchtools/constitution](https://github.com/crunchtools/constitution) v1.20.0
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
- **Surface:** the Nagios CGI JSON API only (`statusjson.cgi`,
  `archivejson.cgi`, `cmd.cgi`). No filesystem access, shell execution or
  code evaluation.

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
