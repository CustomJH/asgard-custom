# syntax=docker/dockerfile:1
# asgard-k6 — 아스가르드가 소유하는 부하 시험 러너 이미지.
#
# 왜 공개 이미지를 그대로 쓰지 않고 우리 이름을 붙이나: 부하 수치는 도구의 판에 딸려 있다.
# `grafana/k6:latest` 로 잰 값이 나중에 어느 k6 였는지는 복원되지 않고, 태그가 움직이면
# 같은 명령이 다른 도구로 돈다. 여기서 판을 고정하고 그 이름을 실행마다 보고서에 새긴다.
#
# 시나리오·라이브러리·기준 표적(pacer)을 함께 굽는다 — 마운트 없이 이미지 하나로 돌 수 있어야
# CI 에서 체크아웃 없이 쓸 수 있다. 아스가르드가 직접 몰 때는 같은 키트를 읽기 전용으로
# 덮어 마운트하므로(정본은 언제나 체크아웃 쪽) 두 경로가 같은 시나리오를 돈다.
#
# 빌드 (컨텍스트는 저장소 루트 — 키트가 src/ 아래 있기 때문):
#   docker build -f docker/asgard-k6/Dockerfile -t asgard-k6:local .
#
# 실행 (마운트 없이 단독):
#   docker run --rm asgard-k6:local run /asgard/scenarios/http-smoke.js
#
# 아스가르드가 이 이미지를 잡는 법: 로컬에 `asgard-k6:<버전>` 또는 `asgard-k6:local` 이
# 있으면 그것을 쓰고, 없으면 공개 k6 이미지로 내려간다 (`asgard k6 doctor` 가 어느 쪽인지 말한다).

ARG K6_BASE=grafana/k6:latest
FROM ${K6_BASE}

ARG ASGARD_VERSION=dev
LABEL org.opencontainers.image.title="asgard-k6" \
      org.opencontainers.image.description="Asgard load-testing runner — k6 with the asgard-k6 scenario kit" \
      org.opencontainers.image.version="${ASGARD_VERSION}" \
      com.asgard.lane="asgard-k6"

# 키트 정본은 체크아웃의 src/asgard/assets/k6_kit — 휠에도 같은 경로로 실려 나간다.
# (tests/test_k6.py 가 이 COPY 원본 경로를 봉인한다: 이미지가 다른 키트를 굽는 순간
#  "같은 시나리오를 돈다"는 전제가 조용히 깨지기 때문이다.)
COPY src/asgard/assets/k6_kit /asgard

# 요약이 나갈 자리. 러너가 여기에 실행별 디렉터리를 bind 하고, 마운트 없이 돌 때도
# 컨테이너 안에서 쓸 수 있어야 한다 — k6 이미지는 비루트(uid 12345)로 돈다.
USER root
RUN mkdir -p /asgard/out && chmod 0777 /asgard/out
USER k6

ENV ASGARD_K6_OUT=/asgard/out/summary.json
WORKDIR /asgard
ENTRYPOINT ["k6"]
CMD ["run", "/asgard/scenarios/selftest.js"]
