# 컨테이너 하나 = 에이전트 하나

컨테이너를 여럿 띄워서 각자 자기 기억으로 도는 에이전트를 세우는 방법을 적어요.

## 먼저 — 이 폴더에 이미지가 둘 있고, 서로 다른 것이에요

헷갈리기 쉬운 자리라 먼저 못박아요.

| 파일 | 무엇인가 | 누가 쓰나 |
| --- | --- | --- |
| `src/asgard/assets/container_kit/Dockerfile` | **에이전트가 실제로 도는 런타임 이미지** | `asgard start --execution container`, `docker/compose.agents.yml` |
| `docker/Dockerfile` | 설치 시험용 클린룸 (bare debian에 `install.sh`로 처음부터 설치해 보는 것) | `docker/sandbox.sh` |

에이전트 관련 배선(`ASGARD_HOME`·볼륨)은 **앞의 것에만** 있어요. 뒤의 것은 "런타임이 하나도
없는 기계에 설치가 되는가"만 재는 이미지라 에이전트와 상관이 없어요.

## 가르는 것은 두 줄이에요

컨테이너가 "기억 없는 기본 에이전트"가 아니라 특정 에이전트로 뜨게 하는 것은 이것뿐이에요.

```
ASGARD_HOME=/agent/<이름>          이 컨테이너는 누구인가
<볼륨>:/agent/<이름>               그 에이전트의 1차 기억·세션·설정을 어디에 두는가
```

경로의 **마지막 조각이 곧 표시 이름**이에요. `profiles.active()`가 이 경로를 기계 뿌리로도
`profiles/<id>`로도 못 읽어서 `custom`을 돌려주고, `profiles.label_for()`가 명세 없는 홈을 홈
디렉터리 이름으로 불러요. 그래서 컨테이너를 열 개 띄워도 로그에서 서로 구분돼요.

## 1. 호스트의 에이전트를 그대로 컨테이너에 (`asgard start`)

지금 이 프로세스의 에이전트를 컨테이너로 넘겨요. 따로 설정할 것이 없어요.

```sh
asgard agent use loki
asgard start --execution container
```

띄우면 이렇게 알려줘요.

```
Starting docker container asgard-myproject-1a2b3c4d-isolated-51234.
Workspace: /Users/yun/.asgard/sandboxes/... (private copy)
Agent: loki — /Users/yun/.asgard/profiles/loki -> /agent/loki
```

여기서 에이전트 홈은 **bind 마운트**예요. 이 컨테이너는 호스트에 이미 있는 그 에이전트
자신이라, 안에서 적은 1차 기억이 호스트의 `asgard agent show loki`에 그대로 보여야 하기
때문이에요. named volume으로 걸면 도커가 쥔 별도 사본이 되어서 호스트 CLI가 그 기억을 못 봐요.

## 2. 컨테이너 전용 에이전트 여럿 (compose)

호스트에 없는 에이전트를 컨테이너마다 하나씩 세우는 경우예요. `compose.agents.yml`에
`freyja`·`loki`·`mimir` 셋이 예시로 들어 있어요.

```sh
export ASGARD_VERSION="$(asgard --version | tr -cd '0-9.')"

# 런타임 이미지를 먼저 구워요 (asgard start --execution container 가 굽는 것과 같은 이미지예요)
docker build --build-arg ASGARD_VERSION="$ASGARD_VERSION" \
  -t "asgard-runtime:$ASGARD_VERSION" src/asgard/assets/container_kit

docker compose -f docker/compose.agents.yml up -d
```

`ASGARD_VERSION`을 안 주면 compose가 거기서 멈춰요. 태그를 파일에 박아두면 릴리스가 올라갈
때마다 낡아서 조용히 옛 이미지를 쓰게 되는데, 그것보다 멈추는 편이 나아서 그렇게 했어요.

