"""just(1) 를 프로젝트의 실행 표면으로 세운다 — 감지, 관리 구역 쓰기, 드리프트 판정, 설치.

**왜 파일 전체가 아니라 구역 하나인가.** 지도는 `PROJECT.md` 를 통째로 소유한다. 사람이 그
파일을 손보는 일이 없기 때문이다. Justfile 은 반대다 — 저장소마다 배포, 마이그레이션, 컨테이너
기동처럼 매니페스트에 안 적힌 절차가 있고 그것을 적는 자리가 여기다. 그래서 두 소유권을 한
파일에 나눠 둔다: `BEGIN`/`END` 표식 사이는 `asgard just sync` 가 매번 다시 그리고, 그 밖은
사람의 것이라 이 모듈이 한 글자도 건드리지 않는다. 표식이 없는 Justfile 을 만나면 구역을 끝에
덧붙이지, 있던 내용을 다시 쓰지 않는다.

**중복 이름은 그냥 두는 게 아니라 피한다.** just 는 같은 이름의 레시피가 두 번 나오면 파일
전체를 거부한다(`Recipe \\`test\\` first defined on line N is redefined on line M`). 사용자가
구역 밖에 `test` 를 적어 두었는데 감지기도 `test` 를 내면, 관리 구역을 쓰는 순간 저장소의
모든 `just` 호출이 죽는다. 그래서 렌더러가 구역 밖 이름을 먼저 읽고 겹치는 것을 뺀다 —
사람이 적은 쪽을 남긴다.

명령 감지는 지도가 쓰는 탐지기 하나(`code_map.verification_commands`)를 그대로 빌린다. 둘이
따로 감지하면 주입면이 광고하는 명령과 Justfile 이 실제로 담은 명령이 갈린다.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from . import io_files

BEGIN = "# >>> asgard managed recipes >>>"
END = "# <<< asgard managed recipes <<<"

# just 는 이 이름들을 대소문자 구분 없이 찾는다. 만들 때 쓰는 이름은 첫 항목이다.
_NAMES = ("Justfile", "justfile", ".justfile", "JUSTFILE")

# PyPI 배포판 — macOS(x86_64·arm64)·Linux(glibc/musl 다중 아키텍처)·Windows(win32·amd64)
# 휠에 just 실행 파일이 들어 있다. 설치기가 이미 uv 를 부트스트랩하므로 이 경로 하나면
# brew·cargo·apt·scoop 분기 없이 세 플랫폼이 같은 방법으로 선다.
JUST_PACKAGE = "rust-just"

_HEADER = f"""\
# Asgard — this project's run commands. https://github.com/casey/just
#
# `just --list` shows every command this repository has. Recipes between the asgard markers are
# rewritten by `asgard just sync` from the checked-in manifests; everything outside them is yours
# and never rewritten. When a name collides, the recipe out here is kept and the managed one is dropped.

set shell := ["bash", "-uc"]
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Show every command in this repository
default:
    @just --list

