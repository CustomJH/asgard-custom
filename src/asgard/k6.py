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
import itertools
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import tomllib
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

# 우리 표면의 종료 코드. 미달(1)과 **판정 자체가 없었음**(3)을 가른다 — CI 가 둘을 같은 초록으로
# 삼키면, 임계값을 안 적은 시나리오가 아무리 죽어도 파이프라인은 통과한다.
UNJUDGED_EXIT = 3

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ──────────────────────────────────────────────────────── 레인의 집 (프로젝트 기준)


def project_root(start: str | os.PathLike[str] | None = None) -> Path:
    """이 명령이 선 자리에서 **프로젝트**를 찾는다 — 볼륨의 집이 여기서 갈린다.

    현재 디렉터리를 그대로 프로젝트로 쓰면 `src/` 안에서 부른 실행이 거기에 `.asgard/`를
    새로 파고, 같은 프로젝트의 키트와 기록이 두 곳으로 갈라진다. 그래서 위로 걸어 표식을
    찾되 **가장 가까운 표식이 우선한다** — 표식 종류로 우선순위를 매기면 안 된다. 아스가르드는
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
    한 사람의 기계에도 있어야 `asgard k6 run`이 동작한다."""
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


_SYNC_SEQ = itertools.count(1)
# 키트 교체는 한 번에 하나만. 이름을 갈라도 `target` 자리는 하나라, 두 스레드가 동시에
# 갈아 끼우면 뒤엣것이 앞엣것의 자리를 못 찾는다.
_SYNC_LOCK = threading.Lock()


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
    with _SYNC_LOCK:
        if not force and kit_is_synced(root):
            return target  # 기다리는 사이에 옆 스레드가 다 맞춰 놓았다
        return _swap_kit(source, target)


def _swap_kit(source: Path, target: Path) -> Path:
    # 덮어 쓰지 않고 통째로 갈아 끼운다: 이전 판에서 사라진 시나리오가 그대로 살아남거나,
    # 반쯤 복사된 키트로 부하를 재는 사고를 막는다.
    #
    # 갈아 끼우는 순서가 중요하다. 예전에는 새 키트를 세운 **뒤 옛것을 지우고** 옮겼는데,
    # 그 사이(지운 직후 ~ 옮기기 직전)에 실패하면 실린 키트가 통째로 사라진 채 남았다. 이제
    # 옛것은 지우지 않고 옆으로 밀어 두고, 새것이 제자리에 앉은 것을 본 뒤에 버린다 — 실패해도
    # 되돌릴 것이 손에 있다.
    # 임시 이름에 프로세스만 넣으면 **한 프로세스 안의 두 스레드**가 같은 자리를 쓴다(창은
    # 부하를 뒤에서 돌린다). 한쪽이 staging 을 지우는 사이 다른 쪽이 거기로 복사하면 키트가
    # 반쯤 앉고, retired 가 겹치면 쓰던 키트가 통째로 사라진다. 스레드와 일련번호까지 넣는다.
    tag = f"{os.getpid()}-{threading.get_ident()}-{next(_SYNC_SEQ)}"
    staging = target.parent / f".kit-staging-{tag}"
    retired = target.parent / f".kit-retired-{tag}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(retired, ignore_errors=True)
    try:
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        moved = False
        if target.exists():
            target.replace(retired)
            moved = True
        try:
            staging.replace(target)
        except OSError:
            if moved:
                retired.replace(target)  # 새것이 못 앉았으면 쓰던 것을 그대로 돌려놓는다
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(retired, ignore_errors=True)
    return target


