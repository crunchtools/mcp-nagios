# Two stages, because the runtime base has no shell.
#
# quay.io/hummingbird/python:latest was rebuilt distroless on 2026-08-19 and now
# contains no /bin/sh, so a `RUN` in the final stage fails with
# "executable file `/bin/sh` not found". Anything that needs to execute has to
# happen in the builder; the final stage may only COPY.

FROM quay.io/hummingbird/python:latest-builder AS pip-builder
USER 0

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/

# --target rather than a plain install: the builder runs as a non-root user with
# HOME=/tmp, so pip would otherwise scatter a *user* install into /tmp/.local.
# It also avoids hardcoding a python3.NN path that changes under us on rebuild.
RUN pip install --no-cache-dir --target=/site .

# Verified here rather than in the final stage, which cannot execute anything.
RUN PYTHONPATH=/site python -c "from mcp_nagios_crunchtools import main; print('Installation verified')"

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

# Only the installed packages cross into the runtime image — no pip, no shell,
# no package manager.
COPY --from=pip-builder /site /site
ENV PYTHONPATH=/site

EXPOSE 8026
ENTRYPOINT ["python", "-m", "mcp_nagios_crunchtools"]
