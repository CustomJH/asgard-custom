"""설정 탐색·기록 + 2단 retain 승인 저장소 (pending·consumed·승인 키)."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Mapping

from ..project_memory_backends import parse_settings
from .trust import _trust_guard

CONFIG_NAME = "memory-server.json"
PROJECT_SECTION = "project_memory"
LEGACY_PROJECT_SECTION = "memory"  # 구 섹션 키 — 글로벌 개인 메모리 섹션과 동명이라 개명됨
PENDING_NAME = "memory-pending.json"
PENDING_TTL = 3600  # 승인 id 만료 (초) — 승인과 실행 사이가 길면 재계획이 맞다
PENDING_LOCK_STALE = 60  # pending JSON lock은 짧은 local critical section에만 유지된다


# ── 설정 탐색 — cwd에서 상향 (모노레포·서브디렉토리 실행 대응) ─────────────────────


class ProjectMemoryConfigError(ValueError):
    """A project-memory config file is present but malformed."""


def _binding_sidecar_path(root: str) -> str:
    return os.path.join(root, ".asgard", "memory", "binding.json")


def read_binding_sidecar(root: str) -> dict:
    """바인딩 사이드카(.asgard/memory/binding.json) — 아스가르드가 관리하는 내부 신원.

    project_uid·binding_id는 사용자가 읽고 고치는 설정이 아니라 connect가 발급·검증하는
    소유권 마커다 (오딘 지적 26-07-23: 설정 파일에는 사람이 만지는 키만). git 추적으로 팀과
    공유된다. 깨진 파일은 없음과 동일 (fail-safe)."""
    try:
        with open(_binding_sidecar_path(root), encoding="utf-8") as source:
            raw = json.load(source)
        if not isinstance(raw, dict):
            return {}
        return {key: str(raw.get(key) or "").strip() for key in ("project_id", "project_uid", "binding_id")}
    except Exception:
        return {}


def _write_binding_sidecar(root: str, project_id: str, project_uid: str, binding_id: str) -> None:
    path = _binding_sidecar_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "_comment": "asgard memory connect가 관리하는 프로젝트 메모리 소유권 마커 — 직접 수정 금지",
        "project_id": project_id,
        "project_uid": project_uid,
        "binding_id": binding_id,
    }
    # 고정 이름은 남이 미리 만들어 둘 수 있는 자리다 (심볼릭 링크를 걸어 두면 우리가 그리로
    # 쓴다). 정본 record 쓰기와 같은 규율로 맞춘다: 이름은 랜덤, 만들기는 O_EXCL, 자리 바꾸기는
    # os.replace. 이 파일은 git으로 공유되는 소유권 마커라 권한만 0600이 아니다.
    tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o644)
    try:
        sink = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        with sink:
            json.dump(payload, sink, ensure_ascii=False, indent=1)
            sink.write("\n")
            sink.flush()
            os.fsync(sink.fileno())
        os.replace(tmp, path)
    finally:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.remove(tmp)


def project_memory_disabled(section: Mapping[str, object] | None) -> bool:
    """`enabled` 토글 — 명시적 false/off/0만 비활성. 부재·그 외 값 = 활성 (기본 on)."""
    if not section:
        return False
    value = section.get("enabled")
    if value is None or value is True:
        return False
    return str(value).strip().lower() in ("false", "off", "0")


# ── 두 층의 승인·신뢰 규율 · 2차 쪽 짝 ────────────────────────────────────────────
#
# 대조표는 여기 없다. 정본은 `memory/policy.py`의 `autosave_enabled` 바로 위 한자리이고,
# 여기는 그 표의 2차 열을 실제로 구현하는 자리다 — 표를 베껴 오지 않는 것이 요점이다.
# 두 벌을 두면 한쪽만 고쳤을 때 갈리고, 갈린 것을 알려 줄 사람이 없다 (그 조용한 분기를
# 막으려고 표를 하나로 모은 것이다).
#
# 이 파일이 그 표에 지고 있는 약속 셋 — 여기를 고칠 때 하나라도 어긋나면 표부터 고쳐라:
#   · 리포 값은 **제안**이다. 실행이 되려면 이 기계의 trust store에 사람이 준 허가가 있어야
#     한다 (`_machine_gated_state`). 1차가 리포 설정을 아예 안 보는 것과 같은 근거에서
#     나온 규율이고, 다른 것은 "끄지 않고 한 번 더 묻는다"뿐이다.
#   · 상태는 세 값이다. 참/거짓으로 뭉개면 "리포는 요청했는데 이 기계가 미승인"이 사라지고,
#     사람은 자기가 승인해야 한다는 사실을 볼 자리를 잃는다.
#   · 켜져도 지나는 길은 안 바뀐다 — 검증·Git 정본 선기록·backend 반영은 승인했을 때와
#     같은 경로다. 사라지는 것은 왕복뿐이다.
#
# 사람 승인 게이트의 세 상태 — 사람에게 보여줄 수 있어야 하므로 참/거짓으로 뭉개지 않는다.
GATE_OFF = "off"  # 리포가 요청하지 않았다
GATE_UNAPPROVED = "unapproved"  # 리포가 요청했으나 이 기계가 아직 승인하지 않았다
GATE_ON = "on"  # 이 기계가 승인했다 — 켜진 것은 이 상태뿐이다
_TRUE = ("on", "1", "true", "yes")


def _requested(cfg: Mapping[str, object] | None, key: str) -> bool:
    """리포 설정이 그 손잡이를 켜 달라고 **제안**하는가 — 켜졌는가가 아니다."""
    if not cfg:
        return False
    return str(cfg.get(key, "off")).strip().lower() in _TRUE


def _machine_gated_state(cfg: Mapping[str, object] | None, key: str, grant: str) -> str:
    """리포의 제안 + 이 기계의 허가 = 세 상태 중 하나.

    왜 리포 값 하나로는 안 되는가: `.asgard/asgard-setting-project.json`은 git으로 공유되는
    파일이라 커밋 한 줄이 팀 전원의 사람 승인 게이트를 끄게 된다. 1차 메모리가 같은 이유로
    프로젝트 설정을 아예 안 보는 것과 같은 규율이다 (`memory/policy.py`의 autosave_enabled:
    "clone으로 딸려 오는 파일에서 이 값을 켤 수 있으면 설정이 아니라 구멍이다").

    1차와 다른 점은 **끄지 않고 한 번 더 묻는다**는 것뿐이다: 이 기억의 스코프는 프로젝트라
    리포가 요청하는 것 자체는 정상이다. 그래서 리포 값은 제안으로만 받고, 실제로 켜지려면 이
    기계의 trust store에 사람이 준 허가가 있어야 한다. 허가가 없으면 리포가 `on`이라도 꺼진
    것으로 판정한다 (fail-closed)."""
    if not _requested(cfg, key):
        return GATE_OFF
    from .trust import has_machine_grant

    return GATE_ON if has_machine_grant(dict(cfg or {}), grant) else GATE_UNAPPROVED


def autosave_state(cfg: Mapping[str, object] | None) -> str:
    """2차(프로젝트) 메모리 자동저장의 게이트 상태 — GATE_OFF·GATE_UNAPPROVED·GATE_ON."""
    from .trust import GRANT_AUTOSAVE

    return _machine_gated_state(cfg, "autosave", GRANT_AUTOSAVE)


def autosave_enabled(cfg: Mapping[str, object] | None) -> bool:
    """2차(프로젝트) 메모리 자동저장 — 리포 제안(`project_memory.autosave`) + 이 기계의 허가.

    켜면 `memory_retain`이 approval_id를 돌려주고 기다리는 대신 그 자리에서 커밋한다.
    지나는 길은 **한 글자도 안 바뀐다**: 검증(validate_record)·Git 정본 선기록·backend 반영은
    사람이 승인했을 때와 똑같은 `commit_approved_record`를 그대로 탄다. 사라지는 것은 왕복뿐이다.

    허가가 왜 따로 필요한지는 `_machine_gated_state` 참조. 사람에게 "리포는 요청했는데 이
    기계가 미승인"을 보여주려면 참/거짓이 아니라 `autosave_state`를 읽어야 한다."""
    return autosave_state(cfg) == GATE_ON


