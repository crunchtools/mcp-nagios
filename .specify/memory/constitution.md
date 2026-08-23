# mcp-nagios-crunchtools Constitution

> **Version:** 1.0.0
> **Ratified:** 2026-08-23
> **Status:** Active
> **Inherits:** [crunchtools/constitution](https://github.com/crunchtools/constitution) v1.0.0
> **Profile:** MCP Server

---

## I. Core Principles

### 1. Five-Layer Security Model

Every change MUST preserve all five security layers. No exceptions.

**Layer 1 -- Credential Protection:**
- HTTP Basic Auth credentials stored as `SecretStr` (never logged or exposed)
- Environment-variable-only storage
- Automatic scrubbing from error messages

**Layer 2 -- Input Validation:**
- Pydantic models enforce strict data types with `extra="forbid"`
- Hostname and service description length limits
- Comment length limits

**Layer 3 -- API Hardening:**
- Auth via HTTP Basic Auth header (never in URL)
- Mandatory TLS certificate validation
- Request timeouts (30s) and response size awareness

**Layer 4 -- Dangerous Operation Prevention:**
- No filesystem access, shell execution, or code evaluation
- No `eval()`/`exec()` functions
- Tools are pure API wrappers with no side effects

**Layer 5 -- Supply Chain Security:**
- Weekly automated CVE scanning via GitHub Actions
- Hummingbird container base images (minimal CVE surface)
- Gourmand AI slop detection gating all PRs

### 2. Two-Layer Tool Architecture

Tools follow a strict two-layer pattern:
- `server.py` -- `@mcp.tool()` decorated functions that validate args and delegate
- `tools/*.py` -- Pure async functions that call `client.py` HTTP methods

Never put business logic in `server.py`. Never put MCP registration in `tools/*.py`.

### 3. Three Distribution Channels

Every release MUST be available through all three channels simultaneously:

| Channel | Command | Use Case |
|---------|---------|----------|
| uvx | `uvx mcp-nagios-crunchtools` | Zero-install, Claude Code |
| pip | `pip install mcp-nagios-crunchtools` | Virtual environments |
| Container | `podman run quay.io/crunchtools/mcp-nagios` | Isolated, systemd |

### 4. Three Transport Modes

The server MUST support all three MCP transports:
- **stdio** (default) -- spawned per-session by Claude Code
- **SSE** -- legacy HTTP transport
- **streamable-http** -- production HTTP, systemd-managed containers

### 5. Semantic Versioning

Follow [Semantic Versioning 2.0.0](https://semver.org/) strictly.

### 6. AI Code Quality

All code MUST pass Gourmand checks before merge. Zero violations required.

---

## II. Technology Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Language | Python | 3.10+ |
| MCP Framework | FastMCP | Latest |
| HTTP Client | httpx | Latest |
| Validation | Pydantic | v2 |
| Container Base | Hummingbird | Latest |
| Package Manager | uv | Latest |
| Build System | hatchling | Latest |
| Linter | ruff | Latest |
| Type Checker | mypy (strict) | Latest |
| Tests | pytest + pytest-asyncio | Latest |
| Slop Detector | gourmand | Latest |

---

## III. Testing Standards

### Mocked API Tests (MANDATORY)

Every tool MUST have a corresponding mocked test. Tests use `httpx.AsyncClient` mocking -- no live API calls, no credentials required in CI.

### Input Validation Tests

Every Pydantic model in `models.py` MUST have tests in `test_validation.py`.

### Tool Count Assertion

`test_tool_count` MUST be updated whenever tools are added or removed.

---

## IV. Gourmand (AI Slop Detection)

All code MUST pass `gourmand --full .` with **zero violations** before merge. Gourmand is a CI gate in GitHub Actions.

### Configuration

- `gourmand.toml` -- Check settings, excluded paths
- `gourmand-exceptions.toml` -- Documented exceptions with justifications

### Exception Policy

Exceptions MUST have documented justifications in `gourmand-exceptions.toml`.

---

## V. Code Quality Gates

Every code change must pass through these gates in order:

1. **Lint** -- `uv run ruff check src tests`
2. **Type Check** -- `uv run mypy src`
3. **Tests** -- `uv run pytest -v` (all passing, mocked httpx)
4. **Gourmand** -- `gourmand --full .` (zero violations)
5. **Container Build** -- `podman build -f Containerfile .`

---

## VI. Naming Conventions

| Context | Name |
|---------|------|
| GitHub repo | `crunchtools/mcp-nagios` |
| PyPI package | `mcp-nagios-crunchtools` |
| CLI command | `mcp-nagios-crunchtools` |
| Python module | `mcp_nagios_crunchtools` |
| Container image | `quay.io/crunchtools/mcp-nagios` |
| systemd service | `mcp-nagios.service` |
| HTTP port | 8026 |
| License | AGPL-3.0-or-later |

---

## VII. Development Workflow

### Adding a New Tool

1. Add the async function to the appropriate `tools/*.py` file
2. Export it from `tools/__init__.py`
3. Import it in `server.py` and register with `@mcp.tool()`
4. Add a mocked test in `tests/test_tools.py`
5. Update the tool count in `test_tool_count`
6. Run all five quality gates
7. Update CLAUDE.md tool listing

---

## VIII. Governance

### Amendment Process

1. Create a PR with proposed changes to this constitution
2. Document rationale in PR description
3. Require maintainer approval
4. Update version number upon merge

### Ratification History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-08-23 | Initial constitution |

---

## IX. References

- RT #1459: Zabbix-to-Nagios migration
- Nagios CGI JSON API: statusjson.cgi, archivejson.cgi, cmd.cgi
- [crunchtools/constitution](https://github.com/crunchtools/constitution) v1.0.0
