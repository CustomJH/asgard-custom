# Asgard DEV box — persistent, batteries-included (CUS-108 Path B).
# Python 3.14 via uv (Asgard's runtime) + node (Claude Code / Codex / cursor-agent CLIs) + dev tools.
# Install & test Asgard alongside those agents inside it. Distinct from docker/Dockerfile (clean-room).
FROM node:24-bookworm

# dev tooling — vim, a nice `ll`, ripgrep/fd/bat/fzf/jq/tree, git, build tools, sudo.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates build-essential sudo \
      vim less jq tree unzip ripgrep fd-find bat fzf \
 && rm -rf /var/lib/apt/lists/*

# non-root user with passwordless sudo (install anything you need)
RUN useradd -m -s /bin/bash dev \
 && echo 'dev ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/dev && chmod 0440 /etc/sudoers.d/dev
USER dev
WORKDIR /home/dev

# uv — Asgard's Python toolchain; installs a standalone CPython 3.14 (no system Python needed).
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
 && ~/.local/bin/uv python install 3.14

# PATH: uv tool bin (asgard) + user npm globals (claude-code/codex install without sudo).
ENV PATH=/home/dev/.local/bin:/home/dev/.npm-global/bin:/usr/local/bin:/usr/bin:/bin
RUN npm config set prefix /home/dev/.npm-global

# dev conveniences: ll/la/l aliases, debian bat/fd naming, editor, PATH for interactive shells.
RUN cat >> /home/dev/.bashrc <<'RC'

# ── asgard devbox ──
export PATH=/home/dev/.local/bin:/home/dev/.npm-global/bin:$PATH
export EDITOR=vim
alias ll='ls -alF --color=auto'
alias la='ls -A --color=auto'
alias l='ls -CF --color=auto'
alias ..='cd ..'
alias ...='cd ../..'
alias gs='git status'
alias gd='git diff'
command -v batcat >/dev/null && alias bat='batcat'
command -v fdfind >/dev/null && alias fd='fdfind'
# install/refresh asgard from the mounted repo (--refresh-package: bust uv's stale path build cache)
# && completions --install: 서브커맨드 자동완성까지 배선 (bashrc 에 가드된 source 한 줄, 멱등)
alias asgard-install='uv tool install --force --python 3.14 --refresh-package asgard ~/asgard && asgard completions --install'
# run the mounted working tree directly (editable) — 릴리스/설치 없이 호스트에서 고친 코드 즉시 실행.
# UV_PROJECT_ENVIRONMENT: venv 를 마운트 밖에 둔다 (호스트 .venv 는 macOS 바이너리 — 충돌).
alias asgard-dev='UV_PROJECT_ENVIRONMENT=$HOME/.asgard-dev-venv uv run --project $HOME/asgard asgard'
echo "asgard devbox — Python 3.14 (uv) + node $(node -v). install: asgard-install · dev-run: asgard-dev"
RC

# login shells reset PATH via /etc/profile — re-add after the reset.
USER root
RUN printf 'export PATH=/home/dev/.local/bin:/home/dev/.npm-global/bin:$PATH\n' > /etc/profile.d/asgard-devbox.sh
USER dev

CMD ["bash"]
