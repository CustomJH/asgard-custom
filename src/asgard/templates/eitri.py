"""에이트리 전용 스킬 2종 — 빌드 타임(CI 파이프라인·재현성·패키징·릴리스) 심화 지식.

표준 엔지니어링 관행을 우리 용어로 재서술한 자체 캐논이다 — 외부 텍스트 재배포 없음.
CC(.claude/skills/)와 Cursor·Codex 공용(.agents/skills/) 양 스코프에 스캐폴드되어
모드 A/B/네이티브 전부에서 로드 가능하다. 코어 계약 스킬은 thor.eitri_core_skill
(role 파일 단일 소스) — 이 모듈은 심화 층만 담당한다.

리졸버는 토르식 부분 일치 + 단어 경계 2층 — "ci" 같은 짧은 ASCII 용어는 \\b 필수
(certificate·pencil 오발), 배포(deploy)·런타임 거동은 토르 소관이므로 트리거에 넣지 않는다."""

import re

_DRAUPNIR = """\
---
name: asgard-eitri-draupnir
description: Eitri's ring Draupnir — deep knowledge of CI pipelines and build reproducibility. Load before pipeline design, build cache, flaky handling, or image build work.
---

# asgard-eitri-draupnir — 💍 CI Pipelines & Build Reproducibility

Eight identical rings every ninth night — the same inputs must yield the same outputs, whenever and wherever the build runs.

## Pipeline structure

- Cheap checks first (fail fast): static checks → types → unit → integration → build — never make an expensive stage wait on a cheap failure.
- Every stage must be independently re-runnable — no stage may lean on implicit byproducts of earlier stages (global installs, temp files).
- Local-CI parity (deepening the role contract): same check = same command + same tool versions. A check only CI knows, or only local knows, is itself a defect — report it.
- Respect change-detection routing (path → target mapping) where present — switching to a full rebuild requires written justification.

## Cache discipline

- Cache key = hash of inputs (lockfiles, build config) — branch-name or date keys are stale-hit factories.
- A cache is a speed layer, not a correctness layer — results must be identical on a cache miss; if they differ, the cause is an undeclared input, not the cache.
- "Passes locally / fails only in CI": prime suspect is a stale cache — rerun without cache first to bisect whether the cache is the cause.

## Flaky discipline (never paper over with retries)

- A retried pass is not a repair but defect concealment — introduce automatic retries only together with a root-cause triage ticket.
- Classify the cause first: time-dependent / order-dependent / external dependency (network, third party) / resource contention. The classification sets the fix direction.
- Quarantine (temporary exclusion) markers only with a recovery condition and ticket link — a silent skip is a coverage hole.

## Image builds

- Multi-stage — leave no build tools or intermediate artifacts in the final stage.
- Layer order = inverse of change frequency: dependency install before source copy — if one source line invalidates the dependency layer, the cache design has failed.
- Pin base image tags — latest is a declaration that reproducibility has been abandoned.
- Runtime values (HEALTHCHECK, STOPSIGNAL, probes) belong to Thor's canon — only the build stages are this skill's surface.

## Secret boundaries

- Never put secrets in build args or layers — they remain in the image history forever.
- Verify secret masking in CI logs — exposure via echo or error dumps is a common hole.
- Fork-PR execution paths must carry no secrets — external code running in a secret context is itself an incident.

## Verification

- The evidence for a pipeline change is an actual runner execution log — "the syntax is valid" is not verification (Canon 8).
- If the environment cannot execute it, state that limitation in the report and leave a minimal execution path (syntax check + a local equivalent run of the affected stage).
"""

