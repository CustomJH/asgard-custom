# Asgard DEV sandbox — persistent, batteries-included dev box.
# Install + test Asgard alongside Claude Code / Codex (you install those yourself).
# Distinct from docker/Dockerfile (the ephemeral clean-room install test).
FROM node:24-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates ripgrep python3 build-essential sudo less vim jq \
 && rm -rf /var/lib/apt/lists/*

# non-root user with passwordless sudo (install anything you need)
RUN useradd -m -s /bin/bash dev \
 && echo 'dev ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/dev && chmod 0440 /etc/sudoers.d/dev
USER dev
WORKDIR /home/dev

# bun — Asgard runtime / build
RUN curl -fsSL https://bun.sh/install | bash

# user-local npm globals so `npm i -g @anthropic-ai/claude-code` / `@openai/codex` need no sudo
ENV BUN_INSTALL=/home/dev/.bun
ENV PATH=/home/dev/.npm-global/bin:/home/dev/.bun/bin:/home/dev/.local/bin:/usr/local/bin:/usr/bin:/bin
RUN npm config set prefix /home/dev/.npm-global \
 && printf '\n# asgard devbox\nexport BUN_INSTALL=/home/dev/.bun\nexport PATH=/home/dev/.npm-global/bin:/home/dev/.bun/bin:/home/dev/.local/bin:$PATH\n' >> /home/dev/.bashrc

# login shells: /etc/profile resets PATH, so re-add via profile.d (runs after the reset)
USER root
RUN printf 'export BUN_INSTALL=/home/dev/.bun\nexport PATH=/home/dev/.npm-global/bin:/home/dev/.bun/bin:/home/dev/.local/bin:$PATH\n' > /etc/profile.d/asgard-devbox.sh
USER dev

CMD ["bash"]
