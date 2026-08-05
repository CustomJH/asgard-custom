"""Bounded, task-relevant context derived from the tracked Asgard project map."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .code_map import MapResult, refresh_map
from .map_lex import Groups, group_terms, hits, idf, query_groups

CONTEXT_BUDGET = 4_000
AREA_FILE_BUDGET = 8_192
MAX_CONTEXT_ENTRIES = 32
_ENTRY = re.compile(r"^- `([^`]+)` — (.+)$")
_COMMAND = re.compile(r"^- Command: `([^`]+)` — (.+)$")
_TOKEN = re.compile(r"[\w./-]{2,}", re.UNICODE)
_SEED_ID = re.compile(r"`([a-z_]+:[^`\s]+)`")
_COVERAGE = re.compile(r"^- Coverage status: ([a-z_]+) · (\d+) named limits$")
_MAX_CONTEXT_SEEDS = 3
_MAX_CONTEXT_COMMANDS = 3
GRAPH_SOURCE = "GRAPH.md"
# 동점 시드의 종류 우선순위 — route는 교차 레인 허브라 impact 회수 가치가 가장 크다.
_SEED_KIND_PRIORITY = ("route", "event", "job", "store", "page", "command")
# 한 엔트리가 이 바이트를 넘으면 길이 대가를 물린다. 짧은 행을 벌주려는 게 아니라, 긴 행이
# 부분문자열을 더 많이 품는다는 이유만으로 이기는 것을 막는 게 목적이다.
_LENGTH_FREE_BYTES = 120
# 주입면 한 행의 역할 문장 상한. 32개 엔트리가 다 이 크기여도 예산 안에 든다.
_MAX_ROLE_BYTES = 220


@dataclass(frozen=True)
class MapEntry:
    path: str
    role: str
    source: str
    managed: bool


@dataclass(frozen=True)
class AreaIssue:
    source: str
    reason: str


@dataclass(frozen=True)
class MapContext:
    text: str
    entries: tuple[MapEntry, ...]
    issues: tuple[AreaIssue, ...]
    managed_hash: str
    refresh: MapResult | None = None


def _safe_path(root: Path, raw: str) -> bool:
    path = Path(raw.rstrip("/"))
    if not path.parts or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    try:
        full = root.joinpath(path)
        full.resolve().relative_to(root.resolve())
        return full.exists() and not full.is_symlink()
    except OSError, ValueError:
        return False


def _threat(*texts: str) -> str | None:
    try:
        from .memory.policy import scan_threats

        return scan_threats(*texts)
    except Exception:
        # A missing optional memory backend must not disable map loading. The policy module itself
        # is stdlib-only, so an import failure means the scanner is unavailable rather than clean.
        return "threat scanner unavailable"


def _neutralize(value: str) -> str:
    return value.replace("<", "‹").replace(">", "›")


def _clip_role(role: str) -> str:
    """주입면이 쓰는 역할 문장의 바이트 상한.

    카탈로그는 완전해야 하지만 주입면은 4,000B 예산이다. `cli.py` 한 행이 명령 109개를 늘어놓아
    1,036B — 예산의 26% — 를 혼자 먹은 적이 있다 (26-08-01 실측). 자르는 자리는 카탈로그가 아니라
    여기다: 잘렸다는 사실과 완전한 목록을 어디서 보는지를 같이 적어 둔다.
    """
    encoded = role.encode("utf-8")
    if len(encoded) <= _MAX_ROLE_BYTES:
        return role
    # 멀티바이트 문자 중간에서 자르지 않는다 — 깨진 바이트는 디코드 단계에서 통째로 사라진다.
    head = encoded[:_MAX_ROLE_BYTES].decode("utf-8", "ignore").rstrip(" ,·")
    return f"{head}… (잘림 — 전체는 `asgard map list`)"


def validate_area_maps(root: str | os.PathLike[str]) -> tuple[tuple[MapEntry, ...], tuple[AreaIssue, ...]]:
    """Validate human/agent-owned maps without rewriting them."""
    base = Path(root).resolve()
    map_dir = base / ".asgard" / "map"
    entries: list[MapEntry] = []
    issues: list[AreaIssue] = []
    try:
        candidates = sorted(
            path for path in map_dir.glob("*.md") if path.name not in {"GRAPH.md", "INDEX.md", "PROJECT.md"}
        )
    except OSError as exc:
        return (), (AreaIssue(".asgard/map", str(exc)),)
    for path in candidates:
        rel = path.relative_to(base).as_posix()
        try:
            if path.is_symlink():
                issues.append(AreaIssue(rel, "map file is a symlink"))
                continue
            raw = path.read_bytes()
            if len(raw) > AREA_FILE_BUDGET:
                issues.append(AreaIssue(rel, f"map exceeds {AREA_FILE_BUDGET} byte budget"))
                continue
            text = raw.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            issues.append(AreaIssue(rel, str(exc)))
            continue
        blocked = _threat(text)
        if blocked:
            issues.append(AreaIssue(rel, blocked))
            continue
        title_seen = False
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            if not title_seen and line.startswith("# map: "):
                title_seen = True
                continue
            match = _ENTRY.fullmatch(line)
            if not match:
                issues.append(AreaIssue(rel, f"line {number} violates map entry grammar"))
                continue
            entry_path, role = match.groups()
            if not _safe_path(base, entry_path):
                issues.append(AreaIssue(rel, f"line {number} references a stale or unsafe path: {entry_path}"))
                continue
            entries.append(MapEntry(entry_path, role.strip(), rel, False))
        if not title_seen:
            issues.append(AreaIssue(rel, "missing `# map: <area>` title"))
    return tuple(entries), tuple(issues)


def _managed_entries(
    root: Path, text: str, source: str = ".asgard/map/PROJECT.md"
) -> tuple[list[MapEntry], list[tuple[str, str]]]:
    entries: list[MapEntry] = []
    commands: list[tuple[str, str]] = []
    for line in text.splitlines():
        command = _COMMAND.fullmatch(line)
        if command:
            if not _threat(*command.groups()):
                commands.append((command.group(1), command.group(2)))
            continue
        match = _ENTRY.fullmatch(line)
        if not match:
            continue
        path, role = match.groups()
        if path == "(none yet)" or not _safe_path(root, path) or _threat(path, role, source):
            continue
        entries.append(MapEntry(path, role.strip(), source, True))
    return entries, commands


def _trace_seeds(graph_text: str, terms: set[str]) -> list[str]:
    """GRAPH.md `## Trace seeds`에서 쿼리 연관 노드 id를 고른다 — 명령 라우팅의 시드.

    경로만 주면 에이전트는 Read/grep 최소 저항 경로를 탄다(실측). 시드 id를 명령과 함께
    주입해야 trace/impact로 간다. 쿼리와 무관한 시드는 예산만 축내므로 매치 0 이면 비운다.
    """
    if not terms:
        return []
    split = graph_text.split("## Trace seeds", 1)
    if len(split) < 2:
        return []
    body = split[1].split("\n## ", 1)[0]
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for node_id in _SEED_ID.findall(body):
        lowered = node_id.casefold()
        score = sum(1 for term in terms if term in lowered)
        if score and node_id not in seen:
            seen.add(node_id)
            kind = node_id.partition(":")[0]
            rank = _SEED_KIND_PRIORITY.index(kind) if kind in _SEED_KIND_PRIORITY else len(_SEED_KIND_PRIORITY)
            scored.append((-score, rank, node_id))
    scored.sort()
    return [node_id for _score, _rank, node_id in scored[:_MAX_CONTEXT_SEEDS]]


def _routable_commands(graph_text: str) -> list[tuple[str, str]]:
    """GRAPH.md `## Commands` 절 → (명령, 역할).

    상한 넘김 안내행(`- (+N more …)`)은 백틱으로 시작하지 않아 엔트리 문법에 안 걸린다.
    """
    split = graph_text.split("## Commands", 1)
    if len(split) < 2:
        return []
    rows: list[tuple[str, str]] = []
    for line in split[1].split("\n## ", 1)[0].splitlines():
        match = _ENTRY.fullmatch(line.strip())
        if not match:
            continue
        command, role = (value.strip() for value in match.groups())
        if not _threat(command, role):
            rows.append((command, role))
    return rows


def _coverage_note(graph_text: str) -> str:
    """Carry a partial scanner boundary into the agent slice without copying the full gap catalog."""
    found = next(
        (_COVERAGE.fullmatch(line) for line in graph_text.splitlines() if line.startswith("- Coverage status:")), None
    )
    if found is None or found.group(1) != "partial":
        return ""
    count = int(found.group(2))
    return (
        f"관계 지도 coverage가 partial이다({count} named limits). "
        "부재·전체 영향 주장은 `asgard map scan --json`의 빠진 범위를 먼저 확인해라."
    )


def _command_routes(rows: list[tuple[str, str]], groups: Groups) -> list[tuple[str, str]]:
    """질의에 맞는 명령 — 숏컷의 본체다.

    경로만 주면 에이전트는 grep 최소 저항 경로를 탄다(`_trace_seeds` 주석의 실측). 시드가 노드
    id를 주는 것과 같은 이유로, 여기서는 **이미 답을 내는 명령**을 준다. 무매치면 비운다 —
    관련 없는 명령은 예산만 먹고 잘못된 자신감을 준다.

    엔트리와 달리 개념 수(coverage)를 **먼저** 본다. 명령은 하나만 고르는 자리라 "두 개념을
    걸친 명령"이 "한 개념에 세게 걸린 명령"보다 거의 언제나 맞다: `스튜디오 티켓 상태`에서
    IDF만 보면 `auth status`(상태 하나, 희귀)가 `ticket board`(티켓+상태)를 이겼다.
    """
    if not groups or not rows:
        return []
    haystacks = [f"{command} {role}".casefold() for command, role in rows]
    weights = idf(haystacks, groups)
    scored: list[tuple[int, float, str, str]] = []
    for (command, role), haystack in zip(rows, haystacks):
        covered, score = hits(haystack, command.casefold(), groups, weights)
        if covered:
            scored.append((-covered, -score, command, role))
    scored.sort()
    return [(command, role) for _covered, _score, command, role in scored[:_MAX_CONTEXT_COMMANDS]]


def _tier(entry: MapEntry) -> int:
    """동점일 때의 층 우선순위 — 방위 지도가 먼저다.

    질의가 아무것도 안 맞으면(또는 여러 엔트리가 같은 점수면) 남는 건 오리엔테이션이고, 그건
    PROJECT.md 가 하는 일이다. 예전엔 `source` 문자열이 타이브레이크라 `GRAPH.md` 가 알파벳순으로
    PROJECT.md 를 이겨, 무매치 질의에 관계 카탈로그 행부터 실렸다.
    """
    if not entry.managed:
        return 2
    return 1 if entry.source.endswith(GRAPH_SOURCE) else 0


def _weights(entries: list[MapEntry], groups: Groups) -> dict[str, float]:
    if not entries or not groups:
        return {}
    return idf([f"{entry.path} {entry.role} {entry.source}".casefold() for entry in entries], groups)


def _relevance(entry: MapEntry, groups: Groups, weights: dict[str, float]) -> float:
    """질의 적합도 — 맞은 개념 수를 먼저 보고, 행이 먹는 바이트로 나눈다.

    나누는 이유: 주입면은 4,000B 예산이고 행마다 값이 다르다. `cli.py` 한 행이 명령 109개를
    늘어놓아 부분문자열을 잔뜩 품은 채 1,036B(예산의 26%)를 먹으며 2위로 올라온 적이 있다
    (26-08-01 실측). 긴 행은 더 많이 맞히는 만큼 더 많이 증명해야 한다.
    """
    haystack = f"{entry.path} {entry.role} {entry.source}".casefold()
    covered, raw = hits(haystack, entry.path.casefold(), groups, weights)
    if not covered:
        return 0.0
    cost = len(f"{entry.path} {entry.role}".encode("utf-8"))
    return raw / max(1.0, cost / _LENGTH_FREE_BYTES)


def _score(entry: MapEntry, groups: Groups, weights: dict[str, float]) -> tuple[float, int, str, str]:
    score = _relevance(entry, groups, weights)
    if entry.managed:
        # 관리 엔트리의 미세 가산 — 무매치 질의에서 사람 지도보다 방위 지도가 먼저 서게 하는
        # 타이브레이크지, 적합도를 이기라는 값이 아니다.
        score += 0.01
    return (-score, _tier(entry), entry.source, entry.path)


def build_map_context(
    root: str | os.PathLike[str],
    query: str = "",
    *,
    refresh: bool = False,
    managed_only: bool = False,
) -> MapContext:
    """Refresh if requested, then render a safe query-relevant context fragment."""
    base = Path(root).resolve()
    # The map is an opt-in project asset created by `asgard init/map generate`. A refresh request
    # from a hook or `map context --refresh` must not seed tracked files in an unmapped repository.
    refreshed = refresh_map(base) if refresh and (base / ".asgard" / "map").is_dir() else None
    project_path = base / ".asgard" / "map" / "PROJECT.md"
    try:
        managed_text = project_path.read_text(encoding="utf-8")
    except OSError:
        managed_text = ""
    # 관계 그래프 카탈로그(GRAPH.md)는 맵의 심화 계층이다 — 존재하면 같은 엔트리 문법으로
    # 융합되어 라우트·모델·외부 서비스 증거가 동일 예산 안에서 함께 랭크된다.
    graph_path = base / ".asgard" / "map" / "GRAPH.md"
    try:
        graph_text = graph_path.read_text(encoding="utf-8") if not graph_path.is_symlink() else ""
    except OSError:
        graph_text = ""
    managed_hash = hashlib.sha256((managed_text + "\0" + graph_text).encode()).hexdigest()
    managed, commands = _managed_entries(base, managed_text)
    graph_entries, _graph_commands = _managed_entries(base, graph_text, ".asgard/map/GRAPH.md")
    managed = [*managed, *graph_entries]
    manual: tuple[MapEntry, ...] = ()
    issues: tuple[AreaIssue, ...] = ()
    if not managed_only:
        manual, issues = validate_area_maps(base)
    all_entries = [*managed, *manual]
    # 질의 어휘를 두 갈래로 편다: 라틴 토큰은 있는 그대로, 한국어 도메인 명사는 닫힌 사전으로.
    # 지도 표면은 전부 라틴 식별자인데 질문은 한국어로 오므로, 이 다리가 없으면 "커밋 게이트"가
    # `command:seal` 과 한 글자도 안 겹쳐 숏컷이 뜨지 않는다.
    groups = query_groups(query)
    terms = group_terms(groups)
    weights = _weights(all_entries, groups)
    ranked = sorted(all_entries, key=lambda entry: _score(entry, groups, weights))
    if groups and any(_relevance(entry, groups, weights) for entry in ranked):
        relevant = [entry for entry in ranked if _relevance(entry, groups, weights)]
        fallback = [entry for entry in ranked if entry.managed and entry not in relevant]
        ranked = [*relevant, *fallback]
    # 라우팅 두 줄(명령·시드)은 숏컷의 본체다 — 큰 리포일수록 엔트리가 예산을 다 채우므로
    # 바이트를 선예약하고 블록을 원자적으로 넣는다 (헤더만 남는 절단 금지).
    routes = _command_routes(_routable_commands(graph_text), groups)
    route_lines: list[str] = []
    if routes:
        # 주장의 세기를 근거에 맞춘다: 이 줄은 "이 명령이 답이다"가 아니라 "질의에 가장 가까운
        # 명령이다"까지만 안다. 맞는 명령이 아예 없어도 가장 가까운 것은 늘 하나 나온다.
        route_lines = ["질의에 가까운 이 저장소의 명령이다 — 핸들러를 grep 하기 전에 여기부터 확인해라:"]
        route_lines += [f"- `{_neutralize(command)}` — {_neutralize(role)}" for command, role in routes]
    seeds = _trace_seeds(graph_text, terms)
    seed_lines: list[str] = []
    if seeds and not _threat(*seeds):
        seed_row = " · ".join(f"`{_neutralize(seed)}`" for seed in seeds)
        seed_lines = [
            "연쇄·영향 질문(무엇이 무엇을 부르나·바꾸면 어디까지)은 경로 grep 전에 지도 명령이 정확하다:",
            f"- `asgard map impact <id>` / `asgard map trace --from <id> --kinds calls,touches` — 시드: {seed_row}",
        ]
    coverage_note = _coverage_note(graph_text)
    coverage_lines = [coverage_note] if coverage_note else []
    reserved = sum(len(line.encode("utf-8")) + 1 for line in (*coverage_lines, *route_lines, *seed_lines))
    selected: list[MapEntry] = []
    lines = [
        f'<asgard-map revision="{managed_hash[:12]}" advisory="true">',
        "작업 관련 프로젝트 지도다. 먼저 이 경로로 탐색하되 계획·편집·판정에 쓰는 정의와 사용처는 소스에서 다시 읽어라.",
        *coverage_lines,
        *route_lines,
    ]
    for entry in ranked[:MAX_CONTEXT_ENTRIES]:
        line = f"- `{entry.path}` — {_clip_role(_neutralize(entry.role))} [source: {_neutralize(entry.source)}]"
        if len(("\n".join([*lines, line, "</asgard-map>"])).encode("utf-8")) > CONTEXT_BUDGET - reserved:
            break
        lines.append(line)
        selected.append(entry)
    if seed_lines and len(("\n".join([*lines, *seed_lines, "</asgard-map>"])).encode("utf-8")) <= CONTEXT_BUDGET:
        lines.extend(seed_lines)
    if commands:
        lines.append("검증 명령 후보:")
        for command, role in commands:
            line = f"- `{_neutralize(command)}` — {_neutralize(role)}"
            if len(("\n".join([*lines, line, "</asgard-map>"])).encode("utf-8")) > CONTEXT_BUDGET:
                break
            lines.append(line)
    lines.append("</asgard-map>")
    text = "\n".join(lines) if selected or commands or route_lines or coverage_lines else ""
    return MapContext(text, tuple(selected), issues, managed_hash, refreshed)
