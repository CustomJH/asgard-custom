"""스웜 — 프로젝트가 루트의 에이전트를 **불러 쓰는** 자리 (오딘 확정 26-07-29).

경계가 이 파일의 요지다. 루트(`profiles.py`)는 에이전트가 **누구인가**를 소유한다 — 정체성과
1차 기억과 자기 설정. 프로젝트는 그걸 하나도 복제하지 않고 **어디에 세울지**만 적는다:

    .asgard/asgard-setting-project.json
    { "agents": {
        "default": "loki-qa",                                이 프로젝트의 대표 에이전트
        "modes":   {"native": "loki-qa", "codex": "saga-doc"},  모드별 고정 — 그 세션은 그 에이전트로만
        "roles":   {"worker": "freyja-ui", "verifier": "loki-qa"}   역할별 배치 = 스웜
    }}

`roles`가 스웜을 만든다. Trinity의 thinker·worker·verifier가 서로 다른 에이전트로 돌면
셋은 각자의 1차 기억을 갖는다 — Verifier가 Worker의 일지를 못 보므로 "내가 방금 그렇게
했으니 맞다"는 자기 확증이 구조적으로 불가능해진다. 역할 분리가 프롬프트 문구가 아니라
파일시스템 경계가 되는 자리다.

`[trinity.<role>]`(providers.py)와 축이 다르다 — 저쪽은 **어느 모델이** 그 역할을 도느냐,
이쪽은 **어느 에이전트가** 그 역할을 도느냐(정체성·기억·스킬)다. 둘은 곱해진다: 에이전트가
자기 홈의 `[provider]`/`[trinity]`를 갖고 있으면 그게 그 역할 턴의 모델을 정한다.

fail-open: 프로젝트 설정은 리포에 실려 다른 기계로 간다. 거기 없는 에이전트 이름이 적혀 있어도
**세션을 막지 않는다** — 기본으로 떨어지고, 무엇이 없어서 떨어졌는지는 `missing()`과 doctor가
말한다. 협업자의 기계에 내 에이전트가 없다고 그 사람 작업이 멈추면 이 계층은 순손실이다.
"""

from __future__ import annotations

import os

from .profiles import DEFAULT, ID_RE, exists, normalize, validate

SECTION = "agents"

# 세션을 여는 네 모드 — 모드 패리티(tests/test_mode_parity.py)와 같은 이름을 쓴다.
MODES = ("native", "claude-code", "cursor", "codex")


def _project(root: str) -> dict:
    try:
        from .settings import load_project

        raw = load_project(root).get(SECTION)
        return dict(raw) if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _name(value: object) -> str:
    """설정에서 읽은 에이전트 이름 정규화 — 미선언·형식 불량은 빈 문자열.

    빈 값을 `normalize`에 그냥 넘기면 안 된다: 거기서는 빈 입력이 DEFAULT로 접히므로
    "선언 안 함"과 "명시적으로 기본 에이전트를 지정"이 구분되지 않는다. 그러면 배치가 하나도
    없는 프로젝트가 `default`를 강제 선언한 것처럼 읽혀 루트의 활성 에이전트를 덮어쓴다
    (`asgard agent use loki-qa`를 해도 프로젝트 안에서만 기본으로 돌아가는 유령 결함)."""
    text = str(value or "").strip()
    if not text:
        return ""
    canon = normalize(text)
    if canon == DEFAULT:
        return DEFAULT
    return canon if ID_RE.match(canon) else ""


def binding(root: str) -> dict:
    """이 프로젝트의 배치 선언 — {default, modes{}, roles{}}. 형식 불량 키는 조용히 탈락."""
    raw = _project(root)
    raw_modes, raw_roles = raw.get("modes"), raw.get("roles")
    modes: dict = raw_modes if isinstance(raw_modes, dict) else {}
    roles: dict = raw_roles if isinstance(raw_roles, dict) else {}
    return {
        "default": _name(raw.get("default")),
        "modes": {k: n for k, v in modes.items() if k in MODES and (n := _name(v))},
        "roles": {str(k): n for k, v in roles.items() if (n := _name(v))},
    }


def resolve(root: str, *, mode: str | None = None, role: str | None = None) -> str:
    """이 자리에서 일할 에이전트 id — 좁은 선언이 넓은 선언을 이긴다.

    사다리: 역할 배치 > 모드 고정 > 프로젝트 대표 > 루트 활성(끈끈한 기본) > default.
    명시 env/`--agent`는 이 함수 위에 있다 (profiles.active()가 이미 반영)."""
    b = binding(root)
    if role:
        picked = b["roles"].get(role)
        if picked and exists(picked):
            return picked
    if mode:
        picked = b["modes"].get(mode)
        if picked and exists(picked):
            return picked
    if b["default"] and exists(b["default"]):
        return b["default"]

    from .profiles import active

    now = active()
    return now if now != "custom" else DEFAULT


