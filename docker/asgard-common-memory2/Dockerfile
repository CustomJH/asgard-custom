FROM ghcr.io/astral-sh/uv:0.8.22 AS uv

FROM cognee/cognee:1.3.0

COPY --from=uv /uv /uvx /bin/

# Cognee's published API image does not include the optional FastEmbed provider.
# Install it at build time so runtime startup never mutates the container.
RUN uv pip install --python /app/.venv/bin/python "fastembed==0.8.0"