def expose_lib(root: str | os.PathLike[str]) -> Path:
    """프로젝트 시나리오가 `../lib/asgard.js` 로 닿을 자리를 레인에 세운다.

    시나리오 계약은 `import { summarize } from '../lib/asgard.js'` 한 줄이고, 컨테이너에서는
    그것이 맞는다: 키트가 `/asgard` 로, 시나리오가 `/asgard/project/x.js` 로 들어오므로
    `../lib` 가 정확히 키트 라이브러리다. 그런데 **네이티브 러너에서는 같은 파일이 호스트
    경로 그대로 돈다** — `<레인>/scenarios/x.js` 의 `../lib` 는 `<레인>/lib` 이고, 키트는
    `<레인>/kit/lib` 에 있으므로 아무것도 없다. 그래서 도커로는 도는 프로젝트 시나리오가
    네이티브로는 모듈을 못 찾고 죽었다(실측: `moduleSpecifier "../lib/asgard.js" couldn't be
    found on local disk`). 같은 시나리오가 러너에 따라 다르게 도는 것은 레인의 계약이 아니다.

    심볼릭 링크를 먼저 시도한다 — 키트를 다시 맞출 때 따라 움직이기 때문이다. 링크를 못 만드는
    자리(권한 없는 윈도우)에서는 복사로 내려간다."""
    lane = lane_dir(root)
    source = mounted_kit_dir(root) / "lib"
    target = lane / "lib"
    if not source.is_dir():
        return target
    if target.is_symlink():
        if target.resolve() == source.resolve():
            return target
        target.unlink()
    elif target.is_dir():
        if _kit_signature(target) == _kit_signature(source):
            return target
        shutil.rmtree(target, ignore_errors=True)
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError, NotImplementedError:
        shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def prepare_lane(root: str | os.PathLike[str], *, force: bool = False) -> Path:
    """실행 전에 레인의 자리를 세운다 — 마운트 원본(kit)과 산출 자리(runs·out)."""
    kit = sync_kit(root, force=force)
    runs_dir(root).mkdir(parents=True, exist_ok=True)
    compose_out_dir(root).mkdir(parents=True, exist_ok=True)
    expose_lib(root)
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
    """프로젝트가 직접 쓴 시나리오. 같은 이름이면 프로젝트가 우선한다.

    자리는 `.asgard/k6/scenarios/*.js` 다. 레인 바로 밑(`.asgard/k6/*.js`)도 계속 잡히지만
    — 이전에 거기 둔 것을 깨지 않는다 — 새로 쓰는 것은 `scenarios/`로 간다: 레인 밑은
    이제 키트·기록·산출이 함께 있는 자리라, 시나리오 하나를 컨테이너에 넣으려고 그 전부를
    읽기 전용으로 끌고 들어가게 된다."""
    out: dict[str, Scenario] = {}
    lane = lane_dir(root)
    for base in (lane, lane / "scenarios"):  # 뒤가 우선한다 — 명시적인 자리가 정본
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
            raise ValueError(f"환경 변수 이름이 올바르지 않아요: {key!r}")


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
        raise ValueError(f"컨테이너 이름이 올바르지 않아요: {name!r}")
    argv = [
        runner.binary,
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--label",
        f"com.asgard.lane={PROJECT}",
        # 호스트에서 도는 표적을 컨테이너 안에서 부를 수 있게 — 리눅스에서도 같은 이름이 통한다.
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
    def judged(self) -> bool:
        """이 실행에 **판정할 것이 있었는가** — 시나리오가 임계값을 하나라도 걸었는가.

        `all([])` 은 참이라, 임계값이 없는 시나리오는 요청이 전부 실패해도 `thresholds_ok` 가
        참이고 k6 는 HTTP 실패로 종료 코드를 안 바꾼다(99 는 임계값 미달 전용). 그래서 40건이
        전부 죽은 실행이 `verdict pass` · exit 0 으로 나갔다 — 이 레인이 스스로 "안 떨어지는
        게이트는 장식이다"라고 적어 둔 바로 그 상태다.

        고치는 자리는 `thresholds_ok` 의 뜻이 아니다(빈 집합에 대해 참인 것은 맞다). 갈라야 할
        것은 **판정에 통과한 실행**과 **판정할 것이 없던 실행**이고, 그 둘이 표면과 종료 코드에서
        같아 보이는 것이 결함이다."""
        return bool(self.thresholds)

    @property
    def ok(self) -> bool:
        """통과 = 임계값 전부 충족 + 프로세스가 정상으로 끝남.

        판정할 것이 없었으면 통과가 아니다 — `judged` 를 함께 물어야 "쟀고 통과했다"가 된다."""
        return self.judged and self.thresholds_ok and self.exit_code == 0

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
            # 판정 없음과 판정 통과를 기록에서도 가른다 — 나중에 이 파일만 보고 물을 수 있어야 한다
            "judged": self.judged,
            # 이 레인에서 가장 비싼 신호다. 어긋났다는 말은 `ok` 도 `exit_code` 도 못 믿는다는
            # 뜻인데, 여태 그 신호는 그 판이 도는 화면에서 한 번 뜨고 사라졌다 — 파일에 없으니
            # 되열어도 안 나오고, 그래서 **가장 못 믿을 판정이 가장 조용히 통과**했다.
            "exit_agrees": self.exit_agrees,
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
        raise SummaryError("요약이 JSON 객체가 아니에요")
    schema = payload.get("schema")
    if schema != SUMMARY_SCHEMA:
        raise SummaryError(f"요약 스키마가 달라요: {schema!r} (기대: {SUMMARY_SCHEMA})")
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


_RUN_SEQ = itertools.count(1)


def container_name() -> str:
    """이 실행만의 컨테이너 이름.

    프로세스 id 하나로 짓던 시절, 한 프로세스 안에서 연달아 도는 판들이 전부 같은 이름이었다.
    `--rm` 의 회수는 **비동기**라 앞판의 컨테이너가 아직 지워지는 중이면 뒷판이
    `Conflict. The container name ... is already in use` 로 즉시 죽는다. 그러면 요약이 안 나오고
    selftest 는 빨개진다 — 하네스의 정합성 판정이 하네스가 아니라 **도커 데몬의 부하**의
    함수가 되는 것이다. 판마다 다른 이름을 주면 그 결합이 끊긴다."""
    return f"{PROJECT}-{os.getpid()}-{next(_RUN_SEQ)}"


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

    argv = build_argv(runner, scenario, out, env, quiet=quiet, container_name=container_name(), kit=kit)
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
        raise SummaryError(f"부하 실행이 {timeout:.0f}s 안에 끝나지 않았어요") from exc
    except OSError as exc:
        raise SummaryError(f"러너를 실행할 수 없어요: {exc}") from exc

    if not summary_path.is_file():
        tail = ((done.stderr or "") + (done.stdout or ""))[-2000:] if not stream else ""
        raise SummaryError(
            "요약 파일이 나오지 않았어요 — 시나리오가 handleSummary를 export 하지 않았거나 "
            f"실행이 시작 전에 죽었어요 (exit {done.returncode}).\n{tail}"
        )
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SummaryError(f"요약을 읽을 수 없어요: {exc}") from exc

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
        # 파이프를 아무도 안 비우면 표적이 **부하 도중에 멈춘다**. 파이프 버퍼가 차는 순간
        # pacer 의 write 가 막히고, 그러면 지연이 치솟은 것처럼 보이는 수치가 나온다 — 표적이
        # 느린 것이 아니라 우리가 안 읽어서 생긴 값이다. 뒤에서 계속 비우고 마지막 조각만 든다.
        self._err: list[str] = []
        self._drain = threading.Thread(target=self._pump, name=f"pacer-err-{self.port}", daemon=True)
        self._drain.start()
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self._drain.join(timeout=2.0)
                raise SummaryError(f"pacer가 뜨지 못했어요: {''.join(self._err).strip()[:400]}")
            try:
                with urllib.request.urlopen(f"{self.url}/health", timeout=1) as resp:
                    if resp.status == 200:
                        return self
            except urllib.error.URLError, OSError:
                time.sleep(0.1)
        self.stop()
        raise SummaryError("pacer가 15s 안에 응답하지 않았어요")

    def _pump(self) -> None:
        stream = self.proc.stderr if self.proc else None
        if stream is None:
            return
        try:
            for line in stream:
                self._err.append(line)
                del self._err[:-40]  # 마지막 몇 줄이면 진단에 충분하다 — 무한히 들고 있지 않는다
        except OSError, ValueError:
            pass

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
        result.error = "러너가 없어요 — docker나 podman, 아니면 k6가 있어야 해요"
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
        wall_start = time.monotonic()
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
        wall_ms = (time.monotonic() - wall_start) * 1000.0
        result.reports["truth"] = report

        result.checks.append(
            _check("summary-schema", True, SUMMARY_SCHEMA, SUMMARY_SCHEMA, "요약이 정본 스키마로 파싱됐어요")
        )
        # 시간축에는 여태 검사가 하나도 없었다. 그래서 `duration_ms` 를 상수로 망가뜨려도 13개
        # 검사가 전부 녹색이었다(실측). 시간은 보고서에서 파생 수치의 분모라, 그것이 거짓이면
        # req/s 와 그것으로 판단한 용량 결론이 통째로 거짓이 된다. 두 각도로 묶는다 —
        # ① 요약이 스스로와 맞는가(건수 = 요청률 × 실행 시간)
        # ② 하네스가 실제로 기다린 벽시계를 넘지 않는가
        implied = report.rate_per_s * (report.duration_ms / 1000.0)
        result.checks.append(
            _check(
                "summary-time-consistency",
                report.duration_ms > 0 and abs(implied - report.requests) <= max(1.0, report.requests * 0.1),
                f"요청률 × 실행 시간 ≈ {report.requests}건",
                f"{implied:.1f}건 (rate {report.rate_per_s:.2f}/s × {report.duration_ms:.0f}ms)",
                "건수·요청률·실행 시간 셋 중 하나가 망가지면 이 곱이 어긋나요 — 시간축의 유일한 자물쇠예요",
            )
        )
        result.checks.append(
            _check(
                "duration-within-wall-clock",
                0 < report.duration_ms <= wall_ms,
                f"0 < 실행 시간 <= {wall_ms:.0f}ms",
                f"{report.duration_ms:.0f}ms",
                "보고된 실행 시간이 하네스가 실제로 기다린 시간을 넘을 수는 없어요",
            )
        )
        result.checks.append(
            _check(
                "request-count",
                report.requests == iterations,
                iterations,
                report.requests,
                "고정 반복인데 보고된 요청 수가 다르면 요약이 다른 메트릭을 읽고 있는 거예요",
            )
        )
        served = int(stats.get("requests") or 0)
        result.checks.append(
            _check(
                "server-parity",
                served == report.requests,
                f"server {report.requests}",
                f"server {served}",
                "표적이 센 건수와 하네스가 센 건수예요 — 어긋나면 한쪽이 요청을 흘린 거예요",
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
                f"표적이 정확히 {latency_ms:.0f}ms를 자요 — 보고된 중앙값이 그 값이어야 해요",
            )
        )
        peak = int(stats.get("peak_in_flight") or 0)
        result.checks.append(
            _check(
                "concurrency-applied",
                peak == vus,
                f"peak {vus}",
                f"peak {peak}",
                "상한 없는 표적에서는 동시 처리 정점이 VU 수와 같아야 해요 — 작으면 직렬로 돈 거예요",
            )
        )
        result.checks.append(
            _check(
                "threshold-passes-when-met",
                report.thresholds_ok and report.exit_code == 0,
                "thresholds ok · exit 0",
                f"thresholds {'ok' if report.thresholds_ok else 'FAIL'} · exit {report.exit_code}",
                "충족되는 임계값은 통과해야 해요",
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
        result.error = f"truth 판이 끝나지 못했어요: {exc}"
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
                "안 떨어지는 게이트는 장식이에요 — 지킬 수 없는 임계값은 반드시 깨져야 해요",
            )
        )
        result.checks.append(
            _check(
                "exit-code-on-breach",
                report.exit_code == THRESHOLD_EXIT,
                f"exit {THRESHOLD_EXIT}",
                f"exit {report.exit_code}",
                "임계값 미달은 종료 코드로도 나와야 CI가 잡아요",
            )
        )
        expected_failures = int(iterations * error_rate)
        result.checks.append(
            _check(
                "error-accounting",
                report.failed == expected_failures,
                f"{expected_failures} failed",
                f"{report.failed} failed",
                "표적의 실패는 확률이 아니라 주기예요 — 건수가 정확히 맞아야 해요",
            )
        )
        served_errors = int(stats.get("errored") or 0)
        result.checks.append(
            _check(
                "error-parity",
                served_errors == report.failed,
                f"server {report.failed}",
                f"server {served_errors}",
                "표적이 낸 5xx와 하네스가 센 실패가 같아야 해요",
            )
        )
    except (SummaryError, OSError) as exc:
        result.error = f"gate 판이 끝나지 못했어요: {exc}"
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
                "상한을 건 표적에서 동시 처리 정점이 상한을 넘으면 표적 쪽 게이트가 샌 거예요",
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
        result.error = f"saturate 판이 끝나지 못했어요: {exc}"
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


@dataclass(frozen=True)
class RunRecord:
    """기록된 실행 하나 — 스탬프와 그때 남긴 report.json 본문."""

    stamp: str
    payload: dict
    path: Path


def recorded_runs(root: str | os.PathLike[str]) -> list[RunRecord]:
    """기록된 실행 전부, 오래된 것부터. 스탬프가 `%Y%m%dT%H%M%S-<시나리오>` 라 사전순이 시간순이다.

    못 읽는 파일은 건너뛴다 — 기록 하나가 깨졌다고 나머지 이력 전체를 못 보게 되면, 게이트를
    쓰는 사람이 하는 일은 `runs/` 를 통째로 지우는 것이다."""
    runs = runs_dir(root)
    if not runs.is_dir():
        return []
    out: list[RunRecord] = []
    for path in sorted(runs.glob("*/report.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        if isinstance(payload, dict):
            out.append(RunRecord(path.parent.name, payload, path))
    return out


def find_recorded_run(root: str | os.PathLike[str], stamp: str = "", *, scenario: str = "") -> RunRecord | None:
    """스탬프로 지목하거나, 안 주면 가장 최근 기록. `scenario` 를 주면 그 시나리오로 돈 것만 본다.

    시나리오를 스탬프 접미사가 아니라 요약 본문에서 읽는 이유: 직접 경로로 돌린 실행
    (`asgard k6 run ./mine.js`)은 스탬프 접미사가 파일 이름이라 시나리오 이름과 다를 수 있다."""
    if stamp:
        return next((record for record in recorded_runs(root) if record.stamp == stamp), None)
    for record in reversed(recorded_runs(root)):
        if not scenario or str(record.payload.get("scenario") or "") == scenario:
            return record
    return None


# ────────────────────────────────────────────────── 기준선과 성능 회귀 게이트

BASELINE_NAME = "baseline.json"
BASELINE_SCHEMA = "asgard-k6-baseline-v1"
GATE_SCHEMA = "asgard-k6-gate-v1"

# 오차를 덮어쓰는 자리. `[tool.asgard.health-gate]` 와 같은 관례다 — 게이트의 느슨함은 코드가
# 아니라 저장소가 정하고, 그 결정이 diff 에 남아 리뷰 대상이 된다.
GATE_TABLE = ("tool", "asgard", "k6-gate")

# 비교 가능성을 정하는 축. 이 중 하나라도 다르면 두 수치는 **같은 것을 잰 값이 아니고**, 그런
# 값끼리의 판정은 거짓이다. 그래서 수치를 보기 전에 여기부터 대조한다.
#
# `vus_max` 가 들어간 이유: 같은 시나리오라도 `--vus 1` 로 잰 값과 `--vus 10` 으로 잰 값을
# 견주는 것은 러너가 다른 것과 정확히 같은 종류의 거짓 판정이다. `vus_max` 는 설정에서 나오는
# 값이라 같은 부하 형상이면 같은 값이 된다.
#
# `iterations` 는 **일부러 뺐다.** 기간 기반 시나리오에서 반복 수는 설정이 아니라 결과다. 같기를
# 요구하면 그런 시나리오는 영영 판정을 못 받고, 더 나쁘게는 우리가 잡으려는 처리량 악화 자체가
# "견줄 수 없음"으로 둔갑한다.
GATE_AXES = ("scenario", "runner", "k6_version", "target", "vus_max")


# ── 허용 오차의 근거 (실측) ──
#
# 부하 수치는 같은 기계·같은 코드에서도 흔들린다. 그 흔들림보다 좁은 오차를 걸면 게이트는
# 아무것도 안 바뀐 커밋을 막고, 그다음에 일어나는 일은 게이트를 끄는 것이다. 그래서 기본값을
# 짐작이 아니라 실측으로 정했다 (2026-08-03 · native k6 v2.1.0 · darwin/arm64 · 표적은 키트 pacer).
#
#   평평한 표적 (고정 80ms sleep, 꼬리가 없다)    p95 재현 편차  n=690 0.23% · n=40 0.38%
#   줄서는 표적 (동시성 상한 2 에 VU 5, 대기열)   p95 재현 편차  n≈357 **9.25%** (5회 반복)
#                                                  같은 실행의 med 1.71% · req/s 0.57%
#
# 읽는 법: 평평한 표적의 0.2~0.4% 는 하네스 자체의 잡음 하한이지 표적의 잡음이 아니다. 고정
# 지연에는 꼬리가 없어서 어느 분위수를 재도 같은 값이 나온다. 대기열이 생기는 순간 같은 코드가
# 9.25% 를 오갔고(225.03~247.13ms), 그동안 중앙값은 1.71% 안에 있었다 — 움직인 것은 꼬리다.
# 부하 게이트가 재는 것이 바로 그 꼬리다.
DEFAULT_P95_PCT = 20.0
# 측정된 9.25% 에 약 2배 여유. 여유가 필요한 이유가 둘 더 있다.
#   ① 위 측정은 놀고 있는 기계에서 서비스 시간이 상수인 표적으로 잰 값이다. 실제 표적에는
#      GC 정지·캐시 예열·연결 재수립이 더해진다.
#   ② p95 는 순서통계량이다. n 건에서 95분위 순위의 표준편차는 √(n·0.95·0.05) 이고, n=357 이면
#      4.1위, n=40 이면 1.4위(= n 의 3.45%)다. 표본이 작을수록 아무것도 안 바뀌어도 추정치가
#      꼬리를 더 크게 오르내린다.
# 10% 로 잡으면 위 실측 잡음이 그대로 회귀로 잡힌다.

DEFAULT_RATE_PER_S_PCT = 10.0
# 처리량은 꼬리가 아니라 실행 전체의 평균이라 훨씬 안정적이다 — 같은 실측에서 0.57%(n≈357)와
# 1.50%(n=40)였고, 10% 는 최악 관측의 약 7배다. p95(20%)와 다른 수인 것은 임의가 아니라 이
# 차이 때문이다.

DEFAULT_FAILED_RATE_PP = 1.0
# 실패는 잡음이 아니라 사건이다 — 위 16회 실행에서 실패는 전부 0.0000 이었고, 그래서 이 축에는
# 잴 잡음 하한 자체가 없다. 단위가 비율(%)이 아니라 **퍼센트포인트**인 이유도 거기 있다: 건강한
# 기준선의 failed_rate 는 0.0 이고 0 의 20% 는 0 이라, 비율 오차를 걸면 한 건짜리 전송 실패가
# 곧바로 회귀가 된다. 1.0pp 는 이 레인이 실제로 도는 규모(40~700건)에서 딸꾹질 한 건을 봐주는
# 폭이다. **알려진 한계**: n=10,000 이면 1.0pp 는 실패 100건이다. 큰 실행을 상시로 도는
# 저장소는 [tool.asgard.k6-gate] 에서 이 값을 좁혀야 한다.


@dataclass(frozen=True)
class Tolerance:
    """회귀라고 부르기 전에 봐주는 폭. 축마다 단위가 다르고, 그 차이가 요점이다."""

    p95_pct: float = DEFAULT_P95_PCT
    failed_rate_pp: float = DEFAULT_FAILED_RATE_PP
    rate_per_s_pct: float = DEFAULT_RATE_PER_S_PCT

    def as_dict(self) -> dict:
        return {
            "p95_pct": self.p95_pct,
            "failed_rate_pp": self.failed_rate_pp,
            "rate_per_s_pct": self.rate_per_s_pct,
        }


def gate_tolerance(root: str | os.PathLike[str]) -> Tolerance:
    """`pyproject.toml` 의 `[tool.asgard.k6-gate]` 로 기본 오차를 덮는다. 없으면 기본값 그대로.

    수치(기준선)는 기계마다 다르므로 `.asgard/` 에 두지만, 정책(오차)은 기계와 무관하므로
    추적되는 파일에 둔다. 그래야 게이트를 푸는 일이 diff 에 남는다.

    못 쓸 값(bool·문자열·음수)은 무시하고 기본값으로 내려간다 — 0 으로 읽으면 오타 하나가
    오차를 없애 버려서, 아무것도 안 바뀐 실행이 회귀로 나온다."""
    try:
        with open(os.path.join(str(root), "pyproject.toml"), "rb") as handle:
            table: object = tomllib.load(handle)
    except OSError, tomllib.TOMLDecodeError:
        return Tolerance()
    for key in GATE_TABLE:
        if not isinstance(table, dict):
            return Tolerance()
        table = table.get(key, {})
    if not isinstance(table, dict):
        return Tolerance()
    values: dict[str, float] = {}
    for name, fallback in (
        ("p95_pct", DEFAULT_P95_PCT),
        ("failed_rate_pp", DEFAULT_FAILED_RATE_PP),
        ("rate_per_s_pct", DEFAULT_RATE_PER_S_PCT),
    ):
        raw = table.get(name)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
            values[name] = fallback
        else:
            values[name] = float(raw)
    return Tolerance(**values)


def baseline_path(root: str | os.PathLike[str]) -> Path:
    """`.asgard/k6/baseline.json` — 이 프로젝트가 표적으로 삼은 실행.

    `[tool.asgard.health-gate]` 는 기준선을 추적되는 파일에 두었는데, 부하는 그 논리가 뒤집힌다.
    p95 는 코드의 성질이 아니라 코드와 기계와 표적이 함께 만드는 값이다. 노트북의 85ms 를
    추적되는 파일에 새기면 CI 러너가 그 값과 자기 수치를 견주게 되고, 그 판정은 코드가 아니라
    하드웨어를 재는 것이 된다. 부하 기준선은 잰 자리에 있어야 한다."""
    return lane_dir(root) / BASELINE_NAME


def baseline_blocker(payload: dict) -> str:
    """이 실행을 기준선으로 못 삼는 이유 코드. 삼을 수 있으면 빈 문자열.

    기준선은 앞으로의 실행을 통과시키는 **표준**이라, 대조군보다 요구가 높다. 아무도 검증하지
    않은 실행을 표준으로 삼으면 이 레인이 실제로 겪었던 사고 — 40건이 전부 죽었는데
    `verdict pass` · exit 0 으로 나간 실행 — 가 그대로 정본이 되고, 그 뒤로는 똑같이 망가진
    실행이 영원히 게이트를 통과한다.

    거절 셋:
      unreadable      요약 계약을 안 지킨 기록. 이 수치가 무엇인지부터 알 수 없다.
      empty           요청 0건. 잰 것이 없는 실행은 표준이 될 수 없다.
      unjudged        임계값이 없어 판정할 것이 없었던 실행 (`Report.judged`).
      exit-disagrees  종료 코드와 임계값 판정이 어긋난 실행. 레인이 이미 못 믿는다고 말한 값이다.
    """
    try:
        report = parse_summary(payload, exit_code=int(payload.get("exit_code") or 0))
    except SummaryError, TypeError, ValueError:
        return "unreadable"
    if report.requests <= 0:
        return "empty"
    if not report.judged:
        return "unjudged"
    if not report.exit_agrees:
        return "exit-disagrees"
    return ""


@dataclass(frozen=True)
class Baseline:
    """지금 표적으로 삼고 있는 실행. `run` 은 그때 기록한 report.json 본문 그대로다."""

    stamp: str
    set_at: str
    run: dict
    path: Path

    @property
    def scenario(self) -> str:
        return str(self.run.get("scenario") or "")


def write_baseline(root: str | os.PathLike[str], record: RunRecord, *, set_at: str = "") -> Baseline:
    """어느 실행을 표적으로 삼았는지를 통째로 새긴다.

    수치만 뽑아 적지 않고 요약 본문을 그대로 넣는 이유: 나중에 이 파일 하나만 열어도 "어떤
    시나리오를, 어떤 러너와 k6 판으로, 어떤 표적에" 걸어 나온 값인지 물을 수 있어야 한다.
    `runs/<stamp>/` 는 보존 정책에 따라 지워질 수 있고, 그때 기준선만 남으면 근거가 사라진다."""
    path = baseline_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = set_at or time.strftime("%Y-%m-%dT%H:%M:%S")
    body = {
        "schema": BASELINE_SCHEMA,
        "stamp": record.stamp,
        "set_at": stamped,
        "run": record.payload,
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return Baseline(record.stamp, stamped, record.payload, path)


def read_baseline(root: str | os.PathLike[str]) -> Baseline | None:
    """세워 둔 기준선. 없으면 None, 있는데 계약을 안 지켰으면 `SummaryError`.

    없음과 깨짐을 가르는 이유: 없음은 정상 상태(아직 표적을 안 정했다)이고, 깨짐은 사람이
    알아야 할 사고다. 둘을 None 하나로 합치면 손상된 기준선이 "아직 안 세웠다"로 읽힌다.

    사유 문장이 해요체인 것은 이 예외가 그대로 화면에 찍히기 때문이다 — `baseline show` 는
    이 문장 말고 다른 설명을 내지 않는다."""
    path = baseline_path(root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SummaryError(f"기준선을 읽을 수 없어요: {exc}") from exc
    schema = payload.get("schema") if isinstance(payload, dict) else None
    if schema != BASELINE_SCHEMA:
        raise SummaryError(f"기준선 스키마가 달라요: {schema!r} (기대: {BASELINE_SCHEMA})")
    run = payload.get("run")
    if not isinstance(run, dict):
        raise SummaryError("기준선에 실행 본문이 없어요 — asgard k6 baseline set으로 다시 세워 주세요.")
    return Baseline(str(payload.get("stamp") or ""), str(payload.get("set_at") or ""), run, path)


def clear_baseline(root: str | os.PathLike[str]) -> bool:
    """기준선을 치운다. 치울 것이 있었으면 True."""
    path = baseline_path(root)
    if not path.is_file():
        return False
    path.unlink()
    return True


@dataclass(frozen=True)
class Axis:
    """비교 가능성 축 하나 — 두 실행이 같은 것을 잰 값인지를 정하는 값."""

    name: str
    baseline: str
    current: str

    @property
    def same(self) -> bool:
        return self.baseline == self.current


@dataclass(frozen=True)
class Delta:
    """수치 축 하나의 변화와 판정.

    `higher_is_better` 가 부등호를 뒤집는다 — 처리량은 떨어지는 것이 악화이고 지연은 오르는
    것이 악화다. 이 값을 안 보고 한 방향으로만 재면 처리량 회귀가 전부 통과한다."""

    metric: str
    baseline: float
    current: float
    limit: float  # 넘으면(높을수록 좋은 축이면 밑돌면) 회귀
    higher_is_better: bool
    unit: str

    @property
    def regressed(self) -> bool:
        return self.current < self.limit if self.higher_is_better else self.current > self.limit

    @property
    def change_pct(self) -> float:
        """기준선 대비 변화율. 기준선이 0 이면 비율이 없다 — 화면은 이 값 대신 절대값을 쓴다."""
        return 0.0 if self.baseline == 0 else (self.current - self.baseline) / self.baseline * 100.0

    def as_dict(self) -> dict:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "current": self.current,
            "limit": self.limit,
            "higher_is_better": self.higher_is_better,
            "unit": self.unit,
            "change_pct": self.change_pct,
            "regressed": self.regressed,
        }


# 판정 셋. `undecidable` 이 `pass` 와 다른 낱말인 것이 이 게이트의 계약이다 — 종료 코드는 둘 다
# 0 이지만(못 견줄 때 막는 것은 소음이다) 판정문은 절대 같지 않다.
VERDICT_PASS = "pass"
VERDICT_REGRESSED = "regressed"
VERDICT_UNDECIDABLE = "undecidable"


@dataclass(frozen=True)
class GateVerdict:
    """게이트 판정 1회."""

    verdict: str
    reason: str  # undecidable 일 때의 이유 코드
    baseline_stamp: str = ""
    current_stamp: str = ""
    scenario: str = ""
    axes: tuple[Axis, ...] = ()
    deltas: tuple[Delta, ...] = ()
    tolerance: Tolerance = field(default_factory=Tolerance)

    @property
    def blocked(self) -> bool:
        return self.verdict == VERDICT_REGRESSED

    @property
    def mismatched(self) -> tuple[Axis, ...]:
        return tuple(axis for axis in self.axes if not axis.same)

    @property
    def regressions(self) -> tuple[Delta, ...]:
        return tuple(delta for delta in self.deltas if delta.regressed)

    def as_dict(self) -> dict:
        return {
            "schema": GATE_SCHEMA,
            "verdict": self.verdict,
            "reason": self.reason,
            "baseline_stamp": self.baseline_stamp,
            "current_stamp": self.current_stamp,
            "scenario": self.scenario,
            "tolerance": self.tolerance.as_dict(),
            "axes": [{"name": a.name, "baseline": a.baseline, "current": a.current, "same": a.same} for a in self.axes],
            "deltas": [d.as_dict() for d in self.deltas],
        }


def axis_values(payload: dict) -> dict[str, str]:
    """비교 가능성 축의 값. 전부 문자열로 맞춰 두면 대조가 한 줄이 된다."""
    return {
        "scenario": str(payload.get("scenario") or ""),
        "runner": str(payload.get("runner") or ""),
        "k6_version": str(payload.get("k6_version") or ""),
        "target": str(payload.get("target") or ""),
        "vus_max": str(int(payload.get("vus_max") or 0)),
    }


def _measurements(payload: dict) -> tuple[float, float, float, int]:
    reqs = payload.get("requests") or {}
    latency = payload.get("latency_ms") or {}
    return (
        float(latency.get("p95") or 0.0),
        float(reqs.get("failed_rate") or 0.0),
        float(reqs.get("rate_per_s") or 0.0),
        int(reqs.get("count") or 0),
    )


def compare_to_baseline(baseline: Baseline, current: RunRecord, tolerance: Tolerance) -> GateVerdict:
    """기준선과 마지막 기록을 견준다. 부하는 안 돈다 — 파일 둘을 읽고 끝난다.

    **비교 가능성이 판정보다 먼저다.** 다른 시나리오·다른 러너·다른 k6 판·다른 표적·다른 부하
    형상에서 나온 수치를 견주면 그 판정은 거짓이다. 그런 때는 회귀라고 말하지 않고 "견줄 수
    없다"고 말한다 — 거짓 회귀 하나가 이 게이트를 끄게 만드는 데는 한 번이면 충분하다."""
    base_axes, cur_axes = axis_values(baseline.run), axis_values(current.payload)
    axes = tuple(Axis(name, base_axes[name], cur_axes[name]) for name in GATE_AXES)
    scenario = base_axes["scenario"]
    common = {
        "baseline_stamp": baseline.stamp,
        "current_stamp": current.stamp,
        "scenario": scenario,
        "axes": axes,
        "tolerance": tolerance,
    }
    if any(not axis.same for axis in axes):
        return GateVerdict(VERDICT_UNDECIDABLE, "not-comparable", **common)

    base_p95, base_failed, base_rate, base_count = _measurements(baseline.run)
    cur_p95, cur_failed, cur_rate, cur_count = _measurements(current.payload)
    # 요청 0건인 실행에는 견줄 수치가 없다. 여기서 안 막으면 기준선 p95 0ms 가 허용치 0ms 가
    # 되어, 정상으로 돈 실행이 전부 회귀로 나온다.
    if base_count <= 0 or cur_count <= 0:
        return GateVerdict(VERDICT_UNDECIDABLE, "no-measurement", **common)

    deltas = (
        Delta("p95", base_p95, cur_p95, base_p95 * (1 + tolerance.p95_pct / 100.0), False, "ms"),
        # 퍼센트포인트를 비율로 되돌린다 — 요약의 failed_rate 는 0~1 이다.
        Delta("failed_rate", base_failed, cur_failed, base_failed + tolerance.failed_rate_pp / 100.0, False, "rate"),
        Delta("rate_per_s", base_rate, cur_rate, base_rate * (1 - tolerance.rate_per_s_pct / 100.0), True, "req/s"),
    )
    verdict = VERDICT_REGRESSED if any(delta.regressed for delta in deltas) else VERDICT_PASS
    return GateVerdict(verdict, "", deltas=deltas, **common)
