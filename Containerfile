

# Stage 1: Lock (turn uv.lock into the exact dependency set to install)
FROM quay.io/hummingbird/python:3.14-builder AS lock
USER 0
RUN pip install --no-cache-dir uv==0.13.7
WORKDIR /lock
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project \
      --format requirements-txt -o /requirements.txt

# Stage 2: Builder (has a shell, dnf and build tools)
FROM quay.io/hummingbird/python:3.14-builder AS builder
USER 0
WORKDIR /app
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
# Dependencies come from uv.lock, not from a fresh resolve. `pip install .`
# read only pyproject.toml, whose floors carry no upper bound, so the image
# shipped whatever had been released that morning -- a dependency set no test
# had ever run against. That is the mcp-gemini / trentina issue #79 bug
# (RT #1564). --no-deps stops pip re-resolving what the lock already decided.
COPY --from=lock /requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-deps -r /tmp/requirements.txt
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

# Stage 3: Runtime (distroless -- no shell, no package manager)
FROM quay.io/hummingbird/python:3.14

# version MUST track pyproject.toml. It is a fourth copy of the version string
# that check_version_sync() does not look at (it checks pyproject.toml,
# __init__.py and server.py), so it drifts silently -- it sat at 0.1.0 through
# the 0.1.2 and 0.2.0 releases, which made a correctly-updated running
# container look three versions stale on inspection.
LABEL name="mcp-nagios-crunchtools" \
      version="0.10.1" \
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
