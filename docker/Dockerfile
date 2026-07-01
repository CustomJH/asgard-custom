# syntax=docker/dockerfile:1
# Asgard test sandbox — clean room (CUS-108 Path B). BARE base: no node/bun/python/uv preinstalled.
# install.sh bootstraps uv + a standalone CPython 3.14 and installs asgard as a uv tool — proving the
# zero-runtime install. Run ephemerally: docker run --rm.

FROM debian:stable-slim AS sandbox
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates bash \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home asgard
USER asgard
WORKDIR /home/asgard
ENV PATH="/home/asgard/.local/bin:${PATH}"
# Just enough of the checkout for install.sh to install from the local project (no git needed).
COPY --chown=asgard:asgard pyproject.toml install.sh /home/asgard/src/
COPY --chown=asgard:asgard src /home/asgard/src/src
COPY --chown=asgard:asgard docker/sandbox-test.sh /home/asgard/src/docker/sandbox-test.sh
CMD ["bash", "/home/asgard/src/docker/sandbox-test.sh"]
