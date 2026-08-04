"""Asgard agent library — the single home for role-agent definitions (grows as we add agents).

Each `*.md` here is a REAL agent file (frontmatter + body), edited as markdown with no escaping —
the same abstraction boundary `asgard.hooks` gives hook scripts. setup scaffolds each file verbatim
into the user's `.claude/agents/`. Add an agent = drop a `.md` file here; discovery is the directory
listing itself, so there is no registry to update."""

import json
from importlib import resources

from ..agent_models import agent_model

# (파일명, 내용) — setup이 .claude/agents/ 에 스캐폴딩. 역할 = 직관명(asgard-thinker/worker/verifier),
# 신화 이름은 딜리버리 계층(freyja/thor/eitri/loki) 전용 (2026-07-02 Odin 결정).
ROLE_AGENTS: list[tuple[str, str]] = sorted(
    (f.name, f.read_text(encoding="utf-8")) for f in resources.files(__package__).iterdir() if f.name.endswith(".md")
)

# 역할 문서가 어떻게 다시 쓰이든 살아남아야 하는 문구 — {파일명: ((문구, 왜), ...)}.
#
# 이 표가 있는 이유: 이 문서들은 산문이라 누구든 통째로 다시 쓸 수 있고, 그때 사라지는 것은
# 문장이 아니라 **계약**이다. 실제로 한 번 그랬다 (26-08-04): 판정자 문서가 41줄에서 105줄로
# 다시 쓰이면서 `not a verification waiver` 와 `read-only guard` 가 같이 사라졌다. 그때도 시험은
# 빨개졌지만 두 곳 다 **우연히** 그 문구를 쓰고 있었을 뿐이라(하나는 doctor 드리프트 카나리아의
# 치환 대상, 하나는 lagom 계약 검사), 무엇이 왜 깨졌는지는 아무 데도 안 적혀 있었다.
# 여기 적어 두면 문구가 빠지는 순간 그 역할과 사유를 대며 죽는다.
ROLE_CONTRACT_INVARIANTS: dict[str, tuple[tuple[str, str], ...]] = {
    "asgard-verifier.md": (
        ("lagom:", "마커 인지가 없으면 판정자가 선언된 절충을 미완성으로 FAIL 한다"),
        ("not a verification waiver", "마커가 기준 면제로 읽히면 lagom 주석 한 줄이 판정을 무력화한다"),
        ("is still FAIL", "마커가 있어도 미충족 기준·안전 예외·증거 부재는 그대로 FAIL 이다"),
        ("read-only guard", "판정자 Bash 허용목록의 유일한 안내 — 없으면 막힌 명령의 변형을 반복한다"),
        ("A PASS with no commands is void", "성공한 검증 명령 기록이 없는 PASS 는 게이트가 거부한다"),
    ),
}


def missing_role_invariants() -> list[str]:
    """계약 문구를 잃은 역할 문서 — `<파일명>: '<문구>' (<왜>)` 형태로.

    비어 있으면 모든 역할 문서가 자기 계약을 들고 있다."""
    bodies = dict(ROLE_AGENTS)
    return [
        f"{fname}: '{phrase}' 가 사라졌다 ({why})"
        for fname, pairs in ROLE_CONTRACT_INVARIANTS.items()
        for phrase, why in pairs
        if phrase not in bodies.get(fname, "")
    ]


def role_document(content: str) -> tuple[dict, str]:
    """Parse one canonical role file for client-specific adapters."""
    parts = content.split("---", 2)
    if len(parts) != 3:
        raise ValueError("role file requires YAML frontmatter")
    metadata = {
        key.strip(): value.strip()
        for line in parts[1].splitlines()
        if ":" in line
        for key, value in (line.split(":", 1),)
    }
    if not metadata.get("name") or not metadata.get("description"):
        raise ValueError("role file requires name and description")
    return metadata, parts[2].lstrip()


def claude_agent(content: str, root: str) -> str:
    """Apply Claude Code model overrides while preserving the canonical role document."""
    metadata, body = role_document(content)
    selected = agent_model(root, "claude-code", metadata["name"])
    lines = content.split("---", 2)[1].splitlines()
    keys = set()
    for index, line in enumerate(lines):
        key = line.split(":", 1)[0]
        if key in selected:
            lines[index] = f"{key}: {json.dumps(selected[key])}"
            keys.add(key)
    lines.extend(f"{key}: {json.dumps(value)}" for key, value in selected.items() if key not in keys)
    return "---\n" + "\n".join(lines).strip() + "\n---\n\n" + body


def delivery_agents() -> dict[str, str]:
    """딜리버리 계층 발견 — frontmatter `delivery: <tier>`를 선언한 role만 (CUS-251 선언화).

    반환 = {짧은 이름(예: freyja): tier(standard|fast)}. 새 딜리버리 페르소나 = `.md` 파일에
    delivery 키 하나 — heimdall 디스패치 enum·티어가 여기서 파생되므로 코드 수정이 없다.
    ullr처럼 delivery 키 없는 role은 네이티브 디스패치 대상이 아니다 (현행 의미 보존)."""
    out: dict[str, str] = {}
    for fname, body in ROLE_AGENTS:
        parts = body.split("---", 2)
        if len(parts) < 3:
            continue
        tier = next((ln.split(":", 1)[1].strip() for ln in parts[1].splitlines() if ln.startswith("delivery:")), None)
        if tier:
            out[fname.removeprefix("asgard-").removesuffix(".md")] = tier
    return out


def role_writable(fname: str) -> bool:
    """frontmatter tools 선언에 Write가 있으면 쓰기 가능 role — readonly 판정의 단일 소스."""
    parts = dict(ROLE_AGENTS)[fname].split("---", 2)
    tools = next((ln.split(":", 1)[1] for ln in parts[1].splitlines() if ln.startswith("tools:")), "")
    return "Write" in tools


def role_core_skill(fname: str, description: str) -> str:
    """모드 A(서브에이전트 부재 툴)용 코어 계약 스킬 — role `.md` 파일이 단일 소스.

    role frontmatter(모델·툴 선언)는 스킬에서 무의미하므로 스킬 frontmatter로 교체하고
    본문은 그대로 잇는다. Worker phase가 해당 도메인 하위작업에서 로드해 인라인 수행한다."""
    body = dict(ROLE_AGENTS)[fname].split("---", 2)[2].lstrip()
    name = fname.removesuffix(".md")
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"