def auto_retain_turns_state(cfg: Mapping[str, object] | None) -> str:
    """턴 원문 자동 적재의 게이트 상태 — GATE_OFF·GATE_UNAPPROVED·GATE_ON."""
    from .trust import GRANT_AUTO_RETAIN_TURNS

    return _machine_gated_state(cfg, "auto_retain_turns", GRANT_AUTO_RETAIN_TURNS)


def auto_retain_turns_enabled(cfg: Mapping[str, object] | None) -> bool:
    """대화 턴 원문을 공유 backend에 자동으로 적재하는가 — autosave와 같은 성질, 같은 허가 축.

    이쪽은 승인 단계가 아예 없어서 리포 설정 한 줄이 곧 실행이었다. 자동저장보다 넓게 새는
    손잡이다: 자동저장은 에이전트가 정제한 record 한 건이지만 이것은 사람이 쓴 턴 원문을
    통째로 보낸다. 게이트가 더 헐거울 근거가 없으므로 같은 grant를 요구한다."""
    return auto_retain_turns_state(cfg) == GATE_ON


def project_memory_section(project: dict) -> dict | None:
    """통합 설정에서 프로젝트 메모리 섹션을 고른다 — project_memory 우선, 구 memory 폴백.

    `_`로 시작하는 키는 스캐폴드가 심는 주석·입력 예제(_comment·_example)라 설정으로 치지
    않는다. 실 설정 키가 하나도 없으면 None — opt-in 미연결(공란 시드) 상태로, 깨진 설정과
    구별된다 (미연결 시드를 malformed로 읽으면 fresh init이 doctor에서 빨갛게 뜬다)."""
    for name in (PROJECT_SECTION, LEGACY_PROJECT_SECTION):
        raw = project.get(name)
        if isinstance(raw, dict):
            section = {key: value for key, value in raw.items() if not str(key).startswith("_")}
            if section:
                return section
    return None


