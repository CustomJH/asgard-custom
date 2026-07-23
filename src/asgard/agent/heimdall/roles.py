"""역할·딜리버리 표면 — 역할 프롬프트 본문, 티어 정책, 스킬 리졸버, 노트 주입.

Heimdall 코어에서 분리된 순수 조회 계층: 어떤 역할이 어떤 본문·모델 티어·스킬을 갖는지의
단일 소스. 세션 상태를 갖지 않는다 — 상태 있는 오케스트레이션은 core.Heimdall 몫.
"""

from __future__ import annotations

import os
import re

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

## Native session rules (harness automation)
This session is the Asgard native loop. Quest log recording, the transition function, and the
verifier-gate are **performed automatically by the harness** — do not run quest-log commands
yourself (double recording). Verifier verdicts are submitted only via the verdict tool.
Declaring completion is still forbidden — the verdict belongs to the Verifier + gate (Canon 10).
Run Python with the project interpreter — in a uv project (`uv.lock` present) use `uv run pytest`,
`uv run python -m …`, `uv run python -c '…'`; otherwise `python -m …`. Calling the system
`python3` directly is forbidden — it cannot see project dependencies (uv already set up the
environment at install time).
Do not use emoji pictograms in user-visible text — when a marker is needed, use text glyphs
(✓ ⚠ ✗ ▸ · ⠶) only."""

LAGOM_VERIFIER_NOTE = """

## Lagom prose invariants (prose deliverables only)
The harness separately inspects the added lines of changed documents. Hyperbole, value
declarations, undefined abbreviations, unnecessary foreign-language glosses, and benefits or
causality absent from the input/verification results are not success criteria even if the user
asked for them. Do not treat the absence of such expressions as a FAIL reason. All remaining
criteria and evidence standards — facts, format, sentence counts — stay unchanged. Do not apply
the full Lagom compression rules to the verdict or lower the verification bar."""


def _role_body(fname: str) -> str:
    body = dict(ROLE_AGENTS)[fname]
    parts = body.split("---", 2)  # frontmatter 제거 — 네이티브에선 모델/툴 선언 무의미
    return parts[2] if len(parts) == 3 else body


# 딜리버리 계층 — roles/*.md frontmatter `delivery:` 선언이 단일 소스 (CC 스캐폴드와 공유).
# readonly = frontmatter tools 에 Write 부재 (loki: 반례 탐색은 도구로 강제) — 하드코딩 아님.
_DELIVERY = {g: _role_body(f"asgard-{g}.md") for g in _DELIVERY_TIERS}
_DELIVERY_READONLY = frozenset(g for g in _DELIVERY_TIERS if not role_writable(f"asgard-{g}.md"))

# 편대장 → 코어 계약 상속원.
_LEAD_BASE = {"thor-lead": "thor"}


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


MEMORY_SAVE_TOOL: dict = {
    "name": "memory_save",
    "description": (
        "Persist one self-contained fact the user explicitly asked to remember into personal memory "
        "(Yggdrasil). Call once per fact. Never claim a fact was remembered without calling this."
    ),
    # 개인 메모리는 워크스페이스 밖(~/.asgard/memory) — repo readonly 강제와 무관하게 DIRECT 에서
    # 실행 가능해야 한다. mutate 로 태그하면 direct 역할({inspect, execute})이 차단한다.
    "x-asgard-capability": "execute",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "One self-contained fact — one or two sentences, "
                "no deictic words or imperative phrasing.",
            },
            "kind": {
                "type": "string",
                "enum": ["user", "note", "decision", "insight", "reference", "feedback"],
                "description": "Default user (a fact about the user).",
            },
        },
        "required": ["text"],
    },
}


def _memory_save_support(saved: list[tuple[str, str]]) -> tuple[str, list[dict], dict]:
    """기억 지시 턴 전용 저장 도구 — 사용자의 명시 지시가 곧 승인이라 ask-before-save 를 우회한다.

    ingest 는 위협·시크릿 스캔과 근사 중복 병합을 그대로 수행하고, 성공은 saved 에 기록된다 —
    core._direct 가 이 목록으로 실행 증거를 판정한다 (허위 "기억했다" 차단, 26-07-21 실측)."""

    def save(inp: dict) -> str:
        from ...memory import ingest

        text = str(inp.get("text") or "").strip()
        kind = str(inp.get("kind") or "user")
        try:
            action, slug = ingest(text, kind=kind)
        except Exception as e:
            return f"Save failed: {type(e).__name__}: {e}"
        saved.append((action, slug))
        return f"Saved: {slug} ({action})"

    note = (
        "\n\n## Memory-instruction turn — memory_save contract\n"
        "The user explicitly instructed you to remember (save) something this turn. Distill what "
        "should be remembered into self-contained facts and save them with the memory_save tool "
        "(call once per fact if there are several). Saying 'remembered/saved' without calling the "
        "tool is forbidden — a save only counts through the tool response. If the request is not a "
        "save instruction but a question about past memory, do not call memory_save; answer from "
        "what you know.\n"
    )
    return note, [MEMORY_SAVE_TOOL], {"memory_save": save}


def _skill_support(
    agent: str,
    root: str | None = None,
    *,
    task: str | None = None,
    include_learned: bool = True,
    exclude: tuple[str, ...] = (),
) -> tuple[str, list[dict], dict]:
    """Return compact discovery context plus a guarded on-demand loader for one native role."""
    from ...skill_registry import load_skill_for_agent, resolve_skills, skill_catalog

    if agent not in ("worker", "freyja", "thor", "thor-lead", "eitri", "mimir"):
        return "", [], {}
    project = root or os.getcwd()
    matched = None
    if task is not None:
        matched = set()
        for name, body in resolve_skills(project, task, agent, include_learned=include_learned):
            if name.endswith("-deferred"):
                matched.update(re.findall(r"^- `([^`]+)`", body, re.M))
            else:
                matched.add(name)
    catalog = skill_catalog(
        project,
        agent,
        include_learned=include_learned,
        exclude=exclude,
        matched=matched,
    )
    if not catalog:
        return "", [], {}

    def load(inp: dict) -> str:
        name = str(inp.get("name") or "")
        return load_skill_for_agent(
            project,
            agent,
            name,
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
        "\n\n## Delivery canon (binds the plan — matched to this quest)\n"
        "The canonical source for policy and conventions is the Asgard skill registry, not repo"
        " documents. Failing to find a canon document in the repository does not mean no canon"
        " exists. Delivery canon matched to this quest:\n"
        "<delivery_canon>\n" + "\n".join(lines) + "\n</delivery_canon>\n"
        "Planning rule: do not let the plan directly fix the shape the canon owns (response"
        " structure, layer placement, naming, conventions) — plan for those units to be dispatched"
        " to that delivery specialist and name the skill above in the unit brief. The"
        " criteria/verify contract pins only verifiable surfaces (file existence, layer location,"
        " canon compliance) and never nails down field names or code values the plan assumed."
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
        f"\n\nDelivery canon hint — the policy canon for this quest's domain ({owners}) is owned"
        " by that specialist, so loading it directly may be refused. Do not end empty-handed after"
        " only observing because the shape (response structure, layer placement, naming) is"
        " undecided — delegate that unit via dispatch to the owning specialist so they settle and"
        " implement it per the canon."
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
