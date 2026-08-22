"""베이스라인 체크 감지 — 이 저장소에서 무엇이 '행동을 실제로 도는' 명령인가.

설정된 체크는 허용 접두사로 거르고, 없으면 보수적으로 감지한다. 감지가 헐거우면 아무것도 안
도는 명령이 초록 증거가 되고(JVM 래퍼의 `-x test`, gradle `help`), 빡빡하면 진짜 스위트가
버려진다. 여기 있는 것은 전부 그 경계 판정이다 — 실행은 baseline 모듈이 한다.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess

from .evidence import trivial_evidence

# Repository policy is untrusted input. A trivial command can erase the LLM Verifier,
# and shell composition can mutate/exfiltrate from the deterministic harness.
SAFE_CHECK_PREFIXES = (
    "pytest ",
    "python -m pytest ",
    "python3 -m pytest ",
    "python -m compileall ",
    "python3 -m compileall ",
    "python -m unittest ",
    "python3 -m unittest ",
    "uv run pytest ",
    # `uv run python -m <안전 모듈>` — 이미 있는 `python -m <같은 모듈>`과 `uv run pytest `의
    # 표기 조합일 뿐, 새로 닿는 실행 파일이 없다. uv 가 정본 인터프리터가 된 뒤 정책에 이렇게
    # 적히는 것이 자연스러워졌는데 표가 못 받아 **조용히 버려지면** 게이트의 유일한 독립 증거
    # 레인이 사라진다. 훅 정본의 `--no-project` 형태는 일부러 넣지 않는다 — 베이스라인 체크는
    # 프로젝트 의존성을 봐야 하므로 프로젝트를 떼는 형태는 애초에 잘못된 설정이다.
    "uv run python -m pytest ",
    "uv run python -m unittest ",
    "uv run python -m compileall ",
    "uv run ruff check ",
    "uv run ruff format --check ",
    "uv run ty check",
    "poetry run pytest ",
    "pdm run pytest ",
    "ruff check ",
    "ruff format --check ",
    "mypy ",
    "pyright ",
    "ty check",
    "npm test",
    "npm run test",
    "pnpm test",
    "yarn test",
    "cargo test",
    "cargo check",
    "go test",
    # JVM 러너는 이 표가 아니라 `jvm_behavior_check` 하나가 받는다 — 접두사로 적어 두면
    # 루트 상대 `./gradlew test` 형태만 통과해 서비스마다 래퍼를 두는 모노레포가 빠지고,
    # 안전 표와 `gate_first_checks_available` 가 서로 다른 기준을 들어 설정이 통과했다가
    # 레인을 못 세운다 (26-08-04 hvami-mono 실측: gradlew 3개가 전부 하위 디렉터리).
    "make test",
    "make check",
    "make verify",
    "test ",
    "false",
)


_PY_EXE = re.compile(r"^python[0-9.]*$")


_SAFE_MODULES = {"pytest", "compileall", "py_compile", "unittest"}


# Gradle·Maven 래퍼는 저장소 안에 있는 파일이다. 신뢰 등급은 `npm test`·`make test` 와 같다 —
# 셋 다 저장소 안 파일이 무엇을 도는지 정한다.
_JVM_WRAPPERS = {"gradlew", "gradlew.bat", "mvnw", "mvnw.cmd"}


_JVM_ON_PATH = {"gradle", "mvn"}


# Maven 은 테스트를 도는 페이즈·골이 `test` 말고도 있다. Gradle 쪽은 태스크 이름이 자유라
# 접두사로 본다 (`testDebugUnitTest`, `:app:test`).
_MVN_TEST_GOALS = {"test", "verify", "integration-test", "surefire:test", "failsafe:integration-test"}


# 실행자 이름에 허용하는 글자 — 셸이 나중에 펴는 것(`$HOME/x/gradlew`, `~/x/gradlew`)을 여기서
# 막는다. `os.path.isabs("$HOME/…")` 는 False 라 절대경로 검사만으로는 안 걸리고, 실행은
# `shell=True` 라 그때는 펴진다 (26-08-05 교차검토 실측).
_RUNNER_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")


# 테스트를 **끄는** 인자. 앞의 것을 안 보면 `./gradlew test -x test` 와 `mvn -DskipTests test` 가
# 아무것도 안 돌리면서 결정론 레인을 세운다 — 그 레인이 LLM 판정자를 대신하므로 exit 0 이
# 설계상 보장된 셈이 된다.
_JVM_SKIP_FLAGS = ("-dskiptests", "-dmaven.test.skip", "-dskipitests")


# Gradle 의 컴파일 전용 태스크 — 이름이 `test` 로 시작하지만 아무 단언도 돌지 않는다.
_GRADLE_NON_RUNNING = {"testclasses", "testfixturesclasses", "testfixturesjar", "testjar"}


def jvm_behavior_check(cmd: str) -> bool:
    """Gradle·Maven 러너가 **테스트 태스크**를 부르는가.

    안전 표(`configured_checks`)와 게이트-우선 판정(`gate_first_checks_available`)이 같은 자를
    쓴다. 종전에는 표는 접두사로 받고 판정은 낱말 두 개를 정확 비교해서, `./gradlew
    testDebugUnitTest` 가 설정으로는 통과했다가 결정론 레인은 못 세웠다 (26-08-04 실측).

    래퍼는 저장소 안 상대 경로만 받는다 — 서비스마다 `gradlew` 를 두는 모노레포가 그 형태고
    (`hvami-batch/gradlew test`), 절대 경로·`..`·셸이 펴는 표기는 저장소 밖 실행 파일로 새는
    길이라 뺀다. `gradle`·`mvn` 은 PATH 실행자라 경로가 붙으면 받지 않는다.

    테스트를 끄는 인자가 하나라도 있으면 거절한다: 이 판정이 참이면 결정론 레인이 LLM 판정자를
    대신하는데, 아무것도 안 돌리는 명령이 그 자리에 서면 exit 0 이 설계상 보장된다."""
    try:
        tokens = _strip_env_prefix(shlex.split(cmd, posix=True))
    except ValueError:
        return False
    if not tokens:
        return False
    head = tokens[0].replace("\\", "/")
    if not _RUNNER_NAME.match(head):
        return False  # `$HOME/…`·`~/…`·글로브 — 셸이 펴는 이름은 저장소 안이라고 말할 수 없다
    base = os.path.basename(head)
    if base in _JVM_WRAPPERS:
        segments = os.path.normpath(head).replace("\\", "/").split("/")
        if os.path.isabs(head) or ".." in segments:
            return False
    elif base in _JVM_ON_PATH:
        if "/" in head:
            return False
    else:
        return False
    maven = base in {"mvn", "mvnw", "mvnw.cmd"}
    if any(token.lower().startswith(_JVM_SKIP_FLAGS) for token in tokens[1:]):
        return False
    tasks: list[str] = []
    excluded: set[str] = set()
    # 값을 뒤 토큰으로 받는 인자 — 그 값을 태스크로 읽으면 `--tests SomeTest` 가 태스크 없는
    # 필터인데 태스크로 읽히고, `-x test` 는 테스트를 **빼는** 명령인데 도는 명령으로 읽힌다.
    pending = ""
    for token in tokens[1:]:
        if pending:
            if pending in ("-x", "--exclude-task"):
                excluded.add(token.split(":")[-1].lower())
            pending = ""
            continue
        if token.startswith("-"):
            pending = token if token in ("-x", "--exclude-task", "--tests", "-P", "-D", "-f", "--file") else ""
            continue
        tasks.append(token)
    for token in tasks:
        task = (token if maven else token.split(":")[-1]).lower()
        if task in excluded:
            continue
        if maven and token in _MVN_TEST_GOALS:
            return True
        if not maven and task.startswith("test") and task not in _GRADLE_NON_RUNNING:
            return True
    return False


def _strip_env_prefix(tokens: list[str]) -> list[str]:
    """선행 `VAR=…` 대입과 `env` 래퍼를 벗긴 나머지 — 신원은 그 뒤부터다."""

    def drop_assignments(rest: list[str]) -> list[str]:
        while rest and "=" in rest[0] and not rest[0].startswith(("=", "-")):
            rest = rest[1:]
        return rest

    tokens = drop_assignments(tokens)
    if tokens and os.path.basename(tokens[0]) == "env":
        tokens = drop_assignments(tokens[1:])
    return tokens


def runner_shape(cmd: str) -> str:
    """안전 프리픽스와 대조할 정규형 — **판정 전용**이다 (실행은 언제나 원문으로 한다).

    같은 검증을 부르는 정당한 표기가 표를 못 넘어 **조용히 버려지던** 것을 막는다: 절대경로
    인터프리터(`/…/.venv/bin/python -m pytest`)·버전 붙은 인터프리터(`python3.13 -m pytest`)가
    그 예다 (26-07-31 실측: 명시 설정 하나가 통째로 사라져 `checks_available`이 false가 됐고,
    게이트의 유일한 독립 증거 레인이 아무 말 없이 침묵했다).

    넓히되 열지는 않는다 — 경로가 붙은 실행자는 **`.venv/bin/` 아래이거나, `-m <안전 모듈>`을
    부르는 인터프리터**일 때만 이름으로 접는다. `./pytest` 같은 저장소 안 파일을 이름으로 접어
    주면, clone으로 딸려 오는 정책 파일(`.asgard/trinity-policy.json`)이 곧 임의 실행 통로가 된다."""
    try:
        tokens = _strip_env_prefix(shlex.split(cmd, posix=True))
    except ValueError:
        return cmd
    if not tokens:
        return cmd
    head = tokens[0]
    base = os.path.basename(head)
    interpreter = bool(_PY_EXE.match(base))
    safe_module = interpreter and len(tokens) >= 3 and tokens[1] == "-m" and tokens[2] in _SAFE_MODULES
    if "/" in head:
        if not (head.startswith(".venv/") or "/.venv/bin/" in head or safe_module):
            return cmd  # 저장소 안 실행 파일일 수 있다 — 이름으로 접지 않는다
        head = base
    if interpreter:
        if not safe_module and head != "python":
            return cmd  # 버전 붙은 인터프리터로 **스크립트**를 부르는 형태는 접지 않는다
        head = "python"
    return shlex.join([head, *tokens[1:]])


def configured_checks(policy: dict) -> tuple[list[str], list[str]]:
    """명시 `baseline_checks`를 (받아들인 것, 거부한 것)으로 가른다.

    거부를 **돌려주는** 것이 요점이다. 조용히 버리면 게이트가 무장해제된 줄 아무도 모른다 —
    설정한 사람은 체크가 도는 줄 알고, 게이트는 독립 증거 없이 모델 신고를 그대로 받는다."""
    accepted: list[str] = []
    rejected: list[str] = []
    for raw in policy.get("baseline_checks") or []:
        cmd = str(raw).strip()
        if not cmd:
            continue
        shape = runner_shape(cmd)
        ok = (
            not trivial_evidence(cmd)
            and "\n" not in cmd
            and not any(token in cmd for token in (";", "&&", "||", "`", "$(", ">", "<"))
            and (
                any(shape == prefix.rstrip() or shape.startswith(prefix) for prefix in SAFE_CHECK_PREFIXES)
                or jvm_behavior_check(cmd)
            )
        )
        (accepted if ok else rejected).append(cmd)
    return accepted, rejected


def rejected_checks(policy: dict) -> list[str]:
    """정책에 적혔지만 안전 표를 못 넘어 **실행되지 않는** 체크 — doctor·state가 이걸 말한다."""
    return configured_checks(policy)[1]


def detect_checks(root: str, policy: dict) -> list[str]:
    """정책 baseline_checks 우선. 없으면 보수적 자동 감지 — pytest 를 먼저 보고, 없으면
    node(`_detect_node_checks`), 그다음 JVM(`_detect_jvm_checks`) 순으로 내려간다.
    lagom: lint 류 자동 감지 안함 — 기존 위반 false-red가 게이트 인질이 된다. 명시 설정으로만.
    uv 프로젝트(uv.lock)는 `uv run pytest`로 — PATH pytest는 venv 밖이라 수집 실패(2/3/4→skip)로
    게이트가 조용히 무력화되고, pytest가 .venv 안에만 있으면 아예 미감지된다. uv의 spawn 실패는
    exit 2라 pytest 미의존 프로젝트도 skip 분류로 fail-open이 유지된다."""
    if policy.get("baseline_checks"):
        return configured_checks(policy)[0]
    import shutil

    if any(os.path.exists(os.path.join(root, p)) for p in ("tests", "test", "pytest.ini", "pyproject.toml")):
        if os.path.exists(os.path.join(root, "uv.lock")) and shutil.which("uv"):
            return ["uv run pytest -x -q"]
        if shutil.which("pytest"):
            return ["pytest -x -q"]
    return _detect_node_checks(root) or _detect_jvm_checks(root)


# Gradle·Maven 이 테스트 소스를 두는 표준 자리. 이 중 하나도 없는 모듈은 러너가 있어도 뺀다.
_JVM_TEST_DIRS = ("src/test/java", "src/test/kotlin", "src/test/groovy")


def _detect_jvm_checks(root: str) -> list[str]:
    """JVM 저장소의 행위 베이스라인 — 러너와 테스트 소스가 같은 모듈에 있을 때만.

    자동 감지가 pytest·npm 계열만 보던 탓에 Gradle·Maven 저장소는 `baseline_checks` 를 손으로
    적지 않으면 **하네스 실행 증거 레인이 통째로 꺼진 채** 돌았다 — 남는 것은 LLM 판정자 하나고,
    PASS 가 diff 정독에 얹힌다 (26-08-05 hvami-mono 실측: doctor 가 "자동 감지 대상 없음" 을 냈다).
    `jvm_behavior_check` 는 사람이 적은 JVM 명령을 받아 주면서도 여기서는 한 줄도 내주지 않아,
    검증 레인과 감지 레인이 같은 저장소를 두고 다른 답을 들고 있었다.

    node 레인과 같은 보수 조건을 건다: ① 러너가 실재하고 ② 그 모듈에 테스트 소스가 있다.
    테스트가 0개인 모듈에서는 exit 0 이 설계상 보장돼, 아무것도 재지 않는 명령이 결정론 레인
    자리에 선다. Maven 은 로컬 저장소(`~/.m2/repository`)까지 요구한다 — 첫 실행의 의존성
    내려받기 실패는 exit 1 이라 테스트 실패와 구분되지 않아 false-red 로 게이트를 인질로 잡는다.

    모듈은 루트와 바로 아래 한 겹만 본다. 모노레포가 서비스마다 래퍼를 두는 형태이고
    (`hvami-batch/gradlew`), 더 깊이 내려가면 벤더링 트리의 래퍼까지 긁는다."""
    import shutil

    try:
        modules = [""] + sorted(
            name for name in os.listdir(root) if not name.startswith(".") and os.path.isdir(os.path.join(root, name))
        )
    except OSError:
        return []
    maven_ready = _maven_local_repo()
    checks: list[str] = []
    maven_usable: bool | None = None
    for module in modules:
        base = os.path.join(root, module)
        if not any(os.path.isdir(os.path.join(base, d)) for d in _JVM_TEST_DIRS):
            continue
        wrapper = os.path.join(base, "gradlew")
        if os.path.isfile(wrapper) and os.access(wrapper, os.X_OK):
            checks.append(f"{module + '/' if module else './'}gradlew test")
            continue
        pom = os.path.join(base, "pom.xml")
        if not (os.path.isfile(pom) and maven_ready and shutil.which("mvn") and _pom_runs_tests(pom)):
            continue
        if maven_usable is None:
            maven_usable = _runner_starts(["mvn", "-v"])
        if maven_usable:
            checks.append(f"mvn -q -f {module + '/' if module else ''}pom.xml test")
    return checks[:4]


# pom 이 테스트를 **돌린다**고 말하는 표식. 이름만 test 인 의존성(`spring-kafka-test` — 임베디드
# 브로커 유틸리티다)에 걸리지 않게 러너와 스코프만 본다.
_POM_TEST_MARKERS = ("junit", "testng", "maven-surefire-plugin", "<scope>test</scope>")


def _pom_runs_tests(pom: str) -> bool:
    """이 모듈이 테스트 러너를 선언했는가 — `src/test/java` 가 있다는 것과 다른 질문이다.

    26-08-05 실측(hvami-mono/kepco-fep): 테스트 소스 4개가 있는데 pom 에 JUnit 도 surefire 도
    없다. 그런 모듈에 `mvn test` 를 걸면 둘 중 하나다 — 도는 테스트가 0개인 **진공 green**,
    아니면 JUnit 임포트가 안 풀리는 컴파일 red. 앞은 아무것도 안 재면서 LLM 판정자를 대신하고,
    뒤는 코드가 멀쩡한데 게이트를 붙잡는다. 둘 다 이 레인이 없는 것만 못하다."""
    try:
        with open(pom, encoding="utf-8", errors="replace") as handle:
            text = handle.read(200_000).lower()
    except OSError:
        return False
    return any(marker in text for marker in _POM_TEST_MARKERS)


def _maven_local_repo() -> bool:
    """Maven 로컬 저장소가 이미 있는가 — node 레인의 `node_modules` 조건과 같은 자리다.

    첫 실행의 의존성 내려받기 실패는 exit 1 이라 테스트 실패와 구분되지 않아 false-red 로
    게이트를 인질로 잡는다. 이름 있는 함수로 뽑아 두는 이유는 시험이 이 사실을 **호스트에서
    빌려오지 않게** 하기 위해서다 — 이 기계에 `~/.m2` 가 있다는 이유로 초록인 시험은 CI 와
    컨테이너에서 빨개진다 (`_runner_starts` 와 같은 조회 지점)."""
    return os.path.isdir(os.path.join(os.path.expanduser("~"), ".m2", "repository"))


def _runner_starts(argv: list[str]) -> bool:
    """이 러너가 실제로 뜨는가 — PATH 에 이름이 있다는 것과 다른 질문이다.

    버전 관리자의 셰임은 이름은 내주고 실행은 거절한다 (26-08-05 실측: mise 의 `mvn` 셰임이
    "No version is set for shim" 과 함께 **exit 1** 을 냈다). 자동 감지가 그런 러너를 내주면
    `run_baseline` 은 1 을 테스트 실패로 읽어 red 를 세우고, 게이트는 멀쩡한 코드를 붙잡는다 —
    미설치를 뜻하는 127 과 달리 skip 으로도 안 빠진다.

    자동 감지 경로에서만, JVM 후보가 실제로 나왔을 때만 한 번 돈다 (pytest·node 는 앞에서
    끝난다). 5초를 못 넘기고, 못 판정하면 안 내준다 — 없는 레인이 거짓 red 보다 낫다."""
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=5)
    except Exception:
        return False
    return proc.returncode == 0


def _detect_node_checks(root: str) -> list[str]:
    """JS/TS 저장소의 행위 베이스라인 — package.json의 test 스크립트.

    자동감지가 pytest 전용이던 탓에 JS/TS 저장소는 `baseline_checks`를 손으로 넣지 않으면
    **하네스 실행 증거 레인이 통째로 꺼진 채** 돌았다 (26-07-26 helios 실측: PASS가 diff 정독과
    `node --check` 문법 검사에 얹혔다). 보수 조건 두 개를 함께 요구한다: ① 실제 test 스크립트가
    선언돼 있고 ② 의존성이 이미 설치돼 있다(node_modules). 미설치 상태의 러너 실패는 exit 1이라
    테스트 실패와 구분되지 않아 false-red로 게이트를 인질로 잡기 때문이다 — 그 경우는 명시 설정만."""
    import json as _json
    import shutil

    manifest = os.path.join(root, "package.json")
    if not os.path.exists(manifest) or not os.path.isdir(os.path.join(root, "node_modules")):
        return []
    try:
        with open(manifest, encoding="utf-8") as handle:
            scripts = (_json.load(handle) or {}).get("scripts") or {}
    except Exception:
        return []
    if not str(scripts.get("test") or "").strip():
        return []
    for lockfile, manager in (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("package-lock.json", "npm"),
        ("bun.lock", "npm"),
    ):
        if os.path.exists(os.path.join(root, lockfile)) and shutil.which(manager):
            return [f"{manager} test"]
    return ["npm test"] if shutil.which("npm") else []


def gate_first_checks_available(root: str, policy: dict) -> bool:
    """Only behavior test runners may replace an LLM Verifier; lint/compile/artifact checks may not.

    JVM 러너는 자동 감지(`_detect_jvm_checks`)로도 들어오고 사람이 `baseline_checks` 에 적어서도
    들어온다. 두 길이 모두 이 함수를 지나므로, 여기서 안 세면 Gradle·Maven 저장소는 감지가 되든
    설정을 하든 레인이 안 선다. 그 판정은 안전 표와 같은
    `jvm_behavior_check` 가 낸다 (두 자리가 갈리면 설정은 통과했는데 레인은 안 서는 상태가 된다)."""
    behavior = (
        ["npm", "test"],
        ["pnpm", "test"],
        ["yarn", "test"],
        ["cargo", "test"],
        ["go", "test"],
    )
    for command in detect_checks(root, policy):
        words = command.split()
        if "pytest" in words or words[:2] in behavior or jvm_behavior_check(command):
            return True
    return False
