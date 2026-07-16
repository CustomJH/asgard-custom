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


def role_core_skill(fname: str, description: str) -> str:
    """모드 A(서브에이전트 부재 툴)용 코어 계약 스킬 — role `.md` 파일이 단일 소스.

    role frontmatter(모델·툴 선언)는 스킬에서 무의미하므로 스킬 frontmatter 로 교체하고
    본문은 그대로 잇는다. Worker phase 가 해당 도메인 하위작업에서 로드해 인라인 수행한다."""
    body = dict(ROLE_AGENTS)[fname].split("---", 2)[2].lstrip()
    name = fname.removesuffix(".md")
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"