여기 홈은 **named volume**이에요. 이 에이전트들은 호스트의 `~/.asgard/profiles/` 아래에 없는
컨테이너 전용이라, bind로 걸면 호스트에 아무도 안 쓰는 디렉터리만 남아요. 볼륨은 컨테이너를
지워도 남으니까 `docker compose down` 뒤에 다시 올려도 기억이 이어져요. 진짜로 지우려면
`docker compose -f docker/compose.agents.yml down -v`를 써야 해요.

작업 폴더를 실제 저장소로 바꾸려면 서비스의 `<이름>-workspace:/workspace` 줄을 바꾸면 돼요.

```yaml
    volumes:
      - freyja-home:/agent/freyja
      - /Users/yun/develop/my-repo:/workspace
```

### 각자 자기 에이전트로 떴는지 확인

```sh
for a in freyja loki mimir; do
  docker compose -f docker/compose.agents.yml exec -T "$a" \
    asgard agent where --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["home"])'
done
```

`/agent/freyja`·`/agent/loki`·`/agent/mimir`가 나오면 셋이 서로 다른 홈으로 도는 거예요.

> `where --json`의 `process` 필드는 세 컨테이너 모두 `custom`이 나와요. 이름이 아니라 "이름
> 없는 홈"이라는 표지라서 그래요 — 컨테이너를 가르는 값은 `home` 쪽이에요.

## 자격증명은 기본으로 안 넘어가요

`~/.asgard/credentials.json`은 **기계의 것**이지 에이전트의 것이 아니에요(`profiles.py`의
경계). 그래서 컨테이너에 기본으로 안 실어요. 대신 이렇게 돼요.

- **provider 키**는 환경변수로 들어가요. `ANTHROPIC_API_KEY`·`OPENAI_API_KEY`·
  `ANTHROPIC_AUTH_TOKEN`·`NVIDIA_API_KEY`·`OLLAMA_API_KEY`가 호스트에 있으면 그대로 전달돼요.
  파일을 안 건드리고도 대부분 이걸로 끝나요.
- **에이전트 전용 키**는 이미 같이 넘어가요. `<에이전트 홈>/credentials.json`은 홈 볼륨 안에
  있으니까요 (`providers.cred_path()`가 그 파일을 기계 공용보다 먼저 봐요).
- 남는 것은 **기계 공용 키 파일**뿐이라, 그것만 명시적으로 켜야 넘어가요.

```sh
ASGARD_CONTAINER_CREDENTIALS=1 asgard start --execution container
```

켜면 호스트의 `~/.asgard/credentials.json`을 컨테이너의 `/root/.asgard/credentials.json`에
**읽기 전용**으로 걸어요. 편한 대신 컨테이너 안에서 도는 것이 호스트 키를 읽을 수 있게 되니,
믿는 작업에만 켜세요. compose 쪽에는 이 옵션이 없어요 — 필요하면 서비스에
`- ~/.asgard/credentials.json:/root/.asgard/credentials.json:ro`를 직접 적으세요.

## 알아둘 것

- 이미지는 root로 돌아요. 리눅스 호스트에서 bind 마운트를 쓰면 컨테이너가 만든 파일이 root
  소유로 남아요. macOS의 OrbStack·Docker Desktop은 UID를 대신 맞춰줘서 이 문제가 없어요.
- 기계 뿌리(`~/.asgard`의 `projects.json`·`sandboxes`·완성 캐시)는 컨테이너에 안 넘어가요.
  컨테이너 안에서는 `/root/.asgard`가 그 자리인데 비어 있어요.
- 에이전트끼리 기억을 나누는 통로는 **없어요**. 지금은 완전 격리이고, 그건 의도된 선택이에요
  (`src/asgard/profiles.py` 첫 주석에 근거가 있어요).
- compose 예시의 이름 셋은 `asgard agent create`로도 만들 수 있는 이름이에요. 다만 `thor`는
  CLI 하위 명령과 겹쳐서 예약어라 에이전트 이름으로 못 써요.