def missing(root: str) -> list[dict]:
    """선언됐지만 이 기계에 없는 에이전트 — [{scope, key, agent}]. doctor가 읽는다.

    빈 목록 = 선언이 전부 살아 있다. 항목이 있으면 그 자리는 조용히 기본으로 떨어지고 있다."""
    b = binding(root)
    out: list[dict] = []
    if b["default"] and not exists(b["default"]):
        out.append({"scope": "default", "key": "", "agent": b["default"]})
    for key, agent in sorted(b["modes"].items()):
        if not exists(agent):
            out.append({"scope": "mode", "key": key, "agent": agent})
    for key, agent in sorted(b["roles"].items()):
        if not exists(agent):
            out.append({"scope": "role", "key": key, "agent": agent})
    return out


def swarm(root: str) -> dict[str, str]:
    """역할 → 에이전트 (존재하는 것만). 두 개 이상이면 이 프로젝트는 스웜으로 돈다."""
    return {k: v for k, v in binding(root)["roles"].items() if exists(v)}


def is_swarm(root: str) -> bool:
    """서로 다른 에이전트가 둘 이상 역할을 맡고 있는가 — 스웜 판정의 단일 소스."""
    return len(set(swarm(root).values())) > 1


def bind(
    root: str,
    agent: str,
    *,
    mode: str | None = None,
    role: str | None = None,
) -> dict:
    """배치 하나를 적는다. mode/role 둘 다 없으면 프로젝트 대표로.

    없는 에이전트는 여기서 거절한다 — 런타임은 fail-open 이어야 하지만, **적는 순간**은
    사람이 보고 있으므로 오타를 그때 잡는 편이 낫다 (조용히 기본으로 도는 걸 나중에 발견하느니)."""
    canon = validate(agent)
    if canon != DEFAULT and not exists(canon):
        raise FileNotFoundError(f"에이전트 {canon!r} 없음 — `asgard agent create {canon}`로 먼저 만들어라")
    if mode and role:
        raise ValueError("--mode와 --role은 함께 쓸 수 없다 (역할이 모드보다 좁다 — 하나만 골라라)")
    if mode and mode not in MODES:
        raise ValueError(f"mode는 {'/'.join(MODES)} 중 하나")

    raw = _project(root)
    if role:
        roles = dict(raw.get("roles") or {})
        roles[role] = canon
        raw["roles"] = roles
    elif mode:
        modes = dict(raw.get("modes") or {})
        modes[mode] = canon
        raw["modes"] = modes
    else:
        raw["default"] = canon
    return {"path": _save(root, raw), "binding": binding(root)}


def unbind(root: str, *, mode: str | None = None, role: str | None = None) -> dict:
    """배치 하나를 지운다 (둘 다 없으면 프로젝트 대표를 지운다)."""
    raw = _project(root)
    if role:
        roles = dict(raw.get("roles") or {})
        roles.pop(role, None)
        raw["roles"] = roles
    elif mode:
        modes = dict(raw.get("modes") or {})
        modes.pop(mode, None)
        raw["modes"] = modes
    else:
        raw.pop("default", None)
    return {"path": _save(root, raw), "binding": binding(root)}


def _save(root: str, raw: dict) -> str:
    from .settings import save_project

    clean = {k: v for k, v in raw.items() if v not in (None, "", {}, [])}
    return save_project(root, SECTION, clean)


def scoped_for(root: str, *, mode: str | None = None, role: str | None = None):
    """`with scoped_for(root, role="worker"): ...` — 그 턴 동안만 그 에이전트의 홈.

    os.environ이 아니라 contextvar를 쓴다 (profiles.scoped) — 한 프로세스가 역할별로 다른
    에이전트를 병렬로 돌릴 때 환경변수는 서로를 덮어쓴다."""
    from .profiles import scoped

    return scoped(resolve(root, mode=mode, role=role))


def describe(root: str) -> dict:
    """사람·doctor·CLI가 함께 읽는 요약 — 선언 + 실효 + 결손 한 판."""
    b = binding(root)
    return {
        "binding": b,
        "effective": {
            "session": resolve(root),
            "modes": {m: resolve(root, mode=m) for m in MODES},
            "roles": {r: resolve(root, role=r) for r in sorted(b["roles"])},
        },
        "swarm": is_swarm(root),
        "missing": missing(root),
        "root": os.path.realpath(root),
    }
