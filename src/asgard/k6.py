"""asgard-k6 — 부하 시험 레인. 도커 k6 부트스트랩을 아스가르드가 소유한다.

지금까지 부하 시험은 떠돌이였다: `docker run --rm -i -v ...`를 손으로 치고, 스크립트마다
메트릭 이름이 다르고, 결과는 사람이 표로 옮겨 적었다. 그 상태의 문제는 느린 것이 아니라
**감사할 수 없다**는 것이다 — 어떤 이미지로 어떤 부하 형상을 걸어 나온 수치인지 기록이 없다.

이 모듈이 세우는 계약은 셋이다:

  러너    이미지·마운트·환경이 한 자리에서 조립된다 (`build_argv`, 순수 함수라 테스트가 본다).
  요약    모든 시나리오가 `asgard-k6-summary-v1` 한 모양으로 뱉는다 (`lib/asgard.js`).
  판정    임계값 결과와 프로세스 종료 코드를 **둘 다** 읽고 서로 어긋나면 그것을 사건으로 본다.

그리고 마지막 하나가 이 레인의 존재 이유다: `selftest()`. 부하 하네스는 자기가 틀렸을 때
조용히 틀린다 — 지연을 잘못 읽어도, 동시성을 안 걸어도, 임계값이 깨졌는데 통과로 보고해도
숫자는 그럴듯하게 나온다. 그래서 **거동을 미리 아는 표적**(`assets/k6_kit/pacer.py`)에
걸어 놓고 하네스가 참을 말하는지 대조한다. 이 검사가 녹색이 아니면 다른 어떤 부하 수치도
근거로 쓰면 안 된다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

SUMMARY_SCHEMA = "asgard-k6-summary-v1"
SUMMARY_NAME = "summary.json"
CONTAINER_MOUNT = "/asgard"
PROJECT = "asgard-k6"  # 컨테이너·compose 프로젝트·이미지 이름의 정본

# 레인이 프로젝트 안에서 쓰는 자리. 도커에 넘기는 호스트 경로는 **전부 여기 아래**다.
LANE_DIR = "k6"

# 우리가 굽는 이미지 (docker/asgard-k6/Dockerfile). 있으면 이것을 쓰고, 없으면 공개 이미지로
# 내려간다 — 자동으로 빌드하지는 않는다. 설치본에는 빌드 컨텍스트(src/)가 없고, 부하 측정
# 도중에 몇 분짜리 이미지 빌드가 끼어드는 것은 그 자체가 측정 방해다.
OWNED_IMAGE = PROJECT
DEFAULT_IMAGE = "grafana/k6:latest"

# k6는 임계값이 깨지면 이 코드로 끝난다. 실패(비정상 종료)와 판정(임계값 미달)은 다른 사건이다.
THRESHOLD_EXIT = 99

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ──────────────────────────────────────────────────────── 레인의 집 (프로젝트 기준)


def project_root(start: str | os.PathLike[str] | None = None) -> Path:
    """이 명령이 선 자리에서 **프로젝트**를 찾는다 — 볼륨의 집이 여기서 갈린다.

    현재 디렉터리를 그대로 프로젝트로 쓰면 `src/` 안에서 부른 실행이 거기에 `.asgard/`를
    새로 파고, 같은 프로젝트의 키트와 기록이 두 곳으로 갈라진다. 그래서 위로 걸어 표식을
    찾되 **가장 가까운 표식이 이긴다** — 표식 종류로 우선순위를 매기면 안 된다. 아스가르드는
    자격 증명을 `~/.asgard/`에 두므로, `.asgard`를 먼저 다 훑으면 홈 아래의 저장소가
    자기 `.git`을 지나쳐 홈을 프로젝트로 잡는다. 둘 다 없으면 선 자리가 프로젝트다."""
    here = Path(start or os.getcwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".asgard").is_dir() or (candidate / ".git").exists():
            return candidate
    return here


def lane_dir(root: str | os.PathLike[str]) -> Path:
    """`<프로젝트>/.asgard/k6` — 이 프로젝트에서 레인이 쓰는 모든 것의 집."""
    return Path(root) / ".asgard" / LANE_DIR


def mounted_kit_dir(root: str | os.PathLike[str]) -> Path:
    """도커에 `/asgard`로 넘어가는 **호스트 경로**. 설치 위치가 아니라 프로젝트 안이다."""
    return lane_dir(root) / "kit"


def runs_dir(root: str | os.PathLike[str]) -> Path:
    return lane_dir(root) / "runs"


def compose_out_dir(root: str | os.PathLike[str]) -> Path:
    """수동 compose 스택이 요약을 떨어뜨리는 자리 — CLI 경로(`runs/`)와 섞이지 않게 따로."""
    return lane_dir(root) / "out"


# ────────────────────────────────────────────────────────────── 키트와 시나리오


def kit_dir() -> Path:
    """설치본에 실려 오는 키트 경로 — 시나리오·라이브러리·기준 표적. **정본은 여기 하나다.**

    다만 이 경로를 도커에 그대로 넘기지는 않는다. 여기는 설치 접두사(휠이 풀린 자리)라
    기계마다 다르고 프로젝트마다 같다 — 볼륨의 집이 될 수 없다. 실제로 마운트되는 것은
    이 정본을 프로젝트 안으로 실체화한 `sync_kit()`의 산물이다.

    도커 산출물(Dockerfile·compose)은 `docker/asgard-k6/`에 따로 산다. 굽는 것과 실려 가는
    것을 갈라 둔 이유: 이미지는 저장소에서 만들고 관리하지만, 시나리오는 `uv tool install`
    한 사람의 기계에도 있어야 `asgard k6 run`이 선다."""
    return Path(str(files("asgard").joinpath("assets", "k6_kit")))


def pacer_script() -> Path:
    return kit_dir() / "pacer.py"


def docker_dir() -> Path | None:
    """`docker/asgard-k6/` — 이미지와 compose의 집. 저장소 체크아웃에서만 존재한다."""
    root = Path(__file__).resolve().parents[2]  # src/asgard/k6.py → 저장소 루트
    candidate = root / "docker" / PROJECT
    return candidate if (candidate / "Dockerfile").is_file() else None


def _kit_signature(source: Path) -> str:
    """키트 내용의 지문 — 판 번호가 아니라 **내용**으로 재동기화를 판단한다.

    버전으로 재면 개발 중 편집한 시나리오가 프로젝트에 안 내려가고, mtime으로 재면
    재설치 때마다 이유 없이 다시 복사한다."""
    digest = hashlib.sha256()
    for path in sorted(p for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(source).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def kit_is_synced(root: str | os.PathLike[str]) -> bool:
    """이 프로젝트에 실린 키트가 지금 배송본과 **같은가** — 두 트리를 직접 잰다.

    기록해 둔 지문과 배송본만 대조하면 실린 쪽이 바뀐 것을 못 본다. 그러면 누군가
    `.asgard/k6/kit/` 안을 고쳐도 레인은 "배송본과 같다"고 말하고, 컨테이너는 고쳐진
    키트를 돈다 — `/asgard`를 읽기 전용으로 거는 이유(시나리오가 자기 정의를 못 고친다)가
    호스트 쪽에서 새는 것이다. 그래서 양쪽을 다 잰다."""
    target = mounted_kit_dir(root)
    if not target.is_dir():
        return False
    try:
        return _kit_signature(target) == _kit_signature(kit_dir())
    except OSError:
        return False


def sync_kit(root: str | os.PathLike[str], *, force: bool = False) -> Path:
    """배송된 키트를 **이 프로젝트의 `.asgard/k6/kit/`**에 실체화하고 그 경로를 준다.

    왜 설치 위치를 바로 마운트하지 않나: 그 경로는 프로젝트의 것이 아니다. `uv tool install`
    한 기계에서는 도구 venv 안(공유 접두사)이고, 체크아웃에서는 `src/` 아래이며, 도커 데스크톱이
    공유하지 않는 자리일 수도 있다. 하나의 설치본을 여러 프로젝트가 함께 쓰는 이상 "지금 이
    실행이 어떤 키트를 마운트했나"도 프로젝트 밖에서 정해진다. 프로젝트 안으로 내려 두면
    그 답이 파일로 남고, 수동 compose 경로도 같은 실물을 본다.

    재동기화는 내용 지문으로 판단한다 — 같으면 손대지 않으므로 매 실행 호출해도 싸다."""
    source = kit_dir()
    target = mounted_kit_dir(root)
    if not force and kit_is_synced(root):
        return target

    # 덮어 쓰지 않고 통째로 갈아 끼운다: 이전 판에서 사라진 시나리오가 그대로 살아남거나,
    # 반쯤 복사된 키트로 부하를 재는 사고를 막는다.
    staging = target.parent / f".kit-staging-{os.getpid()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.rmtree(target, ignore_errors=True)
        staging.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target


def prepare_lane(root: str | os.PathLike[str], *, force: bool = False) -> Path:
    """실행 전에 레인의 자리를 세운다 — 마운트 원본(kit)과 산출 자리(runs·out)."""
    kit = sync_kit(root, force=force)
    runs_dir(root).mkdir(parents=True, exist_ok=True)
    compose_out_dir(root).mkdir(parents=True, exist_ok=True)
    return kit


@dataclass(frozen=True)
class Scenario:
    name: str
    path: Path
    origin: str  # "builtin" | "project"


def builtin_scenarios() -> dict[str, Scenario]:
    out: dict[str, Scenario] = {}
    root = kit_dir() / "scenarios"
    if root.is_dir():
        for path in sorted(root.glob("*.js")):
            out[path.stem] = Scenario(path.stem, path, "builtin")
    return out


def project_scenarios(root: str | os.PathLike[str]) -> dict[str, Scenario]:
    """프로젝트가 직접 쓴 시나리오. 같은 이름이면 프로젝트가 이긴다.

    자리는 `.asgard/k6/scenarios/*.js` 다. 레인 바로 밑(`.asgard/k6/*.js`)도 계속 잡히지만
    — 이전에 거기 둔 것을 깨지 않는다 — 새로 쓰는 것은 `scenarios/`로 간다: 레인 밑은
    이제 키트·기록·산출이 함께 사는 자리라, 시나리오 하나를 컨테이너에 넣으려고 그 전부를
    읽기 전용으로 끌고 들어가게 된다."""
    out: dict[str, Scenario] = {}
    lane = lane_dir(root)
    for base in (lane, lane / "scenarios"):  # 뒤가 이긴다 — 명시적인 자리가 정본
        if base.is_dir():
            for path in sorted(base.glob("*.js")):
                out[path.stem] = Scenario(path.stem, path, "project")
    return out


def scenarios(root: str | os.PathLike[str] | None = None) -> dict[str, Scenario]:
    merged = builtin_scenarios()
    if root is not None:
        merged.update(project_scenarios(root))
    return merged


def find_scenario(name: str, root: str | os.PathLike[str] | None = None) -> Scenario | None:
    """이름 또는 파일 경로로 시나리오 찾기 — 경로가 주어지면 그 파일이 정본이다."""
    candidate = Path(name)
    if candidate.suffix == ".js" and candidate.is_file():
        return Scenario(candidate.stem, candidate.resolve(), "project")
    return scenarios(root).get(name)


# ─────────────────────────────────────────────────────────────────────── 러너


@dataclass(frozen=True)
class Runner:
    kind: str  # "docker" | "podman" | "native"
    binary: str
    image: str = ""

    @property
    def containerized(self) -> bool:
        return self.kind in ("docker", "podman")

    def label(self) -> str:
        return f"{self.kind} ({self.image})" if self.containerized else f"{self.kind} k6"


def owned_image_tags() -> list[str]:
    """우리가 굽는 이미지의 후보 태그 — 버전 태그가 먼저, 개발용 `:local`이 다음."""
    from . import __version__

    return [f"{OWNED_IMAGE}:{__version__}", f"{OWNED_IMAGE}:local"]


def default_image() -> str:
    """환경이 고정한 이미지, 아니면 공개 k6. 여기는 엔진을 안 부르는 순수 폴백이다."""
    return os.environ.get("ASGARD_K6_IMAGE") or DEFAULT_IMAGE


def resolve_image(engine_binary: str = "") -> str:
    """실제로 쓸 이미지. `ASGARD_K6_IMAGE` → 로컬에 구워진 `asgard-k6:*` → 공개 k6.

    우리 이미지를 자동으로 빌드하지는 않는다. 설치본에는 빌드 컨텍스트가 없고, 부하를 재려던
    명령이 몇 분짜리 이미지 빌드로 바뀌는 것은 그 자체가 측정 방해다 — `asgard k6 doctor`가
    지금 어느 이미지인지와 굽는 한 줄을 말해 준다."""
    pinned = os.environ.get("ASGARD_K6_IMAGE")
    if pinned:
        return pinned
    if engine_binary:
        for tag in owned_image_tags():
            probe = subprocess.run(
                [engine_binary, "image", "inspect", tag],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if probe.returncode == 0:
                return tag
    return DEFAULT_IMAGE


def resolve_runner(prefer: str = "") -> Runner | None:
    """컨테이너 우선, 없으면 네이티브 k6. `ASGARD_K6_RUNNER`로 고정할 수 있다.

    도커를 먼저 보는 이유는 취향이 아니다 — 이미지가 고정되면 같은 부하 형상이 다른
    기계에서도 같은 도구로 돌아간다. 네이티브 k6는 판이 사람마다 다르다."""
    prefer = (prefer or os.environ.get("ASGARD_K6_RUNNER") or "").strip().lower()
    if prefer == "native":
        binary = shutil.which("k6")
        return Runner("native", binary) if binary else None
    if prefer in ("docker", "podman"):
        binary = shutil.which(prefer)
        return Runner(prefer, binary, resolve_image(binary)) if binary else None
    for engine in ("docker", "podman"):
        binary = shutil.which(engine)
        if binary:
            return Runner(engine, binary, resolve_image(binary))
    binary = shutil.which("k6")
    return Runner("native", binary) if binary else None


def runner_version(runner: Runner, timeout: float = 60.0) -> str:
    """이 실행이 어느 k6 였는지 — 보고서에 새겨질 값."""
    argv = (
        [runner.binary, "version"]
        if not runner.containerized
        else [runner.binary, "run", "--rm", "--entrypoint", "k6", runner.image, "version"]
    )
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False
        )
    except OSError, subprocess.SubprocessError:
        return ""
    line = (done.stdout or done.stderr or "").strip().splitlines()
    return line[0].strip() if line else ""


def engine_available() -> bool:
    return resolve_runner() is not None


# ────────────────────────────────────────────────────────────── 명령 조립 (순수)


def _validate_env(env: dict[str, str]) -> None:
    for key in env:
        if not _ENV_RE.match(key):
            raise ValueError(f"환경 변수 이름이 올바르지 않다: {key!r}")


def build_argv(
    runner: Runner,
    scenario: Scenario,
    out_dir: str | os.PathLike[str],
    env: dict[str, str] | None = None,
    *,
    quiet: bool = True,
    container_name: str = "",
    kit: str | os.PathLike[str] | None = None,
) -> list[str]:
    """러너·시나리오·환경 → 실제로 실행될 argv. 순수 함수 — 테스트가 여기를 본다.

    컨테이너 마운트 배치:
      키트   `/asgard`      읽기 전용 (시나리오가 자기 정의를 못 고친다)
      요약   `/asgard/out`  쓰기 가능 (여기 하나만)
      프로젝트 시나리오는 `/asgard/project`로 따로 들어온다 — 그래야 `../lib/asgard.js`
      상대 임포트가 키트 라이브러리로 정확히 떨어진다.

    `kit`은 `/asgard`로 들어갈 **호스트 경로**다. 부르는 쪽이 `sync_kit()`으로 프로젝트
    안에 세운 자리를 넘긴다 — 안 넘기면 설치 접두사를 마운트하게 되고, 그것은 프로젝트의
    것이 아니다. 기본값을 배송 경로로 둔 것은 러너 없이 조립만 보는 자리(테스트) 때문이다.
    """
    env = dict(env or {})
    _validate_env(env)
    out_dir = Path(out_dir)
    kit_source = Path(kit) if kit is not None else kit_dir()

    if not runner.containerized:
        merged = {**env, "ASGARD_K6_OUT": str(out_dir / SUMMARY_NAME)}
        argv = [runner.binary, "run"]
        if quiet:
            argv.append("--quiet")
        for key, value in merged.items():
            argv += ["-e", f"{key}={value}"]
        argv.append(str(scenario.path))
        return argv

    name = container_name or f"{PROJECT}-{os.getpid()}"
    if not _NAME_RE.match(name):
        raise ValueError(f"컨테이너 이름이 올바르지 않다: {name!r}")
    argv = [
        runner.binary,
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--label",
        f"com.asgard.lane={PROJECT}",
        # 호스트에서 도는 표적을 컨테이너 안에서 부를 수 있게 — 리눅스에서도 같은 이름이 선다.
        "--add-host=host.docker.internal:host-gateway",
        "-v",
        f"{kit_source}:{CONTAINER_MOUNT}:ro",
        "-v",
        f"{out_dir}:{CONTAINER_MOUNT}/out",
    ]
    if scenario.origin == "project":
        argv += ["-v", f"{scenario.path.parent}:{CONTAINER_MOUNT}/project:ro"]
        script = f"{CONTAINER_MOUNT}/project/{scenario.path.name}"
    else:
        script = f"{CONTAINER_MOUNT}/scenarios/{scenario.path.name}"
    merged = {**env, "ASGARD_K6_OUT": f"{CONTAINER_MOUNT}/out/{SUMMARY_NAME}"}
    for key, value in merged.items():
        argv += ["-e", f"{key}={value}"]
    argv.append(runner.image)
    argv.append("run")
    if quiet:
        argv.append("--quiet")
    argv.append(script)
    return argv


def container_target(runner: Runner, port: int) -> str:
    """러너 자리에서 본 호스트 표적 주소 — 컨테이너 안과 밖은 이름이 다르다."""
    host = "host.docker.internal" if runner.containerized else "127.0.0.1"
    return f"http://{host}:{port}"


def bind_host(runner: Runner) -> str:
    """pacer가 열어야 하는 주소. 컨테이너에서 부르려면 루프백만으로는 안 닿는다 —
    필요할 때만 넓히고, 네이티브 러너면 루프백에 묶어 둔다."""
    return "0.0.0.0" if runner.containerized else "127.0.0.1"  # noqa: S104 - 컨테이너 러너 전용


# ───────────────────────────────────────────────────────────────── 요약 파싱


@dataclass(frozen=True)
class Threshold:
    metric: str
    expression: str
    ok: bool


@dataclass
class Report:
    scenario: str = ""
    target: str = ""
    runner: str = ""
    k6_version: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    requests: int = 0
    failed: int = 0
    failed_rate: float = 0.0
    rate_per_s: float = 0.0
    latency_ms: dict[str, float] = field(default_factory=dict)
    iterations: int = 0
    vus_max: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    thresholds: list[Threshold] = field(default_factory=list)
    custom: dict[str, dict] = field(default_factory=dict)
    stderr: str = ""
    summary_path: str = ""

    @property
    def thresholds_ok(self) -> bool:
        return all(row.ok for row in self.thresholds)

    @property
    def ok(self) -> bool:
        """통과 = 임계값 전부 충족 + 프로세스가 정상으로 끝남."""
        return self.thresholds_ok and self.exit_code == 0

    @property
    def exit_agrees(self) -> bool:
        """종료 코드와 임계값 판정이 같은 이야기를 하는가.

        어긋나면 둘 중 하나가 거짓말이다 — 임계값이 깨졌는데 0으로 끝나면 CI가 빨간 것을
        초록으로 통과시키고, 반대면 멀쩡한 실행이 파이프라인을 세운다."""
        breached = not self.thresholds_ok
        return breached == (self.exit_code == THRESHOLD_EXIT) if self.exit_code in (0, THRESHOLD_EXIT) else True

    def as_dict(self) -> dict:
        return {
            "schema": SUMMARY_SCHEMA,
            "scenario": self.scenario,
            "target": self.target,
            "runner": self.runner,
            "k6_version": self.k6_version,
            "exit_code": self.exit_code,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "requests": {
                "count": self.requests,
                "failed": self.failed,
                "failed_rate": self.failed_rate,
                "rate_per_s": self.rate_per_s,
            },
            "latency_ms": self.latency_ms,
            "iterations": self.iterations,
            "vus_max": self.vus_max,
            "checks": {"passes": self.checks_passed, "fails": self.checks_failed},
            "thresholds": [{"metric": t.metric, "expression": t.expression, "ok": t.ok} for t in self.thresholds],
            "custom": self.custom,
        }


class SummaryError(ValueError):
    """요약이 계약을 안 지켰다 — 이 실행의 수치는 근거로 쓸 수 없다."""


def parse_summary(payload: dict, *, exit_code: int = 0, runner: str = "", k6_version: str = "") -> Report:
    """`asgard-k6-summary-v1` → Report. 모양이 다르면 조용히 0을 채우지 않고 거절한다."""
    if not isinstance(payload, dict):
        raise SummaryError("요약이 JSON 객체가 아니다")
    schema = payload.get("schema")
    if schema != SUMMARY_SCHEMA:
        raise SummaryError(f"요약 스키마가 다르다: {schema!r} (기대: {SUMMARY_SCHEMA})")
    reqs = payload.get("requests") or {}
    checks = payload.get("checks") or {}
    thresholds = [
        Threshold(str(row.get("metric", "")), str(row.get("expression", "")), bool(row.get("ok")))
        for row in payload.get("thresholds") or []
        if isinstance(row, dict)
    ]
    return Report(
        scenario=str(payload.get("scenario") or ""),
        target=str(payload.get("target") or ""),
        runner=runner,
        k6_version=k6_version,
        exit_code=exit_code,
        duration_ms=float(payload.get("duration_ms") or 0.0),
        requests=int(reqs.get("count") or 0),
        failed=int(reqs.get("failed") or 0),
        failed_rate=float(reqs.get("failed_rate") or 0.0),
        rate_per_s=float(reqs.get("rate_per_s") or 0.0),
        latency_ms={k: float(v) for k, v in (payload.get("latency_ms") or {}).items()},
        iterations=int(payload.get("iterations") or 0),
        vus_max=int(payload.get("vus_max") or 0),
        checks_passed=int(checks.get("passes") or 0),
        checks_failed=int(checks.get("fails") or 0),
        thresholds=thresholds,
        custom=dict(payload.get("custom") or {}),
    )


# ────────────────────────────────────────────────────────────────────── 실행


def run_scenario(
    scenario: Scenario,
    *,
    runner: Runner,
    out_dir: str | os.PathLike[str],
    env: dict[str, str] | None = None,
    kit: str | os.PathLike[str] | None = None,
    timeout: float = 1800.0,
    quiet: bool = True,
    stream: bool = False,
    k6_version: str = "",
) -> Report:
    """시나리오 하나를 돌리고 요약을 회수한다. `kit`은 `/asgard`로 갈 호스트 경로다."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if runner.containerized:
        # 컨테이너 안의 k6는 비루트로 돌고 그 uid는 호스트에서 모른다 — 요약을 못 쓰면
        # 실행 전체가 버려진다. 넓히는 자리는 이 실행의 산출 디렉터리 하나뿐이고,
        # 네이티브 러너는 호스트 사용자 그대로라 여기 오지 않는다.
        try:
            out.chmod(0o777)
        except OSError:
            pass
    summary_path = out / SUMMARY_NAME
    if summary_path.exists():
        summary_path.unlink()  # 이전 실행의 요약을 이번 결과로 읽는 사고를 막는다

    argv = build_argv(runner, scenario, out, env, quiet=quiet, kit=kit)
    try:
        done = subprocess.run(
            argv,
            capture_output=not stream,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SummaryError(f"부하 실행이 {timeout:.0f}s 안에 끝나지 않았다") from exc
    except OSError as exc:
        raise SummaryError(f"러너를 실행할 수 없다: {exc}") from exc

    if not summary_path.is_file():
        tail = ((done.stderr or "") + (done.stdout or ""))[-2000:] if not stream else ""
        raise SummaryError(
            "요약 파일이 나오지 않았다 — 시나리오가 handleSummary를 export 하지 않았거나 "
            f"실행이 시작 전에 죽었다 (exit {done.returncode}).\n{tail}"
        )
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SummaryError(f"요약을 읽을 수 없다: {exc}") from exc

    report = parse_summary(payload, exit_code=done.returncode, runner=runner.label(), k6_version=k6_version)
    report.summary_path = str(summary_path)
    if not stream:
        report.stderr = (done.stderr or "")[-4000:]
    return report


# ──────────────────────────────────────────────────────────── pacer (표적)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Pacer:
    """거동을 아는 표적을 호스트에서 띄우고 붙든다 (context manager)."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        latency_ms: float = 80.0,
        error_rate: float = 0.0,
        max_concurrency: int = 0,
    ) -> None:
        self.host = host
        self.port = port or free_port()
        self.latency_ms = latency_ms
        self.error_rate = error_rate
        self.max_concurrency = max_concurrency
        self.proc: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "Pacer":
        self.proc = subprocess.Popen(
            [
                sys.executable,
                str(pacer_script()),
                f"--host={self.host}",
                f"--port={self.port}",
                f"--latency-ms={self.latency_ms}",
                f"--error-rate={self.error_rate}",
                f"--max-concurrency={self.max_concurrency}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if self.proc.poll() is not None:
                err = (self.proc.stderr.read() if self.proc.stderr else "") or ""
                raise SummaryError(f"pacer가 뜨지 못했다: {err.strip()[:400]}")
            try:
                with urllib.request.urlopen(f"{self.url}/health", timeout=1) as resp:
                    if resp.status == 200:
                        return self
            except urllib.error.URLError, OSError:
                time.sleep(0.1)
        self.stop()
        raise SummaryError("pacer가 15s 안에 응답하지 않았다")

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def stats(self) -> dict:
        with urllib.request.urlopen(f"{self.url}/stats", timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))


# ───────────────────────────────────────────────────── 정합성 검사 (selftest)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    expected: str
    observed: str
    detail: str = ""


@dataclass
class Selftest:
    checks: list[Check] = field(default_factory=list)
    runner: str = ""
    k6_version: str = ""
    reports: dict[str, Report] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks) and not self.error

    def as_dict(self) -> dict:
        return {
            "schema": "asgard-k6-selftest-v1",
            "ok": self.ok,
            "runner": self.runner,
            "k6_version": self.k6_version,
            "error": self.error,
            "checks": [
                {"name": c.name, "ok": c.ok, "expected": c.expected, "observed": c.observed, "detail": c.detail}
                for c in self.checks
            ],
        }


def _check(name: str, ok: bool, expected: object, observed: object, detail: str = "") -> Check:
    return Check(name, bool(ok), str(expected), str(observed), detail)


def selftest(
    *,
    runner: Runner | None = None,
    out_dir: str | os.PathLike[str],
    kit: str | os.PathLike[str] | None = None,
    latency_ms: float = 80.0,
    iterations: int = 40,
    vus: int = 4,
    timeout: float = 300.0,
) -> Selftest:
    """하네스가 참을 말하는지 검사한다 — 표적의 정답을 미리 알고 대조한다.

    세 판을 돈다:
      truth      상한 없는 표적. 건수·지연·동시성이 설정과 맞는지, 관대한 임계값이 통과하는지.
      gate       같은 표적에 **깨질 수밖에 없는** 임계값. 게이트가 실제로 떨어지는지, 그리고
                 주기적 오류 주입이 보고서에 정확한 건수로 남는지.
      saturate   동시성 상한이 걸린 표적. 부하 생성기가 실제로 줄을 세웠는지 (Little's law).

    검사 하나라도 빨간 채로 얻은 부하 수치는 근거가 아니다.
    """
    runner = runner or resolve_runner()
    result = Selftest()
    if runner is None:
        result.error = "러너가 없다 — docker/podman 또는 k6가 필요하다"
        return result
    result.runner = runner.label()
    result.k6_version = runner_version(runner)
    out_root = Path(out_dir)
    host = bind_host(runner)
    # 프로젝트가 같은 이름의 시나리오를 두고 있어도 자기검증은 **내장본**으로 돈다 —
    # 하네스를 검사하는 자가 검사 대상과 같이 흔들리면 검사가 아니다.
    probe = Scenario("selftest", kit_dir() / "scenarios" / "selftest.js", "builtin")

    # ── 1판 truth — 정답을 아는 표적에 관대한 임계값
    try:
        with Pacer(host=host, latency_ms=latency_ms) as pacer:
            report = run_scenario(
                probe,
                runner=runner,
                out_dir=out_root / "truth",
                kit=kit,
                env={
                    "ASGARD_K6_TARGET": container_target(runner, pacer.port),
                    "ASGARD_K6_ITERATIONS": str(iterations),
                    "ASGARD_K6_VUS": str(vus),
                    "ASGARD_K6_P95_MAX": str(latency_ms * 20 + 2000),
                    "ASGARD_K6_FAIL_MAX": "0.01",
                },
                timeout=timeout,
                k6_version=result.k6_version,
            )
            stats = pacer.stats()
        result.reports["truth"] = report

        result.checks.append(
            _check("summary-schema", True, SUMMARY_SCHEMA, SUMMARY_SCHEMA, "요약이 정본 스키마로 파싱됐다")
        )
        result.checks.append(
            _check(
                "request-count",
                report.requests == iterations,
                iterations,
                report.requests,
                "고정 반복인데 보고된 요청 수가 다르면 요약이 다른 메트릭을 읽고 있다",
            )
        )
        served = int(stats.get("requests") or 0)
        result.checks.append(
            _check(
                "server-parity",
                served == report.requests,
                f"server {report.requests}",
                f"server {served}",
                "표적이 센 건수와 하네스가 센 건수 — 어긋나면 한쪽이 요청을 흘렸다",
            )
        )
        med = report.latency_ms.get("med", 0.0)
        lower, upper = latency_ms * 0.9, latency_ms + 150.0
        result.checks.append(
            _check(
                "latency-truth",
                lower <= med <= upper,
                f"{lower:.0f}~{upper:.0f}ms",
                f"med {med:.1f}ms",
                f"표적이 정확히 {latency_ms:.0f}ms를 잔다 — 보고된 중앙값이 그 값이어야 한다",
            )
        )
        peak = int(stats.get("peak_in_flight") or 0)
        result.checks.append(
            _check(
                "concurrency-applied",
                peak == vus,
                f"peak {vus}",
                f"peak {peak}",
                "상한 없는 표적에서 동시 처리 정점이 VU 수와 같아야 한다 — 작으면 직렬로 돈 것이다",
            )
        )
        result.checks.append(
            _check(
                "threshold-passes-when-met",
                report.thresholds_ok and report.exit_code == 0,
                "thresholds ok · exit 0",
                f"thresholds {'ok' if report.thresholds_ok else 'FAIL'} · exit {report.exit_code}",
                "충족되는 임계값은 통과해야 한다",
            )
        )
        result.checks.append(
            _check(
                "exit-parity-pass",
                report.exit_agrees,
                "exit code == threshold verdict",
                f"exit {report.exit_code} · thresholds {'ok' if report.thresholds_ok else 'FAIL'}",
            )
        )
    except (SummaryError, OSError) as exc:
        result.error = f"truth 판이 끝나지 못했다: {exc}"
        return result

    # ── 2판 gate — 깨질 수밖에 없는 임계값 + 주기적 오류 주입
    error_rate = 0.25
    try:
        with Pacer(host=host, latency_ms=latency_ms, error_rate=error_rate) as pacer:
            report = run_scenario(
                probe,
                runner=runner,
                out_dir=out_root / "gate",
                kit=kit,
                env={
                    "ASGARD_K6_TARGET": container_target(runner, pacer.port),
                    "ASGARD_K6_ITERATIONS": str(iterations),
                    "ASGARD_K6_VUS": str(vus),
                    # 표적이 확실히 못 지키는 값 — 게이트가 떨어져야 정상이다
                    "ASGARD_K6_P95_MAX": str(max(1.0, latency_ms / 8)),
                    "ASGARD_K6_FAIL_MAX": "0.01",
                },
                timeout=timeout,
                k6_version=result.k6_version,
            )
            stats = pacer.stats()
        result.reports["gate"] = report

        result.checks.append(
            _check(
                "threshold-fails-when-breached",
                not report.thresholds_ok,
                "thresholds FAIL",
                f"thresholds {'ok' if report.thresholds_ok else 'FAIL'}",
                "안 떨어지는 게이트는 장식이다 — 지킬 수 없는 임계값은 반드시 깨져야 한다",
            )
        )
        result.checks.append(
            _check(
                "exit-code-on-breach",
                report.exit_code == THRESHOLD_EXIT,
                f"exit {THRESHOLD_EXIT}",
                f"exit {report.exit_code}",
                "임계값 미달은 종료 코드로도 나와야 CI가 잡는다",
            )
        )
        expected_failures = int(iterations * error_rate)
        result.checks.append(
            _check(
                "error-accounting",
                report.failed == expected_failures,
                f"{expected_failures} failed",
                f"{report.failed} failed",
                "표적의 실패는 확률이 아니라 주기다 — 건수가 정확히 맞아야 한다",
            )
        )
        served_errors = int(stats.get("errored") or 0)
        result.checks.append(
            _check(
                "error-parity",
                served_errors == report.failed,
                f"server {report.failed}",
                f"server {served_errors}",
                "표적이 낸 5xx와 하네스가 센 실패가 같아야 한다",
            )
        )
    except (SummaryError, OSError) as exc:
        result.error = f"gate 판이 끝나지 못했다: {exc}"
        return result

    # ── 3판 saturate — 동시성 상한이 걸린 표적 (부하 생성기가 실제로 줄을 세웠는가)
    cap = max(1, vus // 2)
    try:
        with Pacer(host=host, latency_ms=latency_ms, max_concurrency=cap) as pacer:
            report = run_scenario(
                probe,
                runner=runner,
                out_dir=out_root / "saturate",
                kit=kit,
                env={
                    "ASGARD_K6_TARGET": container_target(runner, pacer.port),
                    "ASGARD_K6_ITERATIONS": str(iterations),
                    "ASGARD_K6_VUS": str(vus),
                    "ASGARD_K6_P95_MAX": str(latency_ms * 30 + 3000),
                    "ASGARD_K6_FAIL_MAX": "0.01",
                },
                timeout=timeout,
                k6_version=result.k6_version,
            )
            stats = pacer.stats()
        result.reports["saturate"] = report

        peak = int(stats.get("peak_in_flight") or 0)
        result.checks.append(
            _check(
                "queue-cap-respected",
                peak <= cap,
                f"peak <= {cap}",
                f"peak {peak}",
                "상한을 건 표적에서 동시 처리 정점이 상한을 넘으면 표적 쪽 게이트가 샌 것이다",
            )
        )
        ceiling = float(stats.get("throughput_ceiling_rps") or 0.0)
        observed = report.rate_per_s
        # 천장의 절반 아래면 부하 생성기가 상한만큼도 못 채웠다는 뜻 — 위쪽은 물리적으로 못 넘는다.
        result.checks.append(
            _check(
                "throughput-ceiling",
                bool(ceiling) and (ceiling * 0.5) <= observed <= (ceiling * 1.2),
                f"{ceiling * 0.5:.1f}~{ceiling * 1.2:.1f} req/s",
                f"{observed:.1f} req/s",
                f"상한 {cap} ÷ 서비스 시간 {latency_ms:.0f}ms = 이론 천장 {ceiling:.1f} req/s (Little's law)",
            )
        )
    except (SummaryError, OSError) as exc:
        result.error = f"saturate 판이 끝나지 못했다: {exc}"
        return result

    return result


# ─────────────────────────────────────────────────────────────────── 기록


def record_run(root: str | os.PathLike[str], report: Report, stamp: str) -> Path:
    """실행 결과를 프로젝트에 남긴다 — 부하 수치는 기억이 아니라 파일이어야 재현을 논한다."""
    target = runs_dir(root) / stamp
    target.mkdir(parents=True, exist_ok=True)
    path = target / "report.json"
    path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
