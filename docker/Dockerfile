# syntax=docker/dockerfile:1
# Asgard test sandbox — clean room.
# Stage 1 compiles the self-contained binary with bun (Linux target).
# Stage 2 is a BARE base (no node/bun/git) — installs + verifies the binary there,
# proving the zero-dependency install. Run ephemerally: docker run --rm.

FROM oven/bun:1 AS builder
WORKDIR /src
COPY package.json tsconfig.json ./
COPY src ./src
RUN bun build src/cli.ts --compile --outfile /out/asgard

FROM debian:stable-slim AS sandbox
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates bash \
 && rm -rf /var/lib/apt/lists/*
# realistic install: non-root user, ~/.local/bin + ~/.asgard
RUN useradd --create-home asgard
USER asgard
WORKDIR /home/asgard
ENV PATH="/home/asgard/.local/bin:${PATH}"
COPY --chown=asgard:asgard --from=builder /out/asgard /home/asgard/prebuilt/asgard
COPY --chown=asgard:asgard install.sh ./install.sh
COPY --chown=asgard:asgard docker/sandbox-test.sh ./sandbox-test.sh
CMD ["bash", "sandbox-test.sh"]
