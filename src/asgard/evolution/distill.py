"""pending 초안의 LLM 재작성 (opt-in) — 실패하면 결정론 초안이 그대로 남는다."""

from __future__ import annotations

import os

from .. import io_files
from ..skill_bank import SKILL_FILE, parse_skill_md
from .inbox import show
from .store import PENDING, _evo_dir

_POLISH_SYS = (
    "스킬 초안 편집기. 입력은 에이전트 세션의 실측 증거로 만든 SKILL.md 초안이다. "
    "같은 SKILL.md 형식으로만 다시 써서 출력한다 (설명·코드펜스 금지, --- frontmatter로 시작). "
    "규칙: (1) 증거에 없는 사실을 지어내지 않는다 — 전략·함정 서술을 일반화 가능한 원칙 문장으로 "
    "다듬는 것만 허용. (2) frontmatter의 name/agent/origin/created/evidence는 그대로 보존. "
    "(3) triggers는 재발 상황을 잡을 실질 키워드로 개선 가능. (4) description은 한 문장. "
    "(5) 환경 의존 실패·도구에 대한 부정 주장은 쓰지 않는다."
)


def polish(root: str, cid: str) -> tuple[bool, str]:
    """LLM 증류 (opt-in) — pending 초안을 원칙 수준 서술로 다듬는다. 실패 = 초안 유지 (fail-open).

    닫힌 과업이다: LLM은 초안 '재작성'만 한다 — 스킬 가치 판단(승인)은 여전히 사용자 몫이고,
    산출물은 pending에 머무른다 (LLM open-ended 판단 금지, CUS-251)."""
    draft = show(root, cid)
    if draft is None:
        return False, f"후보 없음: {cid}"
    try:
        from ..agent.oneshot import complete_once

        raw = complete_once(root, _POLISH_SYS, draft, max_tokens=3000)
    except RuntimeError as e:  # provider 미충족 — 사전 조건 메시지 그대로
        return False, str(e)
    except Exception as e:
        return False, f"LLM 호출 실패 — 결정론 초안 유지 ({type(e).__name__})"
    start = raw.find("---")
    parsed = parse_skill_md(raw[start:]) if start != -1 else None
    if not parsed:
        return False, "LLM 출력이 SKILL.md 형식이 아님 — 결정론 초안 유지"
    old_meta, _ = parse_skill_md(draft) or ({}, "")
    new_meta, _ = parsed
    if str(new_meta.get("name")) != str(old_meta.get("name")):
        return False, "LLM이 보존 필드(name)를 바꿈 — 결정론 초안 유지 (satisficing backstop)"
    p = _evo_dir(root, PENDING, cid, SKILL_FILE)
    orig = f"{p}.orig"
    if not os.path.exists(orig):  # 결정론 초안 백업 — latch 때문에 재생성 불가, 내용 열화 시 복구선
        io_files.write_text(orig, draft)
    io_files.write_text(p, raw[start:].rstrip() + "\n")
    return True, f"증류 완료 — {cid} 초안이 다듬어졌다 (여전히 pending, 승인 필요. 원본: SKILL.md.orig)"
