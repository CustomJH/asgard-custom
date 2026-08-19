"""코드 스타일 규격 — 저장소가 이미 쓰는 린터·포매터를 선언하고, 이 세션이 쓴 파일에만 물린다.

**왜 새 판정기가 아니라 선언인가.** `craft` 와 `thor gate` 는 규칙을 직접 갖는다 — 함수 길이,
삼킨 예외처럼 저장소가 달라도 답이 같은 것들이다. 코드 스타일은 반대다. 중괄호 자리와 import
차례는 팀이 정하고, 그 결정은 이미 `checkstyle.xml`·`eslint.config.js`·`.clang-format` 안에
있다. 그것을 파이썬으로 다시 구현하면 두 벌이 되고 곧 갈린다. 그래서 이 모듈은 규칙을 하나도
모른다 — 저장소의 도구를 부르고, 그 출력에서 파일과 줄 번호를 읽어, 이번 세션이 쓴 파일에서 나온
것만 골라낸다.

**두 조각.** ① `Tool` — 무엇을 실행하고(`check`), 무엇으로 고치고(`fix`), 어떤 확장자를 맡는지.
사용자가 `.asgard/asgard-setting-project.json` 의 `code_style.tools` 에 적는 형태 그대로다.
② `run()` — 그 도구들을 돌리고 출력을 `Finding` 으로 바꾼다. 저장소를 훑어 도구를 찾아내는
쪽은 `code_style_catalog` 에 따로 있다: 언어를 하나 더 받는 변경이 이 파일을 안 건드려야 한다.

**귀속이 이 모듈의 값이다.** 스타일 도구는 저장소 전체를 보고, 오래된 위반은 어느 저장소에나
있다. 그 전부로 막으면 첫 실행에서 게이트가 통째로 꺼진다(사람이 끈다). 그래서 `paths` 를 받은
실행은 그 경로에서 나온 판정만 `blocking` 으로 세고, 나머지는 물려받은 부채로 같은 화면에 적되
막지 않는다 — `craft` 의 래칫과 같은 규약이다.

진단 형식은 도구마다 다르고 표준이 없다. 흔한 일곱 계열을 내장하고(줄 단위 정규식 다섯 =
`_DIAGNOSTICS`, 여기에 eslint stylish 와 화살표 형식), 안 맞는
도구는 `diagnostic` 에 정규식을 적어 덮는다. 한 줄도 못 읽은 실행은 "위반 없음"이 아니라
`unparsed` 로 적는다 — 조용한 통과와 판정 불가는 화면에서 달라야 한다.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field

SECTION = "code_style"
DEFAULT_TIMEOUT = 300
# 명령 한 번에 싣는 경로 수. 넘치면 자르지 않고 그만큼씩 나눠 여러 번 돈다 (`_batches`) —
# 인자 길이 상한(Windows 32KB)에 걸려 실행 자체가 죽지 않으면서, 판정 못 받는 파일도 없다.
MAX_INLINE_PATHS = 60
_FILES_SLOT = "{files}"


@dataclass(frozen=True)
class Tool:
    """스타일 도구 하나 — 설정 파일의 `code_style.tools` 항목과 1:1 이다.

    `check` 안의 `{files}` 는 판정할 경로들로 치환된다. 자리가 없으면 도구를 저장소 전체로
    돌리고 귀속 단계에서 거른다 — gradle·maven 처럼 파일 목록을 안 받는 도구가 그 쪽이다.
    """

    name: str
    check: str
    fix: str = ""
    languages: tuple[str, ...] = ()  # 확장자 (".java") — 비면 모든 파일이 이 도구의 것이다
    paths: tuple[str, ...] = ()  # 저장소 상대 접두사 — 비면 저장소 전체
    cwd: str = ""  # 명령을 도는 자리 (저장소 상대). 비면 뿌리
    diagnostic: str = ""  # 내장 형식을 덮는 정규식 — `file`·`line`·`message` 이름 그룹
    autofix: bool = False  # 켜면 게이트가 `fix` 를 직접 돌린다 (디스크가 바뀐다)
    timeout: int = DEFAULT_TIMEOUT

    def owns(self, rel: str) -> bool:
        """이 경로가 이 도구의 것인가 — 확장자와 접두사 둘 다 맞아야 한다."""
        if self.languages and not rel.endswith(tuple(self.languages)):
            return False
        if not self.paths:
            return True
        return any(rel == p.rstrip("/") or rel.startswith(p.rstrip("/") + "/") for p in self.paths)


@dataclass(frozen=True)
class Finding:
    """판정 1건. 칸 이름은 `craft.Finding` 과 같다 — 게이트가 두 판정기를 한 형식으로 읽는다."""

    rule: str
    path: str
    line: int
    unit: str
    detail: str
    fix: str
    blocking: bool = True


@dataclass(frozen=True)
class Run:
    """도구 하나의 실행 기록 — 무엇이 돌았고 어떻게 끝났는지."""

    tool: str
    command: str
    exit_code: int
    findings: int
    unparsed: int  # 출력에 줄은 있는데 형식을 못 읽은 줄 수
    error: str = ""  # 실행 자체가 실패한 사유 (도구 부재·시간 초과)


@dataclass
class Report:
    tools: list[str] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    scoped: tuple[str, ...] = ()  # 귀속 대상으로 받은 경로 (빈 튜플 = 전체 판정)
    repaired: list[str] = field(default_factory=list)  # 실제로 돌린 수정 명령 — 디스크가 바뀐 사실

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    @property
    def inherited(self) -> int:
        return sum(1 for f in self.findings if not f.blocking)

    @property
    def undetermined(self) -> list[Run]:
        return [r for r in self.runs if r.error or (r.exit_code != 0 and r.findings == 0)]


# ── 설정 ────────────────────────────────────────────────────────────


def _section(root: str) -> dict:
    from .settings import load_project

    raw = load_project(root).get(SECTION)
    return raw if isinstance(raw, dict) else {}


def _real_keys(section: dict) -> list[str]:
    """`_` 로 시작하는 키는 JSON 안의 주석이다 — 설정 여부를 셀 때 빼야 한다."""
    return [k for k in section if not str(k).startswith("_")]


def configured(root: str) -> bool:
    """이 저장소가 스타일 레인을 들였는가 — 훅이 자식 프로세스를 띄우기 전에 묻는 질문이다.

    주석 키만 있는 시드는 "안 들임"이다. 그래야 `asgard style init` 을 부르기 전까지 게이트가
    한 번도 안 돌고, 안 쓰는 저장소가 Stop 마다 `asgard` 자식을 띄우지 않는다.
    """
    section = _section(root)
    if not _real_keys(section):
        return False
    if section.get("enabled") is False:
        return False
    return bool(_tool_rows(section))


def _tool_rows(section: dict) -> list[dict]:
    rows = section.get("tools")
    return [r for r in rows if isinstance(r, dict) and r.get("check")] if isinstance(rows, list) else []


def _tool(row: dict) -> Tool:
    def strings(key: str) -> tuple[str, ...]:
        value = row.get(key)
        return tuple(str(v) for v in value if str(v)) if isinstance(value, list) else ()

    return Tool(
        name=str(row.get("name") or "style"),
        check=str(row["check"]),
        fix=str(row.get("fix") or ""),
        languages=strings("languages"),
        paths=strings("paths"),
        cwd=str(row.get("cwd") or ""),
        diagnostic=str(row.get("diagnostic") or ""),
        autofix=bool(row.get("autofix")),
        timeout=int(row.get("timeout") or DEFAULT_TIMEOUT),
    )


def declared(root: str) -> list[Tool]:
    """설정에 적힌 도구들. 선언이 있으면 그것이 전부다 — 감지는 더하지 않는다.

    자동 감지를 선언 위에 얹으면 사용자가 지운 도구가 다음 실행에서 되살아난다. 감지는
    `asgard style init` 이 한 번 부르고 결과를 설정에 적는 것으로 끝난다.
    """
    return [_tool(row) for row in _tool_rows(_section(root))]


def as_rows(tools: list[Tool]) -> list[dict]:
    """설정 파일에 적을 형태 — 기본값과 같은 칸은 안 적는다 (사람이 읽는 파일이다)."""
    rows = []
    for tool in tools:
        row: dict[str, object] = {"name": tool.name, "check": tool.check}
        if tool.fix:
            row["fix"] = tool.fix
        if tool.languages:
            row["languages"] = list(tool.languages)
        if tool.paths:
            row["paths"] = list(tool.paths)
        if tool.cwd:
            row["cwd"] = tool.cwd
        if tool.diagnostic:
            row["diagnostic"] = tool.diagnostic
        if tool.autofix:
            row["autofix"] = True
        if tool.timeout != DEFAULT_TIMEOUT:
            row["timeout"] = tool.timeout
        rows.append(row)
    return rows


# ── 진단 읽기 ────────────────────────────────────────────────────────

# 한 줄이 판정 하나인 다섯 꼴. 위에서부터 시도하고 첫 성공을 쓴다 — 좁은 형식이 먼저다.
_DIAGNOSTICS: tuple[re.Pattern[str], ...] = (
    # maven checkstyle·pmd: `[ERROR] /abs/File.java:[12,5] (blocks) NeedBraces: msg`
    re.compile(
        r"^\s*(?:\[[^\]]{1,40}\]\s*)+(?P<file>[^\s:]+\.[A-Za-z0-9_+]+):\[(?P<line>\d+)(?:,\d+)?\]\s*(?P<message>.*)$"
    ),
    # gradle checkstyle·ktlint: `[ant:checkstyle] [ERROR] /abs/File.java:12:5: msg [Rule]`
    re.compile(
        r"^\s*(?:\[[^\]]{1,40}\]\s*)+(?P<file>[^\s:]+\.[A-Za-z0-9_+]+):(?P<line>\d+)(?::\d+)?:\s*(?P<message>.*)$"
    ),
    # tsc·MSBuild: `app/x.vue(43,20): error TS2345: msg`
    re.compile(r"^\s*(?P<file>[^\s(]+\.[A-Za-z0-9_+]+)\((?P<line>\d+)(?:,\d+)?\):\s*(?P<message>.*)$"),
    # ruff·eslint --format=compact·shellcheck·rubocop·golangci-lint: `path:12:5: msg`
    re.compile(r"^\s*(?P<file>[^\s:]+\.[A-Za-z0-9_+]+):(?P<line>\d+)(?::\d+)?:\s*(?P<message>.+)$"),
    # flake8 축약형과 sqlfluff: `path:12: msg`
    re.compile(r"^\s*(?P<file>[^\s:]+\.[A-Za-z0-9_+]+):(?P<line>\d+)\s+(?P<message>.+)$"),
)
# eslint 기본 출력(stylish): 경로가 자기 줄에 홀로 서고 그 아래 들여쓴 판정이 붙는다.
# `gofmt -l`·`prettier --check` 는 그 아래에 아무것도 안 붙이고 경로만 나열한다 — 그 경우
# 경로 자체가 판정이므로 줄 번호 0 으로 낸다 (안 그러면 위반이 통째로 조용히 사라진다).
_BARE_PATH = re.compile(
    r"^\s*(?:\[[^\]]{1,20}\]\s*)?(?P<file>(?:[A-Za-z]:)?[^\s:]*[/\\]?[^\s:/\\]+\.[A-Za-z0-9_+]+)\s*$"
)
_INDENTED = re.compile(r"^\s+(?P<line>\d+):\d+\s+(?P<message>.+)$")
# rustc·clippy·ruff 기본 출력: 내용이 먼저 오고 자리가 다음 줄에 화살표로 붙는다.
_ARROW = re.compile(r"^\s*-->\s+(?P<file>\S+?):(?P<line>\d+)(?::\d+)?\s*$")


def parse(text: str, pattern: str = "") -> tuple[list[tuple[str, int, str]], int]:
    """도구 출력 → [(파일, 줄, 내용)] 과 **형식을 못 읽은 줄 수**.

    두 번째 값이 있는 이유는 정직함이다. 진단을 하나도 못 읽은 실행은 "위반이 없다"가 아니라
    "형식을 모른다"이고, 그 둘이 화면에서 같으면 게이트가 꺼진 것을 아무도 못 본다.
    """
    custom = None
    if pattern:
        try:
            custom = re.compile(pattern)
        except re.error:
            custom = None
    rows: list[tuple[str, int, str]] = []
    unparsed = 0
    context = ""  # 바로 위에 홀로 선 경로 (eslint stylish)
    # 아래에 아무 판정도 안 붙은 경로 (gofmt -l·prettier --check). 값 없는 dict 인 이유는 둘
    # 다 필요해서다 — 낸 차례를 지키면서, 판정이 붙을 때 O(1) 로 빼야 한다.
    dangling: dict[str, None] = {}
    previous = ""  # 바로 위 줄 — 화살표 형식은 내용이 자리보다 먼저 온다
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            context, previous = "", ""
            continue
        matched = custom.search(line) if custom else None
        if matched is None:
            for expr in _DIAGNOSTICS:
                matched = expr.match(line)
                if matched:
                    break
        if matched:
            groups = matched.groupdict()
            try:
                number = int(groups.get("line") or 0)
            except ValueError:
                number = 0
            rows.append((groups.get("file") or context, number, (groups.get("message") or line).strip()))
            dangling.pop(context, None)
            context, previous = "", ""
            continue
        arrow = _ARROW.match(line)
        if arrow:
            rows.append((arrow.group("file"), int(arrow.group("line")), previous or line.strip()))
            if previous:
                unparsed -= 1  # 그 줄은 못 읽은 게 아니라 이 판정의 내용이었다
            previous = ""
            continue
        bare = _BARE_PATH.match(line)
        if bare:
            context = bare.group("file")
            dangling[context] = None
            previous = ""
            continue
        indented = _INDENTED.match(line)
        if indented and context:
            rows.append((context, int(indented.group("line")), indented.group("message").strip()))
            dangling.pop(context, None)
            continue
        unparsed += 1
        previous = line.strip()
    rows += [(path, 0, "이 파일이 규격과 다르다고 도구가 이름만 냈어요") for path in dangling]
    return [row for row in rows if row[0]], unparsed


def _normalize(root: str, cwd: str, path: str) -> str:
    """진단이 부른 경로 → 저장소 상대 posix 경로. 못 옮기면 준 대로 둔다."""
    text = path.replace("\\", "/").lstrip()
    if text.startswith("./"):
        text = text[2:]
    absolute = text if os.path.isabs(text) else os.path.join(root, cwd, text)
    try:
        rel = os.path.relpath(os.path.realpath(absolute), os.path.realpath(root))
    except OSError, ValueError:
        return text
    return text if rel.startswith("..") else rel.replace("\\", "/")


def attributes(scoped: set[str], candidate: str) -> bool:
    """이 판정이 이번에 쓴 파일에서 나왔는가.

    끝자리 대조까지 하는 이유는 도구가 저장소 뿌리에서 안 돌기 때문이다 — `helios-fe/` 에서 돈
    vue-tsc 는 `app/x.vue` 라고 부르고 세션 목록에는 `helios-fe/app/x.vue` 로 적혀 있다.
    """
    if candidate in scoped:
        return True
    return any(path.endswith("/" + candidate) or candidate.endswith("/" + path) for path in scoped)


# ── 실행 ────────────────────────────────────────────────────────────


def _batches(command: str, paths: list[str]) -> list[list[str]]:
    """명령 한 번에 실을 경로 묶음들. `{files}` 가 없으면 묶음 하나다 (도구가 전체를 본다).

    자르지도 넓히지도 않고 나누는 이유가 둘 다 나쁘기 때문이다. 상한에서 자르면 판정 못 받은
    파일이 "위반 없음" 으로 읽히고 그 사실이 화면 어디에도 안 남는다. 반대로 넘칠 때 저장소
    전체로 넓히면 수정 명령이 이번에 안 건드린 파일까지 다시 쓴다. 나누면 둘 다 안 생기고,
    값은 도구를 몇 번 더 띄우는 것뿐이다.
    """
    if _FILES_SLOT not in command or not paths:
        return [paths]
    return [paths[at : at + MAX_INLINE_PATHS] for at in range(0, len(paths), MAX_INLINE_PATHS)]


def _render(command: str, root: str, cwd: str, paths: list[str]) -> str:
    """`{files}` 를 실제 경로로 채운다. 자리가 없으면 명령을 그대로 둔다 (저장소 전체 실행).

    경로 수를 여기서 제한하지 않는다 — 묶는 것은 `_batches` 의 일이고, 이 함수가 한 번 더
    자르면 그 절단은 아무도 안 센다.
    """
    if _FILES_SLOT not in command:
        return command
    base = os.path.join(root, cwd) if cwd else root
    quoted = []
    for rel in paths:
        try:
            local = os.path.relpath(os.path.join(root, rel), base).replace("\\", "/")
        except ValueError:
            local = rel
        quoted.append(shlex.quote(local))
    return command.replace(_FILES_SLOT, " ".join(quoted) if quoted else ".")


def _remedy(tool: Tool, root: str, batch: list[str]) -> str:
    """화면에 낼 수정 명령 — 붙여넣을 수 있어야 한다.

    `{files}` 를 남긴 채 내면 읽는 쪽이 경로를 다시 조립해야 하고, 도구가 하위 모듈에서 돌면
    그 경로도 그 자리 기준이라 옮기는 것까지 적어야 맞는 명령이 된다.
    """
    if not tool.fix:
        return ""
    command = _render(tool.fix, root, tool.cwd, batch)
    return "cd %s && %s" % (tool.cwd, command) if tool.cwd else command


def _shell(command: str, cwd: str, timeout: int) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return -1, "", "timed out after %ds" % timeout
    except OSError as exc:
        return -1, "", str(exc)
    return proc.returncode, (proc.stdout or "") + "\n" + (proc.stderr or ""), ""


def _once(root: str, tool: Tool, batch: list[str], scoped: set[str]) -> tuple[list[Finding], Run]:
    """도구 하나를 경로 묶음 하나에 돌리고 (판정들, 실행 기록)을 준다."""
    cwd = os.path.join(root, tool.cwd) if tool.cwd else root
    command = _render(tool.check, root, tool.cwd, batch)
    remedy = _remedy(tool, root, batch) or ("고칠 명령이 선언되지 않았어요 — `%s` 를 직접 돌려 고치세요" % command)
    code, output, error = _shell(command, cwd, tool.timeout)
    rows, unparsed = parse(output, tool.diagnostic)
    findings = []
    for path, number, message in rows:
        rel = _normalize(root, tool.cwd, path)
        blocking = not scoped or attributes(scoped, rel)
        findings.append(Finding(tool.name, rel, number, "", message[:300], remedy, blocking))
    return findings, Run(tool.name, command, code, len(findings), unparsed, error)


def _repair(root: str, tool: Tool, owned: list[str], mode: str, report: Report) -> None:
    """수정 명령을 돌린다 — 판정과 같은 묶음 단위라, 이번에 안 건드린 파일은 안 다시 쓴다."""
    if not tool.fix or mode not in ("all", "auto"):
        return
    if mode == "auto" and not tool.autofix:
        return
    cwd = os.path.join(root, tool.cwd) if tool.cwd else root
    for batch in _batches(tool.fix, owned):
        command = _render(tool.fix, root, tool.cwd, batch)
        _shell(command, cwd, tool.timeout)
        report.repaired.append(command)


def run(root: str, tools: list[Tool], paths: tuple[str, ...] = (), *, repair: str = "") -> Report:
    """도구들을 돌리고 판정을 모은다.

    `paths` 를 주면 그 경로에서 나온 판정만 `blocking` 이다. 안 주면 전부 막는다 — 사람이
    `asgard style check` 를 직접 부른 경우라 물려받은 부채도 보고 싶은 자리다.

    `repair` 는 수정 명령을 먼저 돌릴지다: `"all"` 은 `fix` 가 있는 도구 전부, `"auto"` 는
    `autofix: true` 를 적어 둔 도구만, `""` 는 안 돈다. 게이트가 `"auto"` 를 쓰는 이유는
    디스크를 말없이 고치는 것이 기본이면 안 되기 때문이다 — 켜는 것은 설정에 적는 사람이다.
    """
    scoped = {p.replace("\\", "/") for p in paths}
    report = Report(scoped=tuple(sorted(scoped)))
    for tool in tools:
        owned = sorted(p for p in scoped if tool.owns(p))
        if scoped and not owned:
            continue  # 이 세션이 이 도구의 언어를 안 건드렸다
        report.tools.append(tool.name)
        _repair(root, tool, owned, repair, report)
        for batch in _batches(tool.check, owned):
            found, record = _once(root, tool, batch, scoped)
            report.findings += found
            report.runs.append(record)
    return report
