"""코드 스타일 규격의 **감지** — 이 저장소가 어떤 린터·포매터를 쓰기로 했는지 찾아낸다.

판정과 갈라 둔 이유는 수명이다. 판정(`code_style`)은 도구가 무엇이든 같은 일을 하지만, 이
목록은 생태계가 도구를 하나 낼 때마다 자란다 — 언어를 하나 더 받는 변경이 판정 코드를 한 줄도
안 건드리는 것이 이 경계의 값이다.

찾는 방법은 하나뿐이다: **규격 파일이 디스크에 있는가**. 도구가 PATH 에 깔렸는지는 안 본다
(팀원마다 다르고, 없으면 실행 단계에서 사유가 적힌다). 파일이 없는데 있다고 추측하면 설정에
안 도는 명령이 적히고, 그 상태는 게이트가 꺼진 것과 화면에서 같아진다.

결과는 `asgard style init` 이 설정에 한 번 적고 끝난다. 그 뒤로 이 모듈을 부르는 것은
`style list` 와 `doctor` 뿐이고, 둘 다 "저장소에 있는데 아직 안 적힌 것"을 보여 주려고 부른다.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass

from .code_style import Tool

# 훑을 때 안 내려가는 디렉터리. `code_map._IGNORED_DIRS` 와 뜻이 같지만 사본이 아니라 좁힌
# 목록이다 — 여기서는 점으로 시작하는 **파일**을 남겨야 해서(`.eslintrc`·`.clang-format`)
# 그쪽 걷기를 그대로 못 쓴다.
_PRUNE = frozenset(
    {
        ".git", ".hg", ".svn", ".venv", ".gradle", ".idea", ".mvn",
        "__pycache__", "archive", "build", "coverage", "dist", "htmlcov",
        "node_modules", "out", "ref", "site-packages", "target",
        "third_party", "thirdparty", "vendor", "vendored", "venv",
    }
)  # fmt: skip
_MAX_DEPTH = 5  # 규격 파일은 저장소 뿌리나 모듈 뿌리에 있다 — 더 깊이 찾으면 시험 자산까지 긁는다
_FILES_SLOT = "{files}"


@dataclass(frozen=True)
class Candidate:
    """감지 후보 — 규격 파일이나 매니페스트가 있으면 이 명령이 이 저장소의 스타일 검사다."""

    name: str
    languages: tuple[str, ...]
    check: str
    fix: str = ""
    markers: tuple[str, ...] = ()  # 이 이름의 파일이 하나라도 있으면 후보 (fnmatch)
    inside: tuple[tuple[str, str], ...] = ()  # (매니페스트 이름, 그 안에 있어야 하는 문자열)
    requires: tuple[str, ...] = ()  # 명령을 돌릴 실행기 — 하나라도 있어야 한다
    node: bool = False  # `{pm}` 을 이 저장소의 패키지 매니저로 치환한다


# 언어별 기성 규격. `asgard style init` 이 여기서 골라 설정에 적고, 그 뒤로는 사용자가 정본이다.
# 목록이 짧은 것이 아니라 **감지 가능한 것만** 있다: 규격 파일도 매니페스트 흔적도 없는 도구는
# 여기 못 들어온다 (있다고 추측하면 설정에 안 도는 명령이 적힌다).
_CATALOG: tuple[Candidate, ...] = (
    # ── JVM
    Candidate(
        "checkstyle",
        (".java",),
        "./gradlew checkstyleMain checkstyleTest --console=plain",
        markers=("checkstyle.xml", "checkstyle-rules.xml", "google_checks.xml", "sun_checks.xml"),
        requires=("gradlew",),
    ),
    Candidate(
        "checkstyle",
        (".java",),
        "mvn -B -q checkstyle:check",
        markers=("checkstyle.xml", "checkstyle-rules.xml"),
        requires=("pom.xml",),
    ),
    Candidate(
        "spotless",
        (".java", ".kt", ".groovy"),
        "./gradlew spotlessCheck --console=plain",
        fix="./gradlew spotlessApply",
        inside=(("build.gradle", "spotless"), ("build.gradle.kts", "spotless")),
        requires=("gradlew",),
    ),
    Candidate(
        "spring-javaformat",
        (".java",),
        "./gradlew checkFormat --console=plain",
        fix="./gradlew format",
        markers=(".springjavaformatconfig",),
        requires=("gradlew",),
    ),
    Candidate(
        "pmd",
        (".java",),
        "./gradlew pmdMain --console=plain",
        inside=(("build.gradle", "pmd"), ("build.gradle.kts", "pmd")),
        requires=("gradlew",),
    ),
    Candidate(
        "ktlint",
        (".kt", ".kts"),
        "./gradlew ktlintCheck --console=plain",
        fix="./gradlew ktlintFormat",
        inside=(("build.gradle", "ktlint"), ("build.gradle.kts", "ktlint")),
        requires=("gradlew",),
    ),
    Candidate(
        "detekt",
        (".kt", ".kts"),
        "./gradlew detekt --console=plain",
        markers=("detekt.yml", "detekt.yaml"),
        requires=("gradlew",),
    ),
    # ── JavaScript · TypeScript
    Candidate(
        "eslint",
        (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte"),
        "{pm} eslint " + _FILES_SLOT,
        fix="{pm} eslint --fix " + _FILES_SLOT,
        markers=(
            "eslint.config.js",
            "eslint.config.mjs",
            "eslint.config.cjs",
            "eslint.config.ts",
            ".eslintrc",
            ".eslintrc.js",
            ".eslintrc.cjs",
            ".eslintrc.json",
            ".eslintrc.yml",
            ".eslintrc.yaml",
        ),
        requires=("package.json",),
        node=True,
    ),
    Candidate(
        "prettier",
        (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte", ".css", ".scss", ".json", ".md"),
        "{pm} prettier --check " + _FILES_SLOT,
        fix="{pm} prettier --write " + _FILES_SLOT,
        markers=(
            ".prettierrc",
            ".prettierrc.json",
            ".prettierrc.js",
            ".prettierrc.yml",
            ".prettierrc.yaml",
            "prettier.config.js",
            "prettier.config.mjs",
            "prettier.config.cjs",
        ),
        requires=("package.json",),
        node=True,
    ),
    Candidate(
        "biome",
        (".js", ".jsx", ".ts", ".tsx", ".json", ".css"),
        "{pm} biome check " + _FILES_SLOT,
        fix="{pm} biome check --write " + _FILES_SLOT,
        markers=("biome.json", "biome.jsonc"),
        requires=("package.json",),
        node=True,
    ),
    Candidate(
        "stylelint",
        (".css", ".scss", ".less", ".vue"),
        "{pm} stylelint " + _FILES_SLOT,
        fix="{pm} stylelint --fix " + _FILES_SLOT,
        markers=(".stylelintrc", ".stylelintrc.json", ".stylelintrc.js", "stylelint.config.js", "stylelint.config.mjs"),
        requires=("package.json",),
        node=True,
    ),
    # ── Python
    Candidate(
        "ruff",
        (".py", ".pyi"),
        "ruff check --output-format=concise " + _FILES_SLOT,
        fix="ruff check --fix " + _FILES_SLOT,
        markers=("ruff.toml", ".ruff.toml"),
        inside=(("pyproject.toml", "[tool.ruff"),),
    ),
    Candidate(
        "ruff-format",
        (".py", ".pyi"),
        "ruff format --check " + _FILES_SLOT,
        fix="ruff format " + _FILES_SLOT,
        markers=("ruff.toml", ".ruff.toml"),
        inside=(("pyproject.toml", "[tool.ruff"),),
    ),
    Candidate(
        "black",
        (".py", ".pyi"),
        "black --check " + _FILES_SLOT,
        fix="black " + _FILES_SLOT,
        inside=(("pyproject.toml", "[tool.black"),),
    ),
    Candidate("flake8", (".py",), "flake8 " + _FILES_SLOT, markers=(".flake8",)),
    # ── Go · Rust
    Candidate("gofmt", (".go",), "gofmt -l " + _FILES_SLOT, fix="gofmt -w " + _FILES_SLOT, requires=("go.mod",)),
    Candidate(
        "golangci-lint",
        (".go",),
        "golangci-lint run",
        markers=(".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json"),
    ),
    Candidate("rustfmt", (".rs",), "cargo fmt --check", fix="cargo fmt", requires=("Cargo.toml",)),
    Candidate("clippy", (".rs",), "cargo clippy --all-targets -- -D warnings", requires=("Cargo.toml",)),
    # ── C · C++ · C#
    Candidate(
        "clang-format",
        (".c", ".h", ".cc", ".cpp", ".hpp", ".cxx", ".m", ".mm"),
        "clang-format --dry-run --Werror " + _FILES_SLOT,
        fix="clang-format -i " + _FILES_SLOT,
        markers=(".clang-format",),
    ),
    Candidate("clang-tidy", (".c", ".cc", ".cpp", ".cxx"), "clang-tidy " + _FILES_SLOT, markers=(".clang-tidy",)),
    Candidate("dotnet-format", (".cs",), "dotnet format --verify-no-changes", fix="dotnet format", requires=("*.sln",)),
    # ── 그 밖
    Candidate(
        "swiftlint",
        (".swift",),
        "swiftlint lint --quiet " + _FILES_SLOT,
        fix="swiftlint --fix " + _FILES_SLOT,
        markers=(".swiftlint.yml",),
    ),
    Candidate(
        "rubocop",
        (".rb", ".rake"),
        "bundle exec rubocop " + _FILES_SLOT,
        fix="bundle exec rubocop -a " + _FILES_SLOT,
        markers=(".rubocop.yml",),
    ),
    Candidate(
        "php-cs-fixer",
        (".php",),
        "vendor/bin/php-cs-fixer fix --dry-run --diff",
        fix="vendor/bin/php-cs-fixer fix",
        markers=(".php-cs-fixer.php", ".php-cs-fixer.dist.php"),
    ),
    Candidate(
        "phpcs",
        (".php",),
        "vendor/bin/phpcs " + _FILES_SLOT,
        fix="vendor/bin/phpcbf " + _FILES_SLOT,
        markers=("phpcs.xml", "phpcs.xml.dist"),
    ),
    Candidate("shellcheck", (".sh", ".bash"), "shellcheck " + _FILES_SLOT, markers=(".shellcheckrc",)),
    Candidate(
        "sqlfluff",
        (".sql",),
        "sqlfluff lint " + _FILES_SLOT,
        fix="sqlfluff fix " + _FILES_SLOT,
        markers=(".sqlfluff",),
    ),
    Candidate(
        "terraform-fmt",
        (".tf", ".tfvars"),
        "terraform fmt -check -recursive",
        fix="terraform fmt -recursive",
        markers=("*.tf",),
    ),
    Candidate(
        "dart-format",
        (".dart",),
        "dart format --output=none --set-exit-if-changed " + _FILES_SLOT,
        fix="dart format " + _FILES_SLOT,
        requires=("pubspec.yaml",),
    ),
)


def _tracked(root: str) -> list[str] | None:
    """Git 이 이 저장소의 것이라고 보는 파일들. Git 이 아니면 None.

    걷기보다 Git 을 먼저 묻는 이유는 경계다. 이 저장소의 `workspace/` 처럼 gitignore 된
    시험 자산 안에도 `gradlew` 와 `checkstyle.xml` 이 있고, 그것을 긁으면 감지가 남의
    빌드를 이 프로젝트의 규격이라고 적는다 (26-08-19 실측 — Java 도구 넷이 그렇게 걸렸다).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", root, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True, check=False, timeout=30,
        )  # fmt: skip
    except OSError, subprocess.SubprocessError:
        return None
    if proc.returncode != 0:
        return None
    rows = [raw.decode("utf-8", "replace").replace("\\", "/") for raw in proc.stdout.split(b"\0") if raw]
    return rows or None


