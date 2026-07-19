"""역할·딜리버리 표면 — 역할 프롬프트 본문, 티어 정책, 스킬 리졸버, 노트 주입.

Heimdall 코어에서 분리된 순수 조회 계층: 어떤 역할이 어떤 본문·모델 티어·스킬을 갖는지의
단일 소스. 세션 상태를 갖지 않는다 — 상태 있는 오케스트레이션은 core.Heimdall 몫.
"""

from __future__ import annotations

import os

from ... import theme, ui
from ...templates import agents_md
from ...templates.roles import ROLE_AGENTS, delivery_agents, role_writable

# 전이 상태 → [trinity.<role>] 설정 키 (역할별 provider 배치)
_ROLE_KEY = {
    "THINKER": "thinker",
    "THINKER_REPLAN": "thinker",
    "WORKER": "worker",
    "WORKER_RETRY": "worker",
    "VERIFIER": "verifier",
}

# ── 모델 티어 — 정책 tier → anthropic 모델. 상황별 호출: 역할 기본 + full-verify/재계획 승급.
# 명시 placement([trinity.<role>])와 알려지지 않은 커스텀 모델은 존중.
_TIER_MODELS = {
    "fast": "claude-haiku-4-5-20251001",
    "standard": "claude-sonnet-5",
    "high": "claude-opus-4-8",
    "max": "claude-fable-5",
}
_TIER_UP = {"fast": "standard", "standard": "high", "high": "max", "max": "max"}


def _model_tier(model: str) -> str | None:
    """Known Anthropic full IDs and CLI aliases -> policy tier; unknown IDs inherit unchanged."""
    name = model.lower()
    tiers = (("max", "fable"), ("high", "opus"), ("standard", "sonnet"), ("fast", "haiku"))
    return next((tier for tier, marker in tiers if marker in name), None)


# 탐색 발견 증류 넛지 문턱 — DIRECT 턴 커맨드 수가 이 이상이면 "탐색이 컸다"로 본다
_EXPLORE_NUDGE_MIN = 3
# 딜리버리 전문가 기본 티어 — role frontmatter `delivery:` 선언에서 파생 (CUS-251 선언화).
# 새 페르소나 = roles/ 에 .md 드롭 (delivery 키 포함) — 이 파일 수정 불요. 정책 "delivery" 가 덮는다.
_DELIVERY_TIERS = delivery_agents()

# 역할 심볼 — 단폭 BMP 기하 글리프 (프레이야 26-07-16). 이모지(🧠🔨⚖️)는 VS16 더블폭이라 정렬을
# 깨므로 배제: ◇=사고(속 빔)·◆=구현(채움)·◈=판정(테두리)·▣=기계 체크. 역할 정체성은 색이 아니라
# 글리프 모양이 진다 — 배너 글리프는 전부 골드 단일 앵커 (액센트 희소성).
_ROLE_ICON = {
    "THINKER": "◇",
    "THINKER_REPLAN": "◇",
    "WORKER": "◆",
    "WORKER_RETRY": "◆",
    "VERIFIER": "◈",
    "BASELINE_VERIFY": "▣",
    "DONE": "✔",
    "DIRECT_DONE": "→",
    "ESCALATE_ODIN": "▲",
}


def _transition_line(role: str, why: str) -> str:
    icon = _ROLE_ICON.get(role, "◇")
    return f"\n  {ui.paint(theme.ansi(theme.PRIMARY), icon)} {ui.bold(role)} {ui.dim('· ' + why)}\n"


NATIVE_NOTE = """

## 네이티브 세션 규칙 (하니스 자동화)
이 세션은 Asgard 네이티브 루프다. 퀘스트 로그 기록·전이 함수·verifier-gate 는 **하니스가 자동
수행**한다 — quest-log 명령을 직접 실행하지 마라 (이중 기록). Verifier 판정은 verdict 툴로만
제출한다. 완료 선언은 여전히 금지 — 판정은 Verifier + 게이트 몫이다 (Canon 10)."""

