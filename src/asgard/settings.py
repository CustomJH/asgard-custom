"""통합 설정 (26-07-15 유저 확정) — 글로벌/프로젝트 각 1파일 + 런타임 state/ 격리.

  글로벌   ~/.asgard/asgard-setting-global.json     (구 ~/.asgard/config.toml)
  프로젝트 <root>/.asgard/asgard-setting-project.json (구 config.toml + trinity-policy.json
                                                       + memory-server.json 흡수)
  런타임   <root>/.asgard/state/                     (lagom-mode·route-priors·classify·
                                                       writes-*·memory-pending — 설정 아님)

섹션 스키마 (양쪽 동일 — 프로젝트가 글로벌을 키 단위로 이긴다):
  provider / trinity(네이티브 역할 배치) / agent_models(호스트별 역할 모델) / bridge /
  lagom / memory(글로벌 — 개인 메모리) / project_memory(프로젝트 전용 — 공유 backend,
  구 키 memory 는 폴백으로만 읽는다) / ui / trinity_policy(프로젝트 전용)

레거시 폴백: 신규 JSON 이 없으면 구 파일을 그대로 읽는다 (기배포 프로젝트·기존 테스트 무파손).
쓰기는 항상 신규 JSON — `asgard sync` 가 구 파일을 신 포맷으로 이관한다.
훅(standalone)은 이 모듈을 임포트하지 못한다 — 같은 "신규 우선+폴백" 규칙을 각 훅이 내장하며
"동일 유지 (단일 출처 원칙)" 주석으로 이 파일을 가리킨다.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import tomllib

GLOBAL_FILE = "asgard-setting-global.json"
PROJECT_FILE = "asgard-setting-project.json"
STATE_DIR = "state"
# 레거시 (폴백 전용 — 쓰기 금지)
LEGACY_TOML = "config.toml"
LEGACY_POLICY = "trinity-policy.json"
LEGACY_MEMORY = "memory-server.json"

WORKSPACE_DIR = "studio"
WORKSPACE_HOME_ENV = "ASGARD_STUDIO_HOME"


def global_dir() -> str:
    """활성 에이전트의 홈 — 기본 에이전트면 `~/.asgard` 그대로 (마이그레이션 0).

    프로파일 계층이 붙기 전까지 이 함수는 곧 기계 뿌리였다. 지금은 **에이전트의 사유 홈**이고,
    기계 단위 자산(자격증명·projects.json)은 `machine_dir()` 이 따로 가리킨다. `~/.asgard` 를
    직접 조립하던 코드는 둘 중 하나를 골라야 한다 — 그 선택이 곧 "이 파일이 누구 것인가"다."""
    from .profiles import home

    return home()


def workspace_home() -> str:
    """스튜디오 워크스페이스가 사는 곳 — **일감과 기획이 같이 든다**.

    스튜디오는 폴더에 딸린 도구가 아니라 사람이 켜는 앱이다. 그래서 티켓도 기획도 저장소
    안(`<프로젝트>/.asgard/…`)에 살 수 없다: 폴더를 옮기면 갈리고, 폴더를 안 열면 안 보이고,
    코드가 아직 없는 기획은 애초에 설 자리가 없다. 자리는 **에이전트 홈** 하나다.

    두 소비자(`studio.db`·`plan.store`)가 같은 함수를 보는 것이 요점이다 — 워크스페이스가
    하나라는 말은, 그 자리를 옮겼을 때 **둘이 같이 옮겨진다**는 뜻이어야 한다."""
    override = os.environ.get(WORKSPACE_HOME_ENV)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(global_dir(), WORKSPACE_DIR)


def machine_dir() -> str:
    """기계 단위 뿌리 `~/.asgard` — 에이전트가 몇이든 하나 (자격증명·레지스트리·캐시).

    os.path.expanduser("~") 는 Windows 에서 HOME 을 보지 않고 USERPROFILE/HOMEDRIVE+HOMEPATH
    만 본다(posix 는 HOME 우선) — HOME 을 명시 우선해 플랫폼 간 일관성 + 테스트 모킹 가능성 확보."""
    from .profiles import root

    return root()


def global_path() -> str:
    return os.path.join(global_dir(), GLOBAL_FILE)


def project_path(root: str) -> str:
    return os.path.join(root, ".asgard", PROJECT_FILE)


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            d = json.load(handle)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _read_toml(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _own_global(directory: str) -> dict:
    """한 홈의 글로벌 설정 — 신규 JSON 우선, 없으면 구 config.toml (섹션 구조 동일해 그대로 사용)."""
    d = _read_json(os.path.join(directory, GLOBAL_FILE))
    if d is not None:
        return d
    return _read_toml(os.path.join(directory, LEGACY_TOML))


def load_global() -> dict:
    """활성 에이전트의 글로벌 설정 — 기계 뿌리 위에 에이전트 것을 **키 단위로** 덮는다.

    왜 통째 교체가 아닌가: 사용자가 한 번 맞춘 ui·lagom·언어를 에이전트마다 다시 맞추게 하면
    "에이전트 추가"가 "설정 반복"이 된다. 반대로 provider·model·memory 는 에이전트마다 달라야
    쓸모가 있다. 그래서 기본은 물려받고, 적어 넣은 키만 갈린다 (프로젝트>글로벌과 같은 규율)."""
    own_dir = global_dir()
    machine = machine_dir()
    own = _own_global(own_dir)
    if os.path.realpath(own_dir) == os.path.realpath(machine):
        return own
    merged = dict(_own_global(machine))
    for name, value in own.items():
        if isinstance(value, dict) and isinstance(merged.get(name), dict):
            section_view = dict(merged[name])
            section_view.update(value)
            merged[name] = section_view
        else:
            merged[name] = value
    return merged


def _load_legacy_project(root: str) -> dict:
    """구 3파일 합성 뷰 — config.toml 섹션 + trinity-policy.json→trinity_policy
    + memory-server.json→memory. 마이그레이션과 폴백이 공유하는 유일한 레거시 해석."""
    asg = os.path.join(root, ".asgard")
    merged: dict = dict(_read_toml(os.path.join(asg, LEGACY_TOML)))
    pol = _read_json(os.path.join(asg, LEGACY_POLICY))
    if pol is not None:
        merged.setdefault("trinity_policy", pol)
    mem = _read_json(os.path.join(asg, LEGACY_MEMORY))
    if mem is not None:
        # 구 memory-server.json 은 [memory] 와 별개 파일이었다 — server/bank 키만 흡수
        m = dict(merged.get("memory") or {})
        m.update({k: v for k, v in mem.items() if k in ("server", "bank", "timeout")})
        merged["memory"] = m
    return merged


def load_project(root: str) -> dict:
    """프로젝트 설정 — 신규 JSON 우선, 없으면 레거시 합성 뷰."""
    d = _read_json(project_path(root))
    if d is not None:
        return d
    return _load_legacy_project(root)


def own_global(name: str) -> dict:
    """활성 에이전트가 **자기 파일에 직접 적은** 섹션만 (상속분 제외).

    경로처럼 "물려받으면 안 되는 값"을 위한 창구다. 예: 뿌리에 `memory.directory` 가 있으면
    load_global 병합으로 모든 에이전트가 그 한 디렉터리를 가리키게 되고 격리가 조용히 무너진다.
    그런 키는 이 함수로 자기 선언만 본다."""
    return dict(_own_global(global_dir()).get(name) or {})


def section(name: str, root: str | None = None) -> dict:
    """섹션 병합 뷰 — 프로젝트 > 글로벌, 키 단위 덮어쓰기. root=None 이면 글로벌만."""
    out = dict(load_global().get(name) or {})
    if root:
        out.update(load_project(root).get(name) or {})
    return out


# 설정을 쓰는 쪽은 한 줄로 선다. 스튜디오 서버는 요청마다 스레드를 띄우므로, 사용자가 설정을
# 연달아 바꾸면 읽기-고치기-쓰기가 겹친다. 겹치면 둘 다 잃는다 — 늦은 쪽이 이른 쪽의 섹션을
# 안 읽은 상태로 덮고, 임시 파일 이름이 같으면 두 벌의 JSON 이 한 파일에 섞여 파일이 깨진다.
_WRITE_LOCK = threading.RLock()


def _atomic_json(path: str, data: dict) -> None:
    """임시 파일은 쓰는 이마다 달라야 한다 — 이름이 pid 하나면 같은 프로세스의 두 스레드가
    같은 임시 파일에 겹쳐 쓴다(그 결과가 `}}` 로 끝나는 설정 파일이었다)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=f"{os.path.basename(path)}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def save_global(section_name: str, kv: dict) -> str:
    """글로벌 섹션 저장 — 섹션 **교체** (다른 섹션 불변; 구 save_config_section 계약 계승 —
    병합이면 배치 전환 시 낡은 키가 남는다). 최초 저장 시 구 config.toml 내용 자동 승계.

    쓰기는 **활성 에이전트의 파일에만** 한다 — 병합 뷰를 저장하면 뿌리의 값이 프로파일로
    복제돼, 뿌리를 고쳐도 안 따라오는 유령 사본이 된다."""
    with _WRITE_LOCK:  # 읽기-고치기-쓰기 한 벌 — 겹치면 나중 쓰기가 앞 섹션을 못 본 채 덮는다
        data = _own_global(global_dir())
        data[section_name] = {k: v for k, v in kv.items() if v is not None}
        _atomic_json(global_path(), data)
    return global_path()


