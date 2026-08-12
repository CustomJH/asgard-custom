"""learned 스킬 큐레이터 — 수명주기 결정론 전이 (26-07-24).

learned 스킬 뱅크(.asgard/skills/)의 노화를 결정론으로 판정한다: active → stale(30일 무사용)
→ archive 후보(90일 무사용). LLM 없음 — 판정 원료는 usage 기록(skill_bank.record_use)과
SKILL.md의 created 뿐이다.

안전 계약:
- 출처 게이팅: frontmatter origin이 학습 계열(retrospective/learned/norn)인 스킬만 손댄다.
  수동 설치·허브 스킬은 읽기 전용 — 큐레이터의 관할이 아니다.
- pinned: true 스킬은 모든 전이에서 면제된다 (사용자 고정).
- 유예 플로어: 한 번도 안 쓰인 스킬의 기준 시점은 created — "사용 증거의 부재"는
  생성 직후엔 노화의 증거가 아니다.
- 최대 파괴 행위 = 아카이브 (evolution.archive_skill — 복원 가능). 삭제 없음.
- 기본은 드라이런 보고 — 실제 전이는 --apply 명시 시에만.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os

from . import io_files
from .skill_bank import SKILL_FILE, parse_skill_md
from .skill_bank import usage as _usage

STALE_DAYS = 30
ARCHIVE_DAYS = 90
_CURATED_ORIGINS = frozenset({"retrospective", "learned", "norn"})
_TRUTHY = frozenset({"true", "yes", "1", "on"})
_NUDGE_STATE = ("state", "skill-curate.json")


def _parse_date(value: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(value.strip()[:10])
    except ValueError, AttributeError:
        return None


def curate(root: str, apply: bool = False) -> dict:
    """learned 스킬 노화 판정 (+선택 전이). 반환 = {"findings": [...], "archived": [...]}.

    finding = {name, state, origin, pinned, last_activity, idle_days, reason}.
    state ∈ active | stale | archive-candidate | exempt-pinned | skipped-origin | unreadable.
    apply=True 면 archive-candidate를 실제 보관 전이한다 (아카이브 = 복원 가능)."""
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
            with open(path, encoding="utf-8") as handle:
                parsed = parse_skill_md(handle.read())
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


def _latched(root: str, digest: str) -> bool:
    """같은 후보 집합으로 두 번 말하지 않는다. 표식을 못 남기면 침묵한다 — 되풀이가 침묵보다 나쁘다."""
    path = os.path.join(root, ".asgard", *_NUDGE_STATE)
    try:
        if (io_files.read_json(path) or {}).get("digest") == digest:
            return True
    except AttributeError:
        pass
    try:
        io_files.write_json(path, {"digest": digest}, indent=None)
    except OSError:
        return True
    return False


def wake(root: str) -> str | None:
    """턴이 끝난 자리에서 부르는 노후 신호 — 사람에게 보일 한 줄, 또는 None(침묵).

    노른·패턴의 wake 와 같은 계약이되 자식을 안 띄운다: 판정 원료가 SKILL.md 몇 개와 usage
    파일뿐이라 (LLM 도 임베더도 없다) 스폰 값이 판정 값보다 비싸다.

    자율 등급이 off 가 아니면 보관까지 적용한다. 보관이 자율의 상한인 이유는 그것이 이 층에서
    할 수 있는 가장 센 일이면서 되돌아오기 때문이다 — 삭제는 없고, `evolve restore` 가 최신
    스냅샷을 그대로 되돌린다. 손대는 대상도 학습 계열 origin 으로 이미 좁혀져 있어 사람이
    손으로 깐 스킬은 어느 등급에서도 안 건드린다.

    26-08-12 이전에는 이 판정에 부르는 손이 없었다 — `curate` 의 호출자가 CLI 하나뿐이라
    아무도 치지 않으면 학습 스킬은 영영 늙지 않았다."""
    from .evolution import autonomy_mode

    try:
        result = curate(root, apply=autonomy_mode() != "off")
    except OSError:
        return None
    archived = result["archived"]
    if archived:
        names = ", ".join(archived[:2]) + (f" 외 {len(archived) - 2}건" if len(archived) > 2 else "")
        return (
            f"진화 — {ARCHIVE_DAYS}일 넘게 안 쓰인 학습 스킬 {len(archived)}건을 보관했다 ({names}). "
            "되돌리려면 `asgard evolve restore <이름>`."
        )
    waiting = sorted(f["name"] for f in result["findings"] if f["state"] in ("archive-candidate", "stale"))
    if not waiting:
        return None
    if _latched(root, hashlib.sha1("\0".join(waiting).encode()).hexdigest()):
        return None
    names = ", ".join(waiting[:2]) + (f" 외 {len(waiting) - 2}건" if len(waiting) > 2 else "")
    if autonomy_mode() == "off":
        return (
            f"진화 — 학습 스킬 {len(waiting)}건이 {STALE_DAYS}일 넘게 안 쓰였다 ({names}). "
            "`asgard evolve curate` 로 보고, `--apply` 로 보관한다."
        )
    return (
        f"진화 — 학습 스킬 {len(waiting)}건이 {STALE_DAYS}일 넘게 안 쓰였다 ({names}). "
        f"{ARCHIVE_DAYS}일이 되면 스스로 보관한다."
    )
