# mcp-nagios-crunchtools Constitution

> **Version:** 1.0.0
> **Ratified:** 2026-08-23
> **Status:** Active
> **Inherits:** [crunchtools/constitution](https://github.com/crunchtools/constitution) v1.0.0
> **Profile:** MCP Server

## I. Core Principles

### 1. Five-Layer Security Model

Every change MUST preserve all five security layers.

**Layer 1 -- Credential Protection:** HTTP Basic Auth credentials stored as SecretStr, env-var-only, auto-scrubbed from errors.

**Layer 2 -- Input Validation:** Pydantic models with extra="forbid" for all write operations.

**Layer 3 -- API Hardening:** Auth via HTTP Basic Auth header, TLS, 30s request timeout.

**Layer 4 -- Dangerous Operation Prevention:** No filesystem, no shell, no eval. Tools are pure API wrappers.

**Layer 5 -- Supply Chain Security:** Weekly CVE scanning, Hummingbird base images, Gourmand gating.

### 2. Two-Layer Tool Architecture

- `server.py` -- `@mcp.tool()` decorated wrappers
- `tools/*.py` -- Pure async functions calling `client.py`

### 3. Three Distribution Channels

| Channel | Command |
|---------|---------|
| uvx | `uvx mcp-nagios-crunchtools` |
| pip | `pip install mcp-nagios-crunchtools` |
| Container | `podman run quay.io/crunchtools/mcp-nagios` |

### 4. Semantic Versioning

Follow SemVer 2.0.0. Version bumped at release time, not per-commit.

## II. Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.10+ |
| MCP Framework | FastMCP |
| HTTP Client | httpx |
| Validation | Pydantic v2 |
| Container Base | Hummingbird |
| Build System | hatchling |

## III. Naming Conventions

| Context | Name |
|---------|------|
| GitHub repo | `crunchtools/mcp-nagios` |
| PyPI package | `mcp-nagios-crunchtools` |
| CLI command | `mcp-nagios-crunchtools` |
| Python module | `mcp_nagios_crunchtools` |
| Container image | `quay.io/crunchtools/mcp-nagios` |
| HTTP port | 8026 |
| License | AGPL-3.0-or-later |