def save_project(root: str, section_name: str, kv: dict, *, drop: tuple[str, ...] = ()) -> str:
    """프로젝트 섹션 저장 — save_global 과 동일 계약 (섹션 교체). 최초 저장 시 구 3파일 자동 승계.
    drop = 함께 제거할 구 섹션 키 (섹션 개명 이관용 — 구 키를 남기면 정본이 이원화된다)."""
    with _WRITE_LOCK:
        data = load_project(root)
        data[section_name] = {k: v for k, v in kv.items() if v is not None}
        for name in drop:
            data.pop(name, None)
        _atomic_json(project_path(root), data)
    return project_path(root)


# ── 런타임 상태 (설정 아님) — .asgard/state/ 격리 ──────────────────────────────────


def state_path(root: str, name: str, legacy: str | None = None) -> str:
    """상태 파일 경로 — state/ 신규 우선. 신규가 없고 레거시(.asgard/ 직하)가 있으면
    레거시를 반환해 구 세션 상태를 계속 읽는다 (쓰기 호출부는 새 경로를 만들며 이관)."""
    new = os.path.join(root, ".asgard", STATE_DIR, name)
    if legacy and not os.path.exists(new):
        old = os.path.join(root, ".asgard", legacy)
        if os.path.exists(old):
            return old
    return new


