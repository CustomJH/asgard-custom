"""Asgard agent library — the single home for role-agent definitions (grows as we add agents).

Each `*.md` here is a REAL agent file (frontmatter + body), edited as markdown with no escaping —
the same abstraction boundary `asgard.hooks` gives hook scripts. setup scaffolds each file verbatim
into the user's `.claude/agents/`. Add an agent = drop a `.md` file here; discovery is the directory
listing itself, so there is no registry to update."""

from importlib import resources

# (파일명, 내용) — setup 이 .claude/agents/ 에 스캐폴딩. 역할 = 직관명(asgard-thinker/worker/verifier),
# 신화 이름은 딜리버리 계층(freyja/thor/eitri/loki) 전용 (2026-07-02 Odin 결정).
ROLE_AGENTS: list[tuple[str, str]] = sorted(
    (f.name, f.read_text(encoding="utf-8")) for f in resources.files(__package__).iterdir() if f.name.endswith(".md")
)


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


def delivery_agents() -> dict[str, str]:
    """딜리버리 계층 발견 — frontmatter `delivery: <tier>` 를 선언한 role 만 (CUS-251 선언화).

    반환 = {짧은 이름(예: freyja): tier(standard|fast)}. 새 딜리버리 페르소나 = `.md` 파일에
    delivery 키 하나 — heimdall 디스패치 enum·티어가 여기서 파생되므로 코드 수정이 없다.
    ullr 처럼 delivery 키 없는 role 은 네이티브 디스패치 대상이 아니다 (현행 의미 보존)."""
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
    """frontmatter tools 선언에 Write 가 있으면 쓰기 가능 role — readonly 판정의 단일 소스."""
    parts = dict(ROLE_AGENTS)[fname].split("---", 2)
    tools = next((ln.split(":", 1)[1] for ln in parts[1].splitlines() if ln.startswith("tools:")), "")
    return "Write" in tools


def role_core_skill(fname: str, description: str) -> str:
    """모드 A(서브에이전트 부재 툴)용 코어 계약 스킬 — role `.md` 파일이 단일 소스.

    role frontmatter(모델·툴 선언)는 스킬에서 무의미하므로 스킬 frontmatter 로 교체하고
    본문은 그대로 잇는다. Worker phase 가 해당 도메인 하위작업에서 로드해 인라인 수행한다."""
    body = dict(ROLE_AGENTS)[fname].split("---", 2)[2].lstrip()
    name = fname.removesuffix(".md")
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"
