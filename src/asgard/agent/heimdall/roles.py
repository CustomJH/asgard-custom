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
제출한다. 완료 선언은 여전히 금지 — 판정은 Verifier + 게이트 몫이다 (Canon 10).
파이썬 실행은 프로젝트 인터프리터로 한다 — uv 프로젝트(`uv.lock` 존재)면 `uv run pytest`·
`uv run python -m …`·`uv run python -c '…'`, 아니면 `python -m …`. 시스템 `python3` 직접
호출은 프로젝트 의존성을 못 보므로 금지다 (설치 시 uv 가 환경을 이미 세팅해 두었다)."""

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

# 편대장 → 코어 계약 상속원 — lead 신설 시 여기와 squad 툴·핸들러만 늘린다.
_LEAD_BASE = {"freyja-lead": "freyja", "thor-lead": "thor"}


SKILL_LOAD_TOOL: dict = {
    "name": "load_skill",
    "description": "Load one assigned Asgard skill body or one referenced text resource on demand.",
    "x-asgard-capability": "inspect",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Exact name from <available_skills>."},
            "resource": {"type": "string", "description": "Optional relative resource path."},
        },
        "required": ["name"],
    },
}


def _skill_support(
    agent: str,
    root: str | None = None,
    *,
    include_learned: bool = True,
    exclude: tuple[str, ...] = (),
) -> tuple[str, list[dict], dict]:
    """Return compact discovery context plus a guarded on-demand loader for one native role."""
    from ...skill_registry import load_skill_for_agent, skill_catalog

    if agent not in ("worker", "freyja", "freyja-lead", "thor", "thor-lead", "eitri", "mimir"):
        return "", [], {}
    project = root or os.getcwd()
    catalog = skill_catalog(project, agent, include_learned=include_learned, exclude=exclude)
    if not catalog:
        return "", [], {}

    def load(inp: dict) -> str:
        return load_skill_for_agent(
            project,
            agent,
            str(inp.get("name") or ""),
            str(inp["resource"]) if inp.get("resource") else None,
            include_learned=include_learned,
            exclude=exclude,
        )

    return catalog, [SKILL_LOAD_TOOL], {"load_skill": load}


def _delivery_matches(root: str, task: str) -> dict[str, list[tuple[str, str]]]:
    """과업 텍스트에 결정론 매칭된 딜리버리 정본 스킬 (agent → [(name, description)]).

    실패는 조용히 빈 결과 (fail-open) — 무매칭 과업은 어느 노트도 만들지 않는다."""
    from ...skill_registry import available_skills, resolve_skills

    matches: dict[str, list[tuple[str, str]]] = {}
    for agent in ("thor", "freyja", "eitri"):
        try:
            matched = [name for name, _ in resolve_skills(root, task, agent, include_learned=False)]
            if not matched:
                continue
            rows = {row["name"]: str(row.get("description") or "") for row in available_skills(root, agent)}
        except Exception:
            continue
        matches[agent] = [(name, rows.get(name, "")) for name in matched]
    return matches


def delivery_canon_note(root: str, task: str) -> str:
    """Thinker 계획 컨텍스트 — 과업에 매칭된 딜리버리 정본 스킬의 존재를 알린다.

    외부 모드(CC/Codex/Cursor)는 코디네이터가 스킬 카탈로그를 보고 위임 브리프에 정본 로드를
    명시하지만, 네이티브 Thinker 는 딜리버리 스킬 표면이 없어 저장소 문서 검색만으로 "정본
    부재"를 확정하고 형태(응답 구조·계층 배치)를 발명해 verify 계약으로 고정할 수 있다.
    결정론 리졸버로 이 과업에 매칭된 정본만 이름+설명으로 주입한다 — 무매칭 과업은 빈 문자열
    (토큰 회귀 없음)."""
    lines = [
        f"  - {agent} · {name}: {desc[:220]}"
        for agent, skills in _delivery_matches(root, task).items()
        for name, desc in skills
    ]
    if not lines:
        return ""
    return (
        "\n\n## 딜리버리 정본 (계획 구속 — 이 과업에 매칭됨)\n"
        "정책·컨벤션 정본은 저장소 문서가 아니라 Asgard 스킬 레지스트리에 있다. 저장소에서 정본"
        " 문서를 못 찾은 것은 정본 부재가 아니다. 이 과업에 매칭된 딜리버리 정본:\n"
        "<delivery_canon>\n" + "\n".join(lines) + "\n</delivery_canon>\n"
        "계획 규칙: 정본이 소유한 형태(응답 구조·계층 배치·명명·컨벤션)를 계획이 직접 확정하지"
        " 마라 — 해당 단위는 그 딜리버리 전문가에게 dispatch 되도록 계획하고 단위 브리프에 위"
        " 스킬 이름을 명시한다. criteria/verify 계약은 검증 가능한 표면(파일 존재·계층 위치·"
        "정본 준수 여부)만 고정하고, 계획이 가정한 필드명·코드값을 못박지 않는다."
    )


def worker_canon_hint(root: str, task: str) -> str:
    """Worker 착수 힌트 — 정본이 전문가 소유일 때 관찰-정지 대신 dispatch 를 지시한다.

    실증 근거(26-07-21): 정본 스킬이 thor 전용이라 worker 직접 로드가 거부되자 "형태 미결정"으로
    관찰만 하다 no-op 종료 (3/3 재현) — 턴 예산의 절반을 태우는 착수 정지."""
    matched = _delivery_matches(root, task)
    if not matched:
        return ""
    owners = "; ".join(f"{agent}: {', '.join(name for name, _ in skills)}" for agent, skills in matched.items())
    return (
        f"\n\n딜리버리 정본 힌트 — 이 과업 도메인의 정책 정본({owners})은 해당 전문가 소유라"
        " 직접 로드가 거부될 수 있다. 형태(응답 구조·계층 배치·명명) 미결정을 이유로 관찰만 하다"
        " 빈손으로 끝내지 마라 — 그 단위를 dispatch 로 소유 전문가에게 위임해 정본대로 확정·구현하게 하라."
    )


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