def _scan(root: str) -> dict[str, list[str]]:
    """파일 이름 → 그 이름을 가진 파일들의 저장소 상대 경로. 훑기는 한 번뿐이다."""
    listed = _tracked(root)
    if listed is None:
        listed = []
        base_depth = root.rstrip(os.sep).count(os.sep)
        for current, dirs, names in os.walk(root):
            if current.count(os.sep) - base_depth >= _MAX_DEPTH:
                dirs[:] = []
            dirs[:] = sorted(d for d in dirs if d not in _PRUNE and not (d.startswith(".") and d != ".github"))
            listed += [os.path.relpath(os.path.join(current, n), root).replace("\\", "/") for n in names]
    found: dict[str, list[str]] = {}
    for rel in listed:
        parts = rel.split("/")
        if len(parts) > _MAX_DEPTH or any(p in _PRUNE for p in parts[:-1]):
            continue
        found.setdefault(parts[-1], []).append(rel)
    return found


def _package_manager(found: dict[str, list[str]]) -> str:
    if "pnpm-lock.yaml" in found:
        return "pnpm exec"
    if "yarn.lock" in found:
        return "yarn"
    if "bun.lockb" in found or "bun.lock" in found:
        return "bunx"
    return "npx"


def _matches(found: dict[str, list[str]], patterns: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            for name, paths in found.items():
                if fnmatch.fnmatch(name, pattern):
                    hits += paths
        else:
            hits += found.get(pattern, [])
    return hits


def _contains(path: str, needle: str) -> bool:
    """이 파일 앞부분에 이 문자열이 있는가. 못 읽으면 없는 것으로 본다 (감지는 막는 판정이 아니다)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return needle in handle.read(200_000)
    except OSError:
        return False


def _mentions(root: str, found: dict[str, list[str]], inside: tuple[tuple[str, str], ...]) -> list[str]:
    """gradle 플러그인처럼 자기 규격 파일이 없는 도구는 매니페스트 본문으로 찾는다 — 그 매니페스트들."""
    return [
        rel
        for manifest, needle in inside
        for rel in found.get(manifest, [])[:40]
        if _contains(os.path.join(root, rel), needle)
    ]


def _dirname(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _runner_dir(marker_dir: str, runners: set[str]) -> str | None:
    """규격 파일에서 위로 올라가며 처음 만나는 실행기 자리. 없으면 None.

    한 저장소에 모듈이 여럿이면 실행기도 여럿이다 (`helios-be/gradlew`·`helios-fe/package.json`).
    규격 파일마다 자기 실행기를 찾아야 명령이 도는 자리와 그 명령이 맡는 파일이 같이 정해진다.
    """
    current = marker_dir
    while True:
        if current in runners:
            return current
        if not current:
            return None
        current = _dirname(current)


def detect(root: str) -> list[Tool]:
    """이 저장소에서 실제로 찾아낸 스타일 도구들 — `asgard style init` 이 설정에 적을 후보.

    감지는 규격 파일과 매니페스트의 존재로만 한다. 도구가 PATH 에 있는지는 안 본다: 팀원마다
    다르고, 없으면 실행 단계에서 `error` 로 적히지 조용히 사라지지 않는다.

    모듈이 여럿인 저장소는 도구도 여럿이 나온다 — 이름에 자리를 붙이고(`checkstyle:helios-be`)
    `cwd` 와 `paths` 로 그 모듈만 맡게 한다. 그래야 백엔드를 안 건드린 변경에서 gradle 이 안 돈다.
    """
    found = _scan(root)
    manager = _package_manager(found)
    tools: dict[tuple[str, str], Tool] = {}
    claimed: set[str] = set()  # 이름 하나는 후보 하나가 가진다 — gradle 이 맞으면 maven 은 안 본다
    for candidate in _CATALOG:
        if candidate.name in claimed:
            continue
        anchors = _matches(found, candidate.markers) + _mentions(root, found, candidate.inside)
        if not anchors:
            continue
        marker_dirs = sorted({_dirname(rel) for rel in anchors})
        if candidate.requires:
            runners = {_dirname(rel) for rel in _matches(found, candidate.requires)}
            bases = sorted({base for d in marker_dirs if (base := _runner_dir(d, runners)) is not None})
        else:
            # 실행기가 없는 도구는 파일 경로로 범위를 받는다 — 뿌리에서 부르면 된다.
            bases = [""]
        replace = (lambda text: text.replace("{pm}", manager)) if candidate.node else (lambda text: text)
        for base in bases:
            key = (candidate.name, base)
            claimed.add(candidate.name)
            tools[key] = Tool(
                name=candidate.name + (":" + base if base else ""),
                check=replace(candidate.check),
                fix=replace(candidate.fix),
                languages=candidate.languages,
                paths=(base,) if base else (),
                cwd=base,
            )
    return list(tools.values())
