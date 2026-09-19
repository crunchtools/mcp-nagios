

# Stage 1: Builder (has a shell, dnf and build tools)
FROM quay.io/hummingbird/python:latest-builder AS builder
USER 0
WORKDIR /app
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Stage 2: Runtime (distroless -- no shell, no package manager)
FROM quay.io/hummingbird/python:latest

LABEL name="mcp-nagios-crunchtools" \
      version="0.1.0" \
      summary="Secure MCP server for Nagios Core monitoring" \
      description="Query status, acknowledge problems, add comments, schedule checks" \
      maintainer="crunchtools.com" \
      url="https://github.com/crunchtools/mcp-nagios" \
      io.k8s.display-name="MCP Nagios CrunchTools" \
      io.openshift.tags="mcp,nagios,monitoring" \
      org.opencontainers.image.source="https://github.com/crunchtools/mcp-nagios" \
      org.opencontainers.image.description="Secure MCP server for Nagios Core monitoring" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

WORKDIR /app

COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Verify the install. Exec form: this stage has no /bin/sh for RUN's shell form.
RUN ["python3", "-c", "from mcp_nagios_crunchtools import main; print('Installation verified')"]

EXPOSE 8026
ENTRYPOINT ["python", "-m", "mcp_nagios_crunchtools"]