_GULLINBURSTI = """\
---
name: asgard-eitri-gullinbursti
description: Eitri's golden boar Gullinbursti — deep knowledge of packaging, versioning, and release automation. Load before building distributions, version bumps, changelogs, or install-script work.
---

# asgard-eitri-gullinbursti — 🐗 Packaging, Versioning & Releases

It runs shining by its own light even in darkness — a release is an artifact that installs, runs, and rolls back without its maker present.

## Versioning

- One single source of truth for the version — versions scattered across files are synchronized by the bump (script) or derived (injected at build time). Two or more hand-synced locations is a mismatch waiting to happen.
- Breaking (compatibility-destroying) changes go where the version convention demands — if no convention (semver etc.) is adopted, check project practice first (Canon 5).
- Prerelease/candidate notation must sort correctly against final versions — notation that breaks ordering breaks upgrade decisions.

## Artifacts (built ≠ installable)

- The done criterion for packaging is an install smoke test: install in a clean environment → run → verify the version, all actually measured (Canon 8).
- Content check: confirm by listing that unneeded files (test fixtures, caches, dev config) and secrets are absent from the distribution.
- If cross-platform is claimed, verify per platform — never report one platform's pass as a total pass.

## Changelog

- In the user's language: what changed and what they must do — a pasted commit log is not a changelog.
- Breaking changes and migration guidance at the very top — what users must know first comes first.

## Release procedure (no order inversion)

- All gates green → version bump → artifact build & verification → tag. Tagging first and fixing after produces "same tag, different contents."
- Release boundary (role contract): Eitri's share ends at local artifact build & verification — publish, image push, tag push, and deploy return an execution plan (targets, impact, rollback) as the deliverable; approval is Odin's share.

## Rollback

- State a rollback path for every release: can the previous version be reinstalled, and do data/config migrations block the reverse direction?
- For a defective release, check and follow the recall procedure (yank and the like) — no silent overwrites.

## Install scripts

- Idempotent: rerunning must be safe — running on an already-installed state reaches the same end state.
- Abort on first failure + clean up partial-install debris — never leave a half-installed environment.
- Never assume platform or prerequisite tools — check for them; if missing, stop with explicit guidance instead of proceeding on guesses.
"""

EITRI_SKILLS: list[tuple[str, str]] = [
    ("asgard-eitri-draupnir", _DRAUPNIR),
    ("asgard-eitri-gullinbursti", _GULLINBURSTI),
]

# 네이티브 디스패치 task → 전용 스킬 매칭 (파일 스킬 로더가 없는 asgard start 세션용 통로 —
# 모드 A/B 는 파일 스킬이 담당). 배포(deploy)·런타임 거동은 토르 소관 — 트리거에 넣지 않는다.
_SUBSTR: dict[str, tuple[str, ...]] = {
    "asgard-eitri-draupnir": (
        "파이프라인",
        "pipeline",
        "github actions",
        "gitlab",
        "jenkins",
        "빌드 캐시",
        "build cache",
        "빌드 실패",
        "build fail",
        "빌드 그래프",
        "재현성",
        "reproducib",
        "락파일",
        "lockfile",
        "flaky",
        "프리커밋",
        "pre-commit",
        "docker build",
        "dockerfile",
        "이미지 빌드",
        "멀티스테이지",
        "multi-stage",
    ),
    "asgard-eitri-gullinbursti": (
        "패키징",
        "packaging",
        "릴리스",
        "release",
        "체인지로그",
        "changelog",
        "semver",
        "버전 범프",
        "version bump",
        "버저닝",
        "versioning",
        "wheel",
        "sdist",
        "npm publish",
        "pypi",
        "설치 스크립트",
        "install script",
        "installer",
        "install.sh",
        "git tag",
        "아티팩트",
        "artifact",
        "배포판",
    ),
}
# 짧은 ASCII 용어는 단어 경계 필수 — 부분 일치면 certificate→ci, pencil→ci 류 통제 불가.
_WORD_RE: dict[str, tuple[str, ...]] = {
    "asgard-eitri-draupnir": (r"\bci\b", r"\bci/cd\b", r"\bworkflow ya?ml\b", r"\brunner\b"),
    "asgard-eitri-gullinbursti": (r"\btag(ging)?\s*(push|생성|릴리스)", r"릴리스\s*태그"),
}


def resolve_eitri_skills(task: str) -> list[tuple[str, str]]:
    """디스패치 task → 매칭된 전용 스킬 (이름, frontmatter 제거 본문) — 0-LLM 휴리스틱.

    네이티브 에이트리 자식 세션의 system 에 직접 주입할 본문을 고른다 (파일 스킬 로더 부재 보완).
    무매칭 = 빈 리스트 (fail-open — role 본문 기준으로 진행, role 이 이미 그 폴백을 선언한다).
    복수 매칭은 전부 주입 — 릴리스용 파이프라인처럼 두 표면이 겹치는 과업이 실재한다."""
    t = task.lower()

    def hit(name: str) -> bool:
        return any(k in t for k in _SUBSTR.get(name, ())) or any(re.search(p, t) for p in _WORD_RE.get(name, ()))

    return [(name, body.split("---", 2)[2].lstrip()) for name, body in EITRI_SKILLS if hit(name)]
