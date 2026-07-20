FROM python:3.14-slim

ARG ASGARD_VERSION
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl git \
    && curl -fsSL -o /tmp/asgard-install.sh \
        https://raw.githubusercontent.com/CustomJH/asgard-custom/main/install.sh \
    && ASGARD_VERSION="${ASGARD_VERSION}" ASGARD_NO_IMAGE=1 bash /tmp/asgard-install.sh \
    && rm -f /tmp/asgard-install.sh \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:${PATH}"
WORKDIR /workspace
ENTRYPOINT ["asgard", "start"]
