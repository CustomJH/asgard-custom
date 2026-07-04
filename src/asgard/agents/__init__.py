"""Asgard agent library — the single home for role-agent definitions (grows as we add agents).

Each `*.md` here is a REAL agent file (frontmatter + body), edited as markdown with no escaping —
the same abstraction boundary `asgard.hooks` gives hook scripts. setup scaffolds each file verbatim
into the user's `.claude/agents/`. Add an agent = drop a `.md` file here; discovery is the directory
listing itself, so there is no registry to update."""

from importlib import resources

# (파일명, 내용) — setup 이 .claude/agents/ 에 스캐폴딩. 역할 = 직관명(asgard-thinker/worker/verifier),
# 신화 이름은 딜리버리 계층(CUS-129) 전용 (2026-07-02 Odin 결정).
ROLE_AGENTS: list[tuple[str, str]] = sorted(
    (f.name, f.read_text(encoding="utf-8")) for f in resources.files(__package__).iterdir() if f.name.endswith(".md")
)