{BEGIN}
{END}
"""

# 레시피 한 줄 설명 — 감지기의 role 문자열은 매니페스트를 설명하지 명령을 설명하지 않아서
# ("Python test suite") 이름마다 부르는 쪽이 읽을 문장을 따로 둔다.
_DOC = {
    "build": "Build the project",
    "check": "Everything the gates run",
    "fmt-check": "Check formatting without writing",
    "lint": "Lint the code",
    "test": "Run the tests",
    "typecheck": "Check types",
}

# 관리 구역 안 차례 — 여기 없는 이름(`make deploy` 같은 것)은 뒤에 알파벳순으로 붙는다.
_ORDER = ("test", "lint", "fmt-check", "typecheck", "build", "check")

_SCRIPT_RECIPES = {"test": "test", "lint": "lint", "typecheck": "typecheck", "check": "check", "build": "build"}

# 레시피 정의 줄: 열 0 에서 시작하고, 이름 뒤에 매개변수와 의존이 올 수 있고, `:=` 는 대입이라
# 레시피가 아니다. `@` 는 조용한 레시피 표식이다.
_RECIPE_RE = re.compile(r"^@?([A-Za-z_][A-Za-z0-9_-]*)(?:\s+[^:\n]*)?:(?!=)")


@dataclass(frozen=True)
class Recipe:
    name: str
    doc: str
    commands: tuple[str, ...] = field(default_factory=tuple)
    deps: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SyncResult:
    path: str
    created: bool
    changed: bool
    recipes: tuple[str, ...]
    skipped: tuple[str, ...]  # 사용자가 구역 밖에 이미 적어 둔 이름
    appended: bool  # 표식이 없어 구역을 끝에 덧붙였다


def find_justfile(root: str) -> str | None:
    """이 저장소의 Justfile 경로 — just 의 탐색 이름 차례를 그대로 따른다."""
    for name in _NAMES:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    return None


def default_path(root: str) -> str:
    return os.path.join(root, _NAMES[0])


def recipe_name(command: str) -> str | None:
    """감지된 명령 하나 → 레시피 이름. 이름을 못 정하는 명령은 관리 구역에 안 들어간다."""
    parts = command.split()
    if not parts:
        return None
    head = parts[0]
    if command == "python -m pytest":
        return "test"
    if head == "ruff":
        return "fmt-check" if "format" in parts else "lint"
    if head == "ty":
        return "typecheck"
    if head == "cargo":
        return parts[1] if len(parts) > 1 and parts[1] in ("test", "check") else None
    if head == "go":
        return "test"
    if head == "make":
        return parts[1] if len(parts) > 1 else None
    if head in ("npm", "pnpm", "yarn"):
        return _SCRIPT_RECIPES.get(parts[-1])
    return None


# uv 가 잠근 환경 안에서만 사는 파이썬 도구들. 매니페스트는 이것들이 dev 그룹에 있다고만
# 말하지 어디서 부르는지는 안 말한다 — `uv.lock` 이 그 답이다.
_UV_TOOLS = frozenset({"python", "ruff", "ty", "pytest", "mypy"})


def _in_environment(root: str, command: str) -> str:
    """명령을 실제로 도는 꼴로 바꾼다 — `uv.lock` 이 있으면 파이썬 도구는 `uv run` 안에서 산다.

    26-08-17 이 저장소 실측: `ruff --version` 은 `command not found`, `uv run ruff --version` 은
    0.15.20. 접두사가 없으면 감지된 레시피 셋(lint·fmt-check·typecheck)이 전부 안 도는 채로
    파일에 적힌다 — 안 도는 레시피는 없는 것만 못하다."""
    head = command.split(maxsplit=1)[0] if command else ""
    if head in _UV_TOOLS and os.path.isfile(os.path.join(root, "uv.lock")):
        return f"uv run {command}"
    return command


def detect_recipes(root: str) -> list[Recipe]:
    """체크인된 매니페스트가 뒷받침하는 명령만 레시피로 묶는다.

    폴리글랏 저장소에서 `python -m pytest` 와 `pnpm test` 가 둘 다 나오면 `test` 하나가 둘을
    차례로 돈다 — 그게 그 저장소에서 "테스트를 돌린다"의 뜻이다. 한 레시피 안의 차례는
    감지기가 정한 알파벳순이라 같은 매니페스트에서 늘 같은 바이트가 나온다."""
    from .code_map import verification_commands

    grouped: dict[str, list[str]] = {}
    for command, _role in verification_commands(root):
        name = recipe_name(command)
        if name:
            grouped.setdefault(name, []).append(_in_environment(root, command))
    recipes = [
        Recipe(name, _DOC.get(name, f"Run `{commands[0]}`"), tuple(commands)) for name, commands in grouped.items()
    ]
    # 집계 레시피는 이름이 비어 있을 때만 — `cargo check` 가 이미 `check` 를 쥔 저장소에서
    # 하나 더 내면 just 가 파일을 거부한다.
    deps = tuple(name for name in ("fmt-check", "lint", "typecheck", "test") if name in grouped)
    if len(deps) >= 2 and "check" not in grouped:
        recipes.append(Recipe("check", _DOC["check"], deps=deps))
    return sorted(recipes, key=lambda r: (_ORDER.index(r.name) if r.name in _ORDER else len(_ORDER), r.name))


def _definitions(text: str) -> list[tuple[str, str, frozenset[str]]]:
    """(이름, 한 줄 설명, 붙은 속성) — 속성은 `[unix]` 처럼 레시피 줄 바로 위에 오는 것들이다.

    속성을 따로 세는 이유는 중복 판정 때문이다. just 에서 `[unix] clean` 과 `[windows] clean`
    은 합법이다(플랫폼마다 하나만 산다). 이것을 중복이라 부르면 helios 처럼 두 벌을 쓰는
    저장소가 영원히 빨간불이 된다."""
    found: list[tuple[str, str, frozenset[str]]] = []
    doc = ""
    attributes: set[str] = set()
    for line in text.splitlines():
        if line.startswith("#"):
            stripped = line.lstrip("#").strip()
            doc = "" if stripped.startswith((">>>", "<<<")) else stripped
            continue
        if not line.strip() or line[:1].isspace():
            continue
        if line.startswith("[") and line.rstrip().endswith("]"):
            attributes.update(part.strip().split("(")[0].strip() for part in line.strip()[1:-1].split(","))
            continue
        match = _RECIPE_RE.match(line)
        if match and not line.startswith(("set ", "export ", "alias ", "import ", "mod ")):
            found.append((match.group(1), doc, frozenset(attributes)))
        doc = ""
        attributes = set()
    return found


def parse_recipes(text: str) -> list[tuple[str, str]]:
    """Justfile 본문에서 (레시피 이름, 한 줄 설명) 을 읽는다 — just 없이도 목록이 나온다.

    lagom: 조건부 정의와 `import`/`mod` 로 들여온 레시피는 못 본다. 정확한 목록은 늘
    `just --list` 다. 이 파서는 그것을 못 부르는 자리(설치 전, 훅, 드리프트 판정)에서만 쓴다."""
    return [(name, doc) for name, doc, _attributes in _definitions(text)]


def _outside_names(text: str) -> set[str]:
    """관리 구역 **밖**에 정의된 레시피 이름 — 겹치면 사람이 적은 쪽을 남긴다."""
    before, _, rest = text.partition(BEGIN)
    _, _, after = rest.partition(END)
    return {name for name, _ in parse_recipes(before + "\n" + after)}


def managed_block(recipes: list[Recipe], *, skip: set[str] | None = None) -> str:
    """표식 두 줄과 그 사이 레시피 — 항상 같은 입력이면 같은 바이트."""
    taken = skip or set()
    lines = [BEGIN]
    for recipe in recipes:
        if recipe.name in taken:
            continue
        # 집계 레시피의 의존도 사용자에게 뺏긴 것이 있으면 뺀다 — 없는 이름을 부르면 just 가 죽는다.
        deps = tuple(dep for dep in recipe.deps if dep not in taken)
        if recipe.deps and not deps:
            continue
        lines += ["", f"# {recipe.doc}", f"{recipe.name}:" + (" " + " ".join(deps) if deps else "")]
        lines += [f"    {command}" for command in recipe.commands]
    if len(lines) == 1:
        lines.append("")
        lines.append("# No run command is backed by a checked-in manifest yet — add yours above.")
    lines += ["", END]
    return "\n".join(lines) + "\n"


def render(existing: str, recipes: list[Recipe]) -> tuple[str, tuple[str, ...], bool]:
    """(새 본문, 뺀 이름들, 구역을 덧붙였는지). 구역 밖 내용은 바이트 그대로 살아남는다.

    한 자리만 예외다: 구역 END 바로 뒤에 빈 줄이 여럿 있으면 아래 `lstrip` 이 하나로 줄인다.
    글자는 하나도 안 없어지고 두 번째 sync 부터는 아무것도 안 바뀌지만, "바이트 그대로"가
    그 공백까지 덮지는 않는다."""
    text = existing or _HEADER
    taken = _outside_names(text)
    block = managed_block(recipes, skip=taken)
    skipped = tuple(sorted(recipe.name for recipe in recipes if recipe.name in taken))
    start = text.find(BEGIN)
    end = text.find(END)
    if start == -1 or end == -1 or end < start:
        # 사람이 먼저 쓴 Justfile — 있던 내용은 안 건드리고 구역만 끝에 붙인다.
        joined = text if text.endswith("\n") else text + "\n"
        return joined + "\n" + block, skipped, True
    tail = text[end + len(END) :].lstrip("\n")
    return text[:start] + block + (("\n" + tail) if tail else ""), skipped, False


def sync(root: str, *, dry_run: bool = False, create: bool = True) -> SyncResult:
    """관리 구역을 지금 매니페스트 상태로 다시 그린다. 없으면 Justfile 을 만든다.

    `create=False` 는 **아무도 안 시킨 자리**(`asgard sync`, 셋업)가 쓴다: 파일이 없으면 아무
    일도 안 한다. 레시피가 감지되든 말든 마찬가지다 — 감지됐다고 만들면 실행 표면을 쓰기로 한
    적 없는 저장소 뿌리에 파일이 생기고, 그건 사용자가 고를 일이지 도구가 고를 일이 아니다.
    실행 표면은 `asgard just init` 으로 들어온다.

    이미 있는 파일은 그 저장소가 이미 골랐다는 뜻이라, 지도와 같은 자리에서 같이 갱신된다."""
    path = find_justfile(root)
    created = path is None
    if created and not create:
        return SyncResult(default_path(root), False, False, (), (), False)
    path = path or default_path(root)
    existing = "" if created else io_files.read_text(path)
    recipes = detect_recipes(root)
    content, skipped, appended = render(existing, recipes)
    changed = content != existing
    if changed and not dry_run:
        io_files.write_text(path, content)
    names = tuple(name for name, _ in parse_recipes(managed_block(recipes, skip=_outside_names(content))))
    return SyncResult(path, created, changed, names, skipped, appended)


def check(root: str) -> list[str]:
    """드리프트 — doctor 와 CI 가 읽는다. 빈 목록이 통과다.

    Justfile 이 없는 것은 드리프트가 아니다. 실행 표면은 저장소가 고르는 것이라, 안 고른 것을
    결함으로 부르면 도구가 고른 셈이 된다. 부르는 쪽이 "없다"를 알아야 하면 `find_justfile` 이
    None 을 준다."""
    path = find_justfile(root)
    if path is None:
        return []
    text = io_files.read_text(path)
    name = os.path.basename(path)
    issues: list[str] = []
    if BEGIN not in text or END not in text:
        issues.append(f"{name} has no asgard managed region — `asgard just sync` appends one.")
    content, _skipped, _appended = render(text, detect_recipes(root))
    if content != text:
        issues.append(f"{name} managed recipes are stale — run `asgard just sync`.")
    duplicates = _duplicates(text)
    if duplicates:
        issues.append(f"{name} defines {', '.join(duplicates)} more than once — just refuses the whole file.")
    return issues


# just 가 플랫폼마다 하나만 살리는 속성 — 이 표식이 붙은 정의는 같은 이름이 여럿이어도 합법이다.
_OS_GATES = frozenset({"linux", "macos", "openbsd", "unix", "windows"})


def _duplicates(text: str) -> list[str]:
    """같은 플랫폼에서 둘이 동시에 살아 충돌하는 이름.

    판정은 "이 이름의 정의가 둘 이상인데 그중 하나라도 플랫폼 표식이 없다" 하나다. 표식 없는
    정의는 어느 플랫폼에서도 살아 있으므로 옆에 무엇이 있든 부딪힌다.

    lagom: 같은 표식이 두 번 붙은 짝(`[unix]` 둘)은 못 잡는다. 그 자리는 just 자신이 즉시
    말해 주고, 반대로 넓게 잡으면 `[unix]`/`[windows]` 두 벌을 쓰는 저장소가 영원히 빨간불이
    된다 — 넓히려면 표식 집합의 교집합까지 봐야 한다."""
    seen: dict[str, list[bool]] = {}
    for defined, _doc, attributes in _definitions(text):
        seen.setdefault(defined, []).append(bool(attributes & _OS_GATES))
    return sorted(name for name, gated in seen.items() if len(gated) > 1 and not all(gated))


def just_version() -> str | None:
    """설치된 just 의 버전 문자열, 없으면 None."""
    binary = shutil.which("just")
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError, subprocess.SubprocessError:
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def ensure_just(*, force: bool = False) -> tuple[str, str]:
    """이 기계에 just 가 서 있게 한다 → (상태, 설명). 상태 = present | installed | unavailable.

    설치는 `uv tool install rust-just` 하나다. 설치기가 uv 를 먼저 깔고 그 위에 asgard 를
    올리므로(install.sh·install.ps1) 설치가 끝난 기계에서 존재가 보장된 것은 uv 뿐이고,
    그 도구 bin 은 asgard 자신이 이미 올라앉은 PATH 자리다 — 새로 PATH 를 손댈 일이 없다.

    실패는 올리지 않는다. just 가 없다고 asgard 가 못 도는 것은 아니고, 설치를 못 하는 자리
    (네트워크 없음, uv 없음)에서 설치를 끊는 것보다 상태를 돌려주는 쪽이 부르는 쪽에 쓸모 있다."""
    from .platform import ensure_user_path

    ensure_user_path()
    if not force:
        version = just_version()
        if version:
            return "present", version
    uv = shutil.which("uv")
    if not uv:
        return "unavailable", "uv is not on PATH — install just yourself: https://just.systems"
    try:
        proc = subprocess.run(
            [uv, "tool", "install", "--quiet", JUST_PACKAGE],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "unavailable", f"`uv tool install {JUST_PACKAGE}` could not run: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return "unavailable", detail[-1] if detail else f"`uv tool install {JUST_PACKAGE}` exited {proc.returncode}"
    ensure_user_path()
    return "installed", just_version() or JUST_PACKAGE
