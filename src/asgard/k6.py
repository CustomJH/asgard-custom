"""asgard-k6 — 부하 시험 레인. 도커 k6 부트스트랩을 아스가르드가 소유한다.

지금까지 부하 시험은 떠돌이였다: `docker run --rm -i -v ...`를 손으로 치고, 스크립트마다
메트릭 이름이 다르고, 결과는 사람이 표로 옮겨 적었다. 그 상태의 문제는 느린 것이 아니라
**감사할 수 없다**는 것이다 — 어떤 이미지로 어떤 부하 형상을 걸어 나온 수치인지 기록이 없다.

이 모듈이 세우는 계약은 셋이다:

  러너    이미지·마운트·환경이 한 자리에서 조립된다 (`build_argv`, 순수 함수라 테스트가 본다).
  요약    모든 시나리오가 `asgard-k6-summary-v1` 한 모양으로 뱉는다 (`lib/asgard.js`).
  판정    임계값 결과와 프로세스 종료 코드를 **둘 다** 읽고 서로 어긋나면 그것을 사건으로 본다.

레인은 셋으로 갈라져 있다. 여기는 **부하를 걸고 그 한 판을 판정하는** 자리다. 나머지 둘은
묻는 것이 달라서 갈랐다 — `k6_selftest` 는 판정기 자신이 참을 말하는지 표적에 걸어 보고,
`k6_gate` 는 끝난 실행을 기록해 두었다가 기준선과 견준다. 둘 다 이 모듈을 읽고, 이 모듈은
둘을 안 읽는다.
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


def engine_responds(engine_binary: str, timeout: float = 10.0) -> bool:
    """이 컨테이너 엔진의 데몬이 지금 대답하는가 — 바이너리가 있다는 것과 다른 사실이다.

    `docker` 가 PATH 에 있어도 데몬이 안 떠 있으면 모든 하위 명령이 실패한다. 그 구분을
    안 하던 판은 데몬이 죽은 기계에서 도커를 러너로 골라 놓고, 옆에 멀쩡한 네이티브 k6 가
    있어도 폴백하지 않았다 (26-08-21 실측)."""
    try:
        probe = subprocess.run(
            [engine_binary, "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return False
    return probe.returncode == 0 and bool((probe.stdout or "").strip())


def resolve_runner(prefer: str = "") -> Runner | None:
    """컨테이너 우선, 없으면 네이티브 k6. `ASGARD_K6_RUNNER`로 고정할 수 있다.

    도커를 먼저 보는 이유는 취향이 아니다 — 이미지가 고정되면 같은 부하 형상이 다른
    기계에서도 같은 도구로 돌아간다. 네이티브 k6는 판이 사람마다 다르다.

    자동 선택일 때만 데몬 응답을 본다. 사람이 `ASGARD_K6_RUNNER` 로 엔진을 고정했으면 그
    선택을 지킨다 — 고정은 "이걸로 돌려라"이지 "되는 걸로 알아서 골라라"가 아니다."""
    prefer = (prefer or os.environ.get("ASGARD_K6_RUNNER") or "").strip().lower()
    if prefer == "native":
        binary = shutil.which("k6")
        return Runner("native", binary) if binary else None
    if prefer in ("docker", "podman"):
        binary = shutil.which(prefer)
        return Runner(prefer, binary, resolve_image(binary)) if binary else None
    for engine in ("docker", "podman"):
        binary = shutil.which(engine)
        if binary and engine_responds(binary):
            return Runner(engine, binary, resolve_image(binary))
    binary = shutil.which("k6")
    if binary:
        return Runner("native", binary)
    # 네이티브도 없다. 엔진 바이너리는 있으니 러너 자체는 돌려주되, 데몬이 죽었다는 사실은
    # `runner_version` 이 빈 문자열로 말한다 — 여기서 None 을 내면 "k6 가 아예 없다"가 되어
    # doctor 가 굽는 법을 안내할 대상조차 잃는다.
    for engine in ("docker", "podman"):
        found = shutil.which(engine)
        if found:
            return Runner(engine, found, resolve_image(found))
    return None


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
    # 종료 코드를 안 보던 판은 실패한 프로브의 stderr 첫 줄을 판 번호로 돌려줬다. 그래서
    # 도커 데몬이 죽은 기계에서 `Cannot connect to the Docker daemon...` 이 판 문자열이 되고,
    # 그 문자열이 비어 있지 않다는 이유로 `k6 doctor` 가 ready 를 냈다 (26-08-21 실측).
    # 같은 값이 report.json 의 `k6_version` 으로 새겨져 기준선 비교 축까지 흐른다.
    if done.returncode != 0:
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