def find_config(start: str | None = None, *, strict: bool = False) -> tuple[str, dict] | None:
    """프로젝트 메모리 섹션(project_memory — engine·project_id)을 위로 걸어가며 탐색한다.

    구 server·bank 설정은 Hindsight로 정규화한다. 반환 dict에는 전환 기간 동안 기존 호출부를
    위한 server·bank alias도 제공하지만, 저장 정본은 engine·endpoint·project_id다.
    깨진 JSON·필수 키 누락은 없음과 동일 (fail-safe — 툴 미노출이 오동작보다 낫다)."""
    from ..settings import PROJECT_FILE

    d = os.path.realpath(start or os.getcwd())
    while True:
        asg = os.path.join(d, ".asgard")
        project_file = os.path.join(asg, PROJECT_FILE)
        legacy_file = os.path.join(asg, CONFIG_NAME)
        if os.path.isfile(project_file) or os.path.isfile(legacy_file):
            try:
                from ..settings import load_project

                if strict and os.path.isfile(project_file):
                    with open(project_file, encoding="utf-8") as source:
                        raw = json.load(source)
                    if not isinstance(raw, dict):
                        raise ValueError("project settings must be a JSON object")
                    if project_memory_section(raw) is None:
                        return None
                    if project_memory_disabled(project_memory_section(raw)):
                        return None
                elif strict and os.path.isfile(legacy_file):
                    with open(legacy_file, encoding="utf-8") as source:
                        raw = json.load(source)
                    if not isinstance(raw, dict):
                        raise ValueError("legacy project-memory settings must be a JSON object")
                project = load_project(d)
                mem = project_memory_section(project)
                if mem is None or project_memory_disabled(mem):
                    return None
                # 신원(uid·binding)은 사이드카가 정본 — 설정 파일 잔존 값(구 스키마)이 있으면 그 값 우선.
                sidecar = read_binding_sidecar(d)
                mem = dict(mem)
                for key in ("project_uid", "binding_id"):
                    if not str(mem.get(key) or "").strip() and sidecar.get(key):
                        mem[key] = sidecar[key]
                settings = parse_settings(mem)
                normalized = dict(mem)
                normalized.update(
                    {
                        "engine": settings.engine,
                        "project_id": settings.project_id,
                        "endpoint": settings.endpoint,
                        "timeout": settings.timeout,
                        "options": dict(settings.options),
                        "project_uid": settings.project_uid,
                        "binding_id": settings.binding_id,
                        # 기존 정책/manifest 코드가 쓰는 호환 alias. backend에는 canonical key가 전달된다.
                        "bank": settings.project_id,
                        "server": settings.endpoint,
                    }
                )
                return d, normalized
            except Exception as exc:
                if strict:
                    raise ProjectMemoryConfigError(f"malformed project-memory configuration at {asg}") from exc
            return None
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def write_config(
    root: str,
    endpoint: str,
    project_id: str,
    *,
    engine: str = "hindsight",
    timeout: int | None = None,
    options: dict | None = None,
    project_uid: str = "",
    binding_id: str = "",
) -> str:
    from ..settings import save_project

    config = {
        "engine": engine.strip().lower(),
        "endpoint": endpoint.rstrip("/"),
        "project_id": project_id.strip(),
        "timeout": timeout,
        "options": options or None,
        "project_uid": project_uid or None,
        "binding_id": binding_id or None,
    }
    parse_settings({key: value for key, value in config.items() if value is not None})
    # 설정 파일에는 사람이 만지는 키만 남긴다 — uid·binding 신원은 사이드카로 (오딘 결정 26-07-23).
    # save_project는 섹션을 통째 교체하므로 구 스키마의 잔존 uid·binding 키도 함께 사라진다.
    visible = {key: value for key, value in config.items() if key not in ("project_uid", "binding_id")}
    # 구 memory 섹션은 함께 제거 — 남기면 정본이 이원화되고 폴백 리더가 낡은 값을 읽는다.
    path = save_project(root, PROJECT_SECTION, visible, drop=(LEGACY_PROJECT_SECTION,))
    if project_uid or binding_id:
        _write_binding_sidecar(root, config["project_id"], project_uid, binding_id)
    return path


