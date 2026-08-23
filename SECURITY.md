# Security Design Document

## Threat Model

| Asset | Sensitivity | Impact if Compromised |
|-------|-------------|----------------------|
| Nagios HTTP credentials | Critical | Full monitoring control, command execution |
| Host/service status data | Medium | Infrastructure reconnaissance |
| Nagios commands | High | Acknowledge/silence real alerts, schedule checks |

## Security Architecture

| Layer | Implementation |
|-------|---------------|
| Input Validation | Pydantic models, extra="forbid", field limits |
| Credential Handling | SecretStr, env-var-only, scrubbed from errors |
| API Hardening | HTTP Basic Auth header, TLS, 30s timeout |
| Output Sanitization | Password scrubbing in error messages |
| Runtime Protection | No filesystem access, no shell, no eval |
| Supply Chain | Hummingbird base, weekly CVE scans, Gourmand |

## Reporting Security Issues

Report via [GitHub private security advisory](https://github.com/crunchtools/mcp-nagios/security/advisories/new).