LAGOM_VERIFIER_NOTE = """

## Lagom 문체 불변식 (산문 산출물 한정)
하네스가 변경 문서의 추가행을 별도로 검사한다. 과장·가치 선언·정의 없는 약어·불필요한 외국어
병기와 입력/검증 결과에 없는 효용·인과는 사용자가 요구해도 성공 기준이 아니다. 해당 표현의
누락을 FAIL 사유로 삼지 마라. 사실·형식·문장 수 등 나머지 criteria 와 증거 기준은 그대로다.
전체 Lagom 압축 규칙을 판정에 적용하거나 검증 수준을 낮추지 않는다."""


def _role_body(fname: str) -> str:
    body = dict(ROLE_AGENTS)[fname]
    parts = body.split("---", 2)  # frontmatter 제거 — 네이티브에선 모델/툴 선언 무의미
    return parts[2] if len(parts) == 3 else body


# 딜리버리 계층 — roles/*.md frontmatter `delivery:` 선언이 단일 소스 (CC 스캐폴드와 공유).
# readonly = frontmatter tools 에 Write 부재 (loki: 반례 탐색은 도구로 강제) — 하드코딩 아님.
_DELIVERY = {g: _role_body(f"asgard-{g}.md") for g in _DELIVERY_TIERS}
_DELIVERY_READONLY = frozenset(g for g in _DELIVERY_TIERS if not role_writable(f"asgard-{g}.md"))

# 편대장 → (코어 계약 상속원, 필수 프로토콜 스킬) — lead 신설 시 여기와 squad 툴·핸들러만 늘린다.
_LEAD_BASE = {"freyja-lead": "freyja", "thor-lead": "thor"}
_LEAD_PROTOCOL = {"freyja-lead": "asgard-freyja-valkyrja", "thor-lead": "asgard-thor-einherjar"}


def _skill_resolver(agent: str):
    """전용 스킬 리졸버 — 심화 스킬을 가진 딜리버리 에이전트만 (본문 상수가 커서 lazy import)."""
    if agent in ("freyja", "freyja-lead"):
        from ...templates.freyja import resolve_freyja_skills

        return resolve_freyja_skills
    if agent in ("thor", "thor-lead"):
        from ...templates.thor import resolve_thor_skills

        return resolve_thor_skills
    if agent == "eitri":
        from ...templates.eitri import resolve_eitri_skills

        return resolve_eitri_skills
    if agent == "mimir":
        from ...templates.mimir import resolve_mimir_skills

        return resolve_mimir_skills
    return None


def _worker_note(task: str) -> str:
    """번들 Worker 공통 스킬 주입 (디버깅·테스트 설계) — Worker 표면 한정.

    딜리버리 전용 스킬(_skill_resolver)의 Worker 층 등가물 — 네이티브엔 파일 스킬 로더가
    없으므로 task 매칭 본문을 system 에 직접 주입한다. Verifier/loki 호출측은 부르지 않는다
    (게이트 무결성). 실패는 조용히 빈 문자열 (fail-open)."""
    try:
        from ...templates.worker import resolve_worker_skills

        hits = resolve_worker_skills(task)
        if not hits:
            return ""
        return "\n\n# 공통 스킬 (task 매칭 주입)\n\n" + "\n\n".join(b for _, b in hits)
    except Exception:
        return ""


def _mimir_note(request: str) -> str:
    """미미르 안내 계약 주입 — 코드 이해·설명 요청의 DIRECT 턴 한정.

    DIRECT 는 dispatch 툴이 없는 read-only 단일 세션이다 (write 에이전트 혼입 금지) —
    설명 과업의 미미르 계약(실행 흐름 서사 + 인지부채 방어)을 모드 A 처럼 인라인 주입한다.
    무매칭·실패는 조용히 빈 문자열 (fail-open — 일반 DIRECT 문답은 그대로)."""
    try:
        from ...templates.mimir import mimir_note

        return mimir_note(request)
    except Exception:
        return ""


def _identity(root: str) -> str:
    p = os.path.join(root, "AGENTS.md")
    if os.path.exists(p):
        try:
            return open(p, encoding="utf-8").read() + NATIVE_NOTE
        except Exception:
            pass
    return agents_md(os.path.basename(root)) + NATIVE_NOTE  # 내장 정체성 (스캐폴드 불요)


def _role_prompt(fname: str) -> str:
    return _role_body(fname) + NATIVE_NOTE