# ── 승인 대기 (2단 retain) — 개인 위키 plan-id와 동일 계약 ───────────────────────────


def _pending_path(root: str) -> str:
    project_key = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:24]
    return os.path.join(os.path.expanduser("~"), ".asgard", "state", f"project-memory-pending-{project_key}.json")


def _secure_machine_directory(path: str) -> None:
    """Create an owner-only machine-local directory without following links."""
    parent = os.path.dirname(path)
    if parent and parent != path and not os.path.exists(parent):
        _secure_machine_directory(parent)
    is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(path))
    if os.path.lexists(path) and (os.path.islink(path) or is_junction):
        raise OSError(f"unsafe machine-local memory state directory: {path}")
    os.makedirs(path, mode=0o700, exist_ok=True)
    info = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        raise OSError(f"machine-local memory state path is not a directory: {path}")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise OSError(f"machine-local memory state directory has the wrong owner: {path}")
    _apply_private_acl(path, directory=True)


def _apply_private_acl(path: str, *, directory: bool = False) -> None:
    if os.name != "nt":
        os.chmod(path, 0o700 if directory else 0o600)
        return
    user = os.environ.get("USERNAME", "")
    if not user:
        raise OSError("USERNAME is required to secure project-memory approval state")
    grant = f"{user}:(OI)(CI)F" if directory else f"{user}:F"
    # /grant:r only replaces ACEs for the named user; it does not remove explicit ACEs for
    # Everyone or other users. Reset to inherited defaults first, then remove inheritance and
    # install the sole owner ACE.
    commands = (
        ["icacls", path, "/reset"],
        ["icacls", path, "/inheritance:r", "/grant:r", grant],
    )
    for command in commands:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=10, check=False, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            raise OSError(f"failed to secure project-memory approval state ACL: {path}")


def _validate_private_state_file(fd: int, label: str, path: str | None = None) -> None:
    info = os.fstat(fd)
    unsafe_posix_mode = os.name != "nt" and bool(info.st_mode & 0o077)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or unsafe_posix_mode:
        raise OSError(f"{label} must be a singly-linked regular 0600 file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise OSError(f"{label} has the wrong owner")
    if path is not None:
        is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(path))
        path_info = os.stat(path, follow_symlinks=False)
        if stat.S_ISLNK(path_info.st_mode) or is_junction:
            raise OSError(f"{label} must not be a symlink or junction")
        if (path_info.st_dev, path_info.st_ino) != (info.st_dev, info.st_ino):
            raise OSError(f"{label} changed while it was opened")


@contextlib.contextmanager
def _pending_guard(root: str):
    """프로세스/스레드 공통 lock — approval JSON의 lost update·double commit 방지."""
    path = _pending_path(root) + ".lock"
    _secure_machine_directory(os.path.dirname(path))
    deadline = time.monotonic() + 5
    fd = None
    while fd is None:
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > PENDING_LOCK_STALE:
                    os.remove(path)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("project memory approval lock timeout")
            time.sleep(0.01)
    try:
        _validate_private_state_file(fd, "project-memory approval lock", path)
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            os.remove(path)