def ensure_state_dir(root: str) -> str:
    d = os.path.join(root, ".asgard", STATE_DIR)
    os.makedirs(d, exist_ok=True)
    return d


# ── 마이그레이션 (asgard sync) — 구 파일 → 신 구조, 멱등 ──────────────────────────────


def migrate_project(root: str) -> list[str]:
    """구 설정 3파일을 asgard-setting-project.json 으로, 런타임 잔재를 state/ 로 이관.
    반환 = 수행한 이관 설명 (없으면 빈 리스트). 구 파일은 이관 후 제거 (정본 이원화 방지)."""
    done: list[str] = []
    asg = os.path.join(root, ".asgard")
    if not os.path.isdir(asg):
        return done
    legacy = _load_legacy_project(root)
    if not os.path.exists(project_path(root)):
        if legacy:  # 주 경로 — 레거시 합성 뷰 그대로 신 파일로
            _atomic_json(project_path(root), legacy)
            done.append(f"settings → {PROJECT_FILE}")
    elif legacy:
        # 신 파일이 먼저 생긴 경우(init --force 후 sync 등) — 누락 섹션만 레거시에서 채운다.
        # 신 파일 우선 (사용자가 신 파일을 이미 만졌을 수 있다). 미채움 = 유실이므로 필수.
        data = _read_json(project_path(root)) or {}
        filled = [k for k in legacy if k not in data]
        if filled:
            for k in filled:
                data[k] = legacy[k]
            _atomic_json(project_path(root), data)
            done.append(f"legacy sections filled: {', '.join(filled)}")
    for name in (LEGACY_TOML, LEGACY_POLICY, LEGACY_MEMORY):
        p = os.path.join(asg, name)
        if os.path.exists(p) and os.path.exists(project_path(root)):
            with contextlib.suppress(OSError):
                os.remove(p)
                done.append(f"removed legacy {name}")
    moves = ("lagom-mode", "lagom-mode.json", "route-priors.json", "classify.jsonl", "memory-pending.json")
    for name in moves:
        old = os.path.join(asg, name)
        if os.path.exists(old):
            ensure_state_dir(root)
            new = os.path.join(asg, STATE_DIR, name)
            if not os.path.exists(new):
                with contextlib.suppress(OSError):
                    os.replace(old, new)
                    done.append(f"{name} → state/")
    return done


def migrate_global() -> list[str]:
    """구 ~/.asgard/config.toml → asgard-setting-global.json (구 파일은 보존 — 타 버전 공존 안전).

    이관 대상은 언제나 **기계 뿌리**다. 구 config.toml 은 프로파일 계층이 생기기 전 유물이라
    프로파일 홈에는 존재할 수 없고, 활성 에이전트를 따라가면 뿌리의 유산이 영영 안 옮겨진다."""
    machine = machine_dir()
    target = os.path.join(machine, GLOBAL_FILE)
    if os.path.exists(target):
        return []
    legacy = _read_toml(os.path.join(machine, LEGACY_TOML))
    if not legacy:
        return []
    _atomic_json(target, legacy)
    return [f"global settings → {GLOBAL_FILE}"]
