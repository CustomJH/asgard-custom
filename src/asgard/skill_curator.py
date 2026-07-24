"""learned 스킬 큐레이터 — 수명주기 결정론 전이 (26-07-24).

learned 스킬 뱅크(.asgard/skills/)의 노화를 결정론으로 판정한다: active → stale(30일 무사용)
→ archive 후보(90일 무사용). LLM 없음 — 판정 원료는 usage 기록(skill_bank.record_use)과
SKILL.md 의 created 뿐이다.

안전 계약:
- 출처 게이팅: frontmatter origin 이 학습 계열(retrospective/learned/norn)인 스킬만 손댄다.
  수동 설치·허브 스킬은 읽기 전용 — 큐레이터의 관할이 아니다.
- pinned: true 스킬은 모든 전이에서 면제된다 (사용자 고정).
- 유예 플로어: 한 번도 안 쓰인 스킬의 기준 시점은 created — "사용 증거의 부재"는
  생성 직후엔 노화의 증거가 아니다.
- 최대 파괴 행위 = 아카이브 (evolution.archive_skill — 복원 가능). 삭제 없음.
- 기본은 드라이런 보고 — 실제 전이는 --apply 명시 시에만.
"""

from __future__ import annotations

import datetime as _dt
import os

from .skill_bank import SKILL_FILE, parse_skill_md
from .skill_bank import usage as _usage

STALE_DAYS = 30
ARCHIVE_DAYS = 90
_CURATED_ORIGINS = frozenset({"retrospective", "learned", "norn"})
_TRUTHY = frozenset({"true", "yes", "1", "on"})


def _parse_date(value: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(value.strip()[:10])
    except ValueError, AttributeError:
        return None


def curate(root: str, apply: bool = False) -> dict:
    """learned 스킬 노화 판정 (+선택 전이). 반환 = {"findings": [...], "archived": [...]}.

    finding = {name, state, origin, pinned, last_activity, idle_days, reason}.
    state ∈ active | stale | archive-candidate | exempt-pinned | skipped-origin | unreadable.
    apply=True 면 archive-candidate 를 실제 보관 전이한다 (아카이브 = 복원 가능)."""
    skills_dir = os.path.join(root, ".asgard", "skills")
    today = _dt.date.today()
    uses = _usage(root)
    findings: list[dict] = []
    archived: list[str] = []
    if not os.path.isdir(skills_dir):
        return {"findings": findings, "archived": archived}
    for name in sorted(os.listdir(skills_dir)):
        if name.startswith("."):
            continue  # .archive 등 숨김
        path = os.path.join(skills_dir, name, SKILL_FILE)
        try:
            parsed = parse_skill_md(open(path, encoding="utf-8").read())
        except OSError:
            parsed = None
        if not parsed:
            findings.append({"name": name, "state": "unreadable", "reason": "SKILL.md missing or malformed"})
            continue
        meta, _body = parsed
        origin = str(meta.get("origin") or "").strip().lower()
        pinned = str(meta.get("pinned") or "").strip().lower() in _TRUTHY
        entry = {"name": name, "origin": origin, "pinned": pinned}
        if origin not in _CURATED_ORIGINS:
            findings.append(
                {**entry, "state": "skipped-origin", "reason": "manually installed — curator never touches it"}
            )
            continue
        if pinned:
            findings.append({**entry, "state": "exempt-pinned", "reason": "pinned by user"})
            continue
        # 활동 앵커 — 마지막 사용, 없으면 created (유예 플로어: 미사용 ≠ 노화, 나이가 판정한다)
        last_used = _parse_date(str((uses.get(name) or {}).get("last_used") or ""))
        created = _parse_date(str(meta.get("created") or ""))
        anchor = max(filter(None, (last_used, created)), default=None)
        if anchor is None:
            findings.append(
                {**entry, "state": "active", "last_activity": "", "idle_days": 0, "reason": "no dates — kept"}
            )
            continue
        idle = (today - anchor).days
        if idle >= ARCHIVE_DAYS:
            state, reason = "archive-candidate", f"{idle}d idle (≥{ARCHIVE_DAYS}d)"
        elif idle >= STALE_DAYS:
            state, reason = "stale", f"{idle}d idle (≥{STALE_DAYS}d)"
        else:
            state, reason = "active", f"{idle}d idle"
        findings.append(
            {**entry, "state": state, "last_activity": anchor.isoformat(), "idle_days": idle, "reason": reason}
        )
        if apply and state == "archive-candidate":
            from .evolution import archive_skill

            ok, _msg = archive_skill(root, name)
            if ok:
                archived.append(name)
    return {"findings": findings, "archived": archived}