def _warn(message: str) -> None:
    """사람에게 남기는 경고 — stderr로 간다 (stdout은 MCP 프로토콜 전용이다)."""
    with contextlib.suppress(Exception):
        print(f"[asgard:memory] {message}", file=sys.stderr, flush=True)


def _quarantine_pending(path: str, reason: str, *, move: bool) -> None:
    """승인 대기 파일을 옆으로 비켜 둔다 — 지우지 않는다.

    승인 대기는 사람이 이미 한 번 손을 댄 것이라, 못 읽는다고 조용히 버리면 사라진 것이
    무엇이었는지 물어볼 자리조차 없어진다. `move`는 파일 전체가 못 읽히는 경우다(다음
    저장이 새 파일을 만든다). 살아 있는 항목이 섞여 있으면 원본은 두고 사본만 남긴다.

    이름은 내용 해시로 짓는다. 사본을 남기는 쪽은 원본이 그대로 있어서 **읽을 때마다** 다시
    불리는데, 이름이 매번 다르면 격리본이 쌓여 그것대로 잃는 것이 된다. 같은 내용은 한 자리다."""
    try:
        with open(path, "rb") as source:
            digest = hashlib.sha256(source.read()).hexdigest()[:12]
    except OSError as exc:
        _warn(f"승인 대기 파일을 읽지 못해 격리도 못 했다 ({path}): {type(exc).__name__}: {exc}")
        return
    target = f"{path}.quarantine-{digest}"
    if not move and os.path.exists(target):
        return  # 이미 비켜 둔 내용이다 — 사본도 경고도 한 번이면 된다
    try:
        if move:
            os.replace(path, target)
        else:
            shutil.copy2(path, target)
        with contextlib.suppress(OSError):
            os.chmod(target, 0o600)
    except OSError as exc:
        _warn(f"승인 대기 파일을 격리하지 못했다 ({path}): {type(exc).__name__}: {exc}")
        return
    _warn(f"승인 대기 파일을 {target} 로 격리했다 — 버린 것이 아니라 비켜 뒀다 ({reason})")


def _load_pending_unlocked(root: str) -> dict:
    path = _pending_path(root)
    if not os.path.exists(path):
        return {}  # 아직 아무도 승인 대기를 만들지 않았다 — 정상이고 경고할 것이 없다
    try:
        _apply_private_acl(path)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            _validate_private_state_file(fd, "project-memory pending approval state", path)
        except Exception:
            os.close(fd)
            raise
        with os.fdopen(fd, encoding="utf-8") as source:
            d = json.load(source)
        if not isinstance(d, dict):
            raise ValueError("pending approval state must be a JSON object")
    except Exception as exc:
        _quarantine_pending(path, f"{type(exc).__name__}: {exc}", move=True)
        return {}
    now = time.time()
    live: dict[str, dict] = {}
    malformed = 0
    for approval_id, entry in d.items():
        if not isinstance(approval_id, str) or not isinstance(entry, dict):
            malformed += 1
            continue
        try:
            issued_at = float(entry.get("issued_at") or entry.get("ts") or 0)
        except TypeError, ValueError:
            malformed += 1
            continue
        if issued_at <= 0:
            malformed += 1
            continue
        if now - issued_at < PENDING_TTL:
            live[approval_id] = entry
    if malformed:
        # 만료(TTL)로 빠지는 것은 설계다 — 경고하지 않는다. 형태가 깨진 것만 비켜 둔다:
        # 다음 저장이 파일을 통째로 다시 쓰므로 여기서 안 남기면 그때 사라진다.
        _quarantine_pending(path, f"형태가 깨진 항목 {malformed}건", move=False)
    return live


def _load_pending(root: str) -> dict:
    with _pending_guard(root):
        return _load_pending_unlocked(root)


def _save_pending_unlocked(root: str, d: dict) -> None:
    p = _pending_path(root)
    _secure_machine_directory(os.path.dirname(p))
    tmp = f"{p}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        _validate_private_state_file(fd, "project-memory pending approval temporary state", tmp)
    except Exception:
        os.close(fd)
        raise
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    _apply_private_acl(p)


