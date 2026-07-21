"""통합 설정 (26-07-15 유저 확정) — 글로벌/프로젝트 각 1파일 + 런타임 state/ 격리.

  글로벌   ~/.asgard/asgard-setting-global.json     (구 ~/.asgard/config.toml)
  프로젝트 <root>/.asgard/asgard-setting-project.json (구 config.toml + trinity-policy.json
                                                       + memory-server.json 흡수)
  런타임   <root>/.asgard/state/                     (lagom-mode·route-priors·classify·
                                                       writes-*·memory-pending — 설정 아님)

섹션 스키마 (양쪽 동일 — 프로젝트가 글로벌을 키 단위로 이긴다):
  provider / trinity(네이티브 역할 배치) / agent_models(호스트별 역할 모델) / bridge /
  lagom / memory / ui / trinity_policy(프로젝트 전용)

레거시 폴백: 신규 JSON 이 없으면 구 파일을 그대로 읽는다 (기배포 프로젝트·기존 테스트 무파손).
쓰기는 항상 신규 JSON — `asgard sync` 가 구 파일을 신 포맷으로 이관한다.
훅(standalone)은 이 모듈을 임포트하지 못한다 — 같은 "신규 우선+폴백" 규칙을 각 훅이 내장하며
"동일 유지 (단일 출처 원칙)" 주석으로 이 파일을 가리킨다.
"""

from __future__ import annotations

import contextlib
import json
import os
import tomllib

GLOBAL_FILE = "asgard-setting-global.json"
PROJECT_FILE = "asgard-setting-project.json"
STATE_DIR = "state"
# 레거시 (폴백 전용 — 쓰기 금지)
LEGACY_TOML = "config.toml"
LEGACY_POLICY = "trinity-policy.json"
LEGACY_MEMORY = "memory-server.json"


def global_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".asgard")


def global_path() -> str:
    return os.path.join(global_dir(), GLOBAL_FILE)


def project_path(root: str) -> str:
    return os.path.join(root, ".asgard", PROJECT_FILE)


def _read_json(path: str) -> dict | None:
    try:
        d = json.load(open(path, encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _read_toml(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def load_global() -> dict:
    """글로벌 설정 — 신규 JSON 우선, 없으면 구 config.toml (섹션 구조 동일해 그대로 사용)."""
    d = _read_json(global_path())
    if d is not None:
        return d
    return _read_toml(os.path.join(global_dir(), LEGACY_TOML))


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


def section(name: str, root: str | None = None) -> dict:
    """섹션 병합 뷰 — 프로젝트 > 글로벌, 키 단위 덮어쓰기. root=None 이면 글로벌만."""
    out = dict(load_global().get(name) or {})
    if root:
        out.update(load_project(root).get(name) or {})
    return out


def _atomic_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def save_global(section_name: str, kv: dict) -> str:
    """글로벌 섹션 저장 — 섹션 **교체** (다른 섹션 불변; 구 save_config_section 계약 계승 —
    병합이면 배치 전환 시 낡은 키가 남는다). 최초 저장 시 구 config.toml 내용 자동 승계."""
    data = load_global()
    data[section_name] = {k: v for k, v in kv.items() if v is not None}
    _atomic_json(global_path(), data)
    return global_path()


def save_project(root: str, section_name: str, kv: dict) -> str:
    """프로젝트 섹션 저장 — save_global 과 동일 계약 (섹션 교체). 최초 저장 시 구 3파일 자동 승계."""
    data = load_project(root)
    data[section_name] = {k: v for k, v in kv.items() if v is not None}
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
    """구 ~/.asgard/config.toml → asgard-setting-global.json (구 파일은 보존 — 타 버전 공존 안전)."""
    if os.path.exists(global_path()):
        return []
    legacy = _read_toml(os.path.join(global_dir(), LEGACY_TOML))
    if not legacy:
        return []
    _atomic_json(global_path(), legacy)
    return [f"global settings → {GLOBAL_FILE}"]
