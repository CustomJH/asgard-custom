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

# 컨테이너 하나 = 에이전트 하나.
#
# 에이전트 홈은 /agent/<이름> 이고 마지막 조각이 곧 표시 이름이다: profiles.active()가
# 이 경로를 뿌리로도 profiles/<id>로도 못 읽어 `custom`을 돌려주고, profiles.label_for()가
# 명세 없는 홈을 홈 디렉터리 이름으로 부른다. 그래서 컨테이너를 여럿 띄워도 로그와
# `asgard agent where`가 이 이름으로 서로를 가른다. 이 경로는 sandbox.CONTAINER_AGENT_ROOT와
# **동일 유지** — 한쪽만 바꾸면 실행측이 마운트한 자리와 이미지가 읽는 자리가 어긋난다.
ENV ASGARD_HOME=/agent/default
RUN mkdir -p /agent/default

# 볼륨 자리. 1차 기억·세션·설정이 컨테이너 수명보다 오래 살아야 "개별 동작하는 에이전트"가
# 된다 — 안 걸면 컨테이너가 죽을 때 그 에이전트가 배운 것도 같이 사라진다.
VOLUME ["/agent"]

# 기계 뿌리(/root/.asgard — credentials.json·projects.json)는 이미지에 없다. 자격은 기계의
# 것이지 에이전트의 것이 아니라서 기본으로 안 넘긴다 (provider 키는 환경변수로 들어오고,
# 에이전트 전용 키는 위 /agent/<이름>/credentials.json이라 볼륨에 이미 포함된다).
WORKDIR /workspace
ENTRYPOINT ["asgard", "start"]