def _save_pending(root: str, d: dict) -> None:
    with _pending_guard(root):
        _save_pending_unlocked(root, d)


def _approval_key() -> bytes:
    """Repo 밖 0600 key. pending JSON을 수정한 repo-local 주체가 승인 payload를 재서명하지 못하게 한다."""
    directory = os.path.join(os.path.expanduser("~"), ".asgard")
    _secure_machine_directory(directory)
    path = os.path.join(directory, "project-memory-approval.key")
    with _trust_guard():
        if not os.path.exists(path):
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            try:
                key = secrets.token_bytes(32)
                os.write(fd, key)
                os.fsync(fd)
            finally:
                os.close(fd)
        _apply_private_acl(path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            _validate_private_state_file(fd, "project-memory approval key", path)
            key = os.read(fd, 33)
        finally:
            os.close(fd)
    if len(key) != 32:
        raise OSError("invalid project-memory approval key")
    return key


def _retain_item_mac(
    approval_id: str,
    issued_at: float,
    expires_at: float,
    item: str | dict,
    target: dict | None,
) -> str:
    payload = json.dumps(
        {
            "schema": 4,
            "approval_id": approval_id,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "item": item,
            "target": target,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hmac.new(_approval_key(), payload, hashlib.sha256).hexdigest()


def _consumed_path(root: str) -> str:
    project_key = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:24]
    return os.path.join(
        os.path.expanduser("~"),
        ".asgard",
        "state",
        f"project-memory-approval-consumed-{project_key}.json",
    )


def _approval_scope(root: str, approval_id: str) -> str:
    project_key = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:24]
    return f"{project_key}:{approval_id}"


def _consumed_mac(entries: dict[str, float]) -> str:
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(_approval_key(), payload, hashlib.sha256).hexdigest()


def _load_consumed_unlocked(root: str) -> dict[str, float]:
    path = _consumed_path(root)
    if not os.path.exists(path):
        return {}
    _apply_private_acl(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        _validate_private_state_file(fd, "project-memory consumed approval state", path)
        source = os.fdopen(fd, encoding="utf-8")
        fd = -1
        with source:
            data = json.load(source)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("entries"), dict):
        raise OSError("invalid project-memory consumed approval state")
    raw_entries: dict[str, float] = {}
    for key, value in data["entries"].items():
        try:
            raw_entries[str(key)] = float(value)
        except TypeError, ValueError:
            raise OSError("invalid project-memory consumed approval entry") from None
    expected = str(data.get("mac") or "")
    if not expected or not secrets.compare_digest(expected, _consumed_mac(raw_entries)):
        raise OSError("project-memory consumed approval state authentication failed")
    now = time.time()
    return {key: expiry for key, expiry in raw_entries.items() if expiry > now}


def _save_consumed_unlocked(root: str, entries: dict[str, float]) -> None:
    path = _consumed_path(root)
    _secure_machine_directory(os.path.dirname(path))
    payload = {"schema": 1, "entries": entries, "mac": _consumed_mac(entries)}
    tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        _validate_private_state_file(fd, "project-memory consumed approval temporary state", tmp)
        output = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        with output:
            json.dump(payload, output, ensure_ascii=False, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
        _apply_private_acl(path)
    finally:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.remove(tmp)


APPROVAL_ID_BYTES = 16  # 128비트. 32비트(4바이트)는 사람이 눈으로 셀 만한 건수에서 생일 충돌에 닿는다


def _new_approval_id(root: str, pending: Mapping[str, object]) -> str:
    """아직 아무도 안 쓴 approval id를 발급한다 — 엔트로피 128비트 + 발급 시 충돌 검사.

    검사가 왜 따로 필요한가: 충돌한 id는 남의 승인을 덮어쓰거나(대기 중인 것을 잃는다) 이미
    소비된 id로 태어난다(발급 즉시 죽은 승인). 128비트면 사실상 안 만나지만, 만났을 때
    조용히 나쁜 쪽으로 지나가는 코드는 두지 않는다. consumed 저장소를 못 읽어도 발급은
    막지 않는다 — 그 확인은 `claim_retain`이 소비 시점에 다시 한다."""
    consumed: dict[str, float] = {}
    with contextlib.suppress(OSError):
        consumed = _load_consumed_unlocked(root)
    for _ in range(8):
        aid = secrets.token_hex(APPROVAL_ID_BYTES)
        if aid not in pending and _approval_scope(root, aid) not in consumed:
            return aid
    raise OSError("failed to mint an unused project-memory approval id")


def stage_retain(root: str, item: str | dict, *, target: dict | None = None) -> str:
    """승인 대기 등록 — 반환 = approval id (1회 소비)."""
    with _pending_guard(root):
        pend = _load_pending_unlocked(root)
        document_id = str(item.get("document_id") or "") if isinstance(item, dict) else ""
        item_hash = hashlib.sha256(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        now = time.time()
        expires_at = now + PENDING_TTL
        if document_id:
            for existing_id, entry in pend.items():
                existing = entry.get("item")
                issued = float(entry.get("issued_at") or 0)
                expires = float(entry.get("expires_at") or 0)
                expected_mac = str(entry.get("item_mac") or "")
                actual_mac = _retain_item_mac(existing_id, issued, expires, existing, entry.get("target"))
                if (
                    entry.get("schema") == 4
                    and isinstance(existing, dict)
                    and existing.get("document_id") == document_id
                    and entry.get("item_hash") == item_hash
                    and entry.get("target") == target
                    and not entry.get("claim")
                    and expected_mac
                    and secrets.compare_digest(expected_mac, actual_mac)
                ):
                    return existing_id
        aid = _new_approval_id(root, pend)
        pend[aid] = {
            "item": item,
            "item_hash": item_hash,
            "item_mac": _retain_item_mac(aid, now, expires_at, item, target),
            "target": target,
            "ts": now,
            "issued_at": now,
            "expires_at": expires_at,
            "schema": 4,
        }
        _save_pending_unlocked(root, pend)
    return aid


def _retain_item_hash(item: str | dict) -> str:
    return hashlib.sha256(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def claim_retain(root: str, aid: str, *, target: dict | None = None) -> tuple[str | dict, str] | None:
    """approval을 원격 write 동안 독점 claim한다. 실패 시 같은 ID를 재사용할 수 있다."""
    with _pending_guard(root):
        if _approval_scope(root, aid) in _load_consumed_unlocked(root):
            return None
        pend = _load_pending_unlocked(root)
        entry = pend.get(aid)
        if not entry:
            return None
        if entry.get("schema") != 4:
            return None
        item = entry.get("item", entry.get("content"))
        expected_hash = str(entry.get("item_hash") or "")
        actual_hash = _retain_item_hash(item)
        if not expected_hash or not secrets.compare_digest(expected_hash, actual_hash):
            return None
        issued_at = float(entry.get("issued_at") or 0)
        expires_at = float(entry.get("expires_at") or 0)
        now = time.time()
        if not issued_at or expires_at <= issued_at or now >= expires_at:
            return None
        expected_mac = str(entry.get("item_mac") or "")
        actual_mac = _retain_item_mac(aid, issued_at, expires_at, item, entry.get("target"))
        if not expected_mac or not secrets.compare_digest(expected_mac, actual_mac):
            return None
        expected_target = entry.get("target")
        if target is not None:
            if not isinstance(expected_target, dict):
                return None
            expected_fingerprint = str(expected_target.get("fingerprint") or "")
            actual_fingerprint = str(target.get("fingerprint") or "")
            if (
                expected_target.get("engine") != target.get("engine")
                or expected_target.get("project_id") != target.get("project_id")
                or not expected_fingerprint
                or not secrets.compare_digest(expected_fingerprint, actual_fingerprint)
            ):
                return None
        if entry.get("claim"):
            return None
        token = secrets.token_hex(8)
        entry["claim"] = token
        entry["claimed_at"] = now
        _save_pending_unlocked(root, pend)
        return (item, token) if item is not None else None


def finish_retain(root: str, aid: str, token: str, *, success: bool) -> None:
    with _pending_guard(root):
        pend = _load_pending_unlocked(root)
        entry = pend.get(aid)
        if not entry or entry.get("claim") != token:
            return
        if success:
            consumed = _load_consumed_unlocked(root)
            consumed[_approval_scope(root, aid)] = float(entry.get("expires_at") or time.time() + PENDING_TTL)
            _save_consumed_unlocked(root, consumed)
            pend.pop(aid, None)
        else:
            entry.pop("claim", None)
            entry.pop("claimed_at", None)
        _save_pending_unlocked(root, pend)
