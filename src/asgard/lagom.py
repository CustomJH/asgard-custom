"""Lagom — 미니멀리즘 사다리(코드 축) + 산출 압축(산출 축)의 모드 계층.

2계층 상태 (26-07-15 설정 통합):
  영속 기본값  asgard-setting-{project,global}.json 의 lagom.mode (구 config.toml 폴백)
              + LAGOM_MODE env
  세션 런타임  .asgard/state/lagom-mode.json — 훅 3종·네이티브 루프가 공유하는 유일한 접점

resolve 우선순위: 플래그 > LAGOM_MODE env > 프로젝트 설정 > 글로벌 설정 > 기본 full.
review 는 세션 한정 스킬 모드 — 영속 기본값으로 저장 불가 (원본 설계 계승).
훅은 standalone(무임포트)이라 이 모듈을 쓰지 못한다 — 같은 규칙을 각 훅이 내장하며
"동일 유지 (단일 출처 원칙)" 주석으로 이 파일을 가리킨다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess

MODES = ("off", "lite", "full")
DEFAULT_MODE = "full"  # default-on — asgard init 프로젝트는 별도 설정 없이 full 로 돈다
STATE_FILE = "lagom-mode.json"  # <root>/.asgard/state/ 아래 — 런타임 상태 격리 (설정 아님)
# 레거시 (읽기 호환 → 다음 쓰기에서 제거): .asgard/ 직하 json(0.4.x 말) / 단일 문자열(0.4.1 이하)
LEGACY_STATE_FILES = ("lagom-mode.json", "lagom-mode")

# 문체 강제는 프롬프트 순응만 믿지 않는다. 아래 검사는 자연어 산출의 명백한 위반만 잡는
# 보수적 하한선이다. 코드·인용·URL은 원문 보존 계약 때문에 검사에서 제외한다.
_HYPE = re.compile(
    r"Executive Summary|혁신적|강력한|획기적|압도적|게임[ -]?체인저|핵심 가치는|견고한 초석|경쟁 우위",
    re.IGNORECASE,
)
_UNSUPPORTED = (
    ("보장", re.compile(r"보장")),
    ("효과 담보", re.compile(r"담보")),
    ("즉시 배포", re.compile(r"즉시\s*배포")),
    ("제약 없음", re.compile(r"제약(?:이|은)?\s*없")),
    ("효율 향상", re.compile(r"효율(?:성)?(?:이)?\s*(?:높|향상|개선)|효율(?:성)?을\s*(?:높|개선)")),
    ("부담 감소", re.compile(r"부담(?:을|이)?\s*(?:낮|줄|감소|적|없)")),
    ("위험 최소화", re.compile(r"(?:위험|리스크|장애|취약점|검토 범위|노출 표면).{0,20}최소화|원천\s*차단")),
    (
        "신뢰성·안정성",
        re.compile(r"(?:신뢰성|안정성)(?:을|이)?\s*(?:높|향상|확보|보장|구현|제공)|최대한의\s*안정성"),
    ),
    ("기술 부채 감소", re.compile(r"기술\s*부채.{0,12}(?:절감|감소|줄)")),
    ("근원적 해결", re.compile(r"근원적(?:으로)?\s*해결")),
    ("설정 없는 즉시 실행", re.compile(r"환경\s*설정\s*없이|바로\s*실행\s*가능")),
    ("유지보수 효과", re.compile(r"유지보수|유지관리")),
)
_FOREIGN_DUP = re.compile(r"[가-힣]{2,}\s*\([A-Za-z][A-Za-z0-9 .+/#-]{1,40}\)")
_COINED_TERM = re.compile(r"무의존성|제로\s*디펜던시", re.IGNORECASE)
_CORRECTION_META = re.compile(r"문체\s*(?:계약|정책|규율)|하이프|대체안.{0,12}제시|요청.{0,20}쓸\s*수\s*없")
_ACRONYM = re.compile(r"(?<![A-Z0-9])[A-Z][A-Z0-9]{2,9}(?![A-Z0-9])")
_KNOWN_TERMS = {
    "API",
    "ASCII",
    "CLI",
    "CPU",
    "CSS",
    "GPU",
    "HTML",
    "HTTP",
    "HTTPS",
    "JSON",
    "PR",
    "RAM",
    "REST",
    "SDK",
    "SQL",
    "TUI",
    "UI",
    "URL",
    "UTF",
    "UUID",
    "UX",
    "XML",
    "YAML",
}
_PROSE_EXTENSIONS = {".md", ".mdx", ".txt", ".rst", ".adoc"}


def _lintable_text(text: str) -> str:
    """코드 블록·인용·인라인 코드·URL을 지운 검사 사본. 원문은 바꾸지 않는다."""
    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or line.lstrip().startswith(">"):
            continue
        line = re.sub(r"`[^`]*`", "", line)
        line = re.sub(r"https?://\S+", "", line)
        out.append(line)
    return "\n".join(out)


def style_violations(text: str, source: str = "") -> list[str]:
    """명백한 Lagom 문체 위반을 반환한다. source에 명시된 효용 주장은 새 추론으로 보지 않는다."""
    body = _lintable_text(text)
    evidence = _lintable_text(source)
    found: list[str] = []
    for phrase in dict.fromkeys(m.group(0) for m in _HYPE.finditer(body)):
        found.append(f"과장 표현: {phrase}")
    for phrase in dict.fromkeys(m.group(0) for m in _FOREIGN_DUP.finditer(body)):
        found.append(f"불필요한 외국어 병기: {phrase}")
    for phrase in dict.fromkeys(m.group(0) for m in _COINED_TERM.finditer(body)):
        found.append(f"불필요한 조어: {phrase}")
    for phrase in dict.fromkeys(m.group(0) for m in _CORRECTION_META.finditer(body)):
        found.append(f"교정 메타 설명: {phrase}")
    for label, pattern in _UNSUPPORTED:
        if pattern.search(body) and not pattern.search(evidence):
            found.append(f"근거 없는 효용: {label}")
    source_terms = set(_ACRONYM.findall(evidence))
    for term in dict.fromkeys(_ACRONYM.findall(body)):
        if term in _KNOWN_TERMS or term in source_terms:
            continue
        # 첫 등장 자리에서 곧바로 정의한 형태는 허용한다: `RAGX는 ...`, `RAGX: ...`, `RAGX(...)`.
        if re.search(rf"(?<![A-Z0-9]){re.escape(term)}(?![A-Z0-9])\s*(?:는|은|이란|:|\()", body):
            continue
        found.append(f"미정의 용어: {term}")
    return found


def _added_prose(root: str, rel: str) -> str:
    """추적 파일은 diff 추가행, 미추적 파일은 전체 본문을 반환한다."""
    tracked = (
        subprocess.run(
            ["git", "-C", root, "ls-files", "--error-unmatch", "--", rel], capture_output=True, text=True, timeout=30
        ).returncode
        == 0
    )
    if not tracked:
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""
    diff = subprocess.run(
        ["git", "-C", root, "diff", "--no-ext-diff", "--unified=0", "--", rel],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    return "\n".join(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))


def changed_prose_violations(root: str, paths: list[str], source: str = "") -> list[str]:
    """변경된 문서의 추가 문장만 검사한다. 기존 문장과 코드 파일은 건드리지 않는다."""
    found: list[str] = []
    base = os.path.realpath(root)
    for raw in dict.fromkeys(paths):
        path = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(root, raw))
        if os.path.commonpath((base, path)) != base or os.path.splitext(path)[1].lower() not in _PROSE_EXTENSIONS:
            continue
        rel = os.path.relpath(path, base)
        for item in style_violations(_added_prose(base, rel), source):
            found.append(f"{rel}: {item}")
    return found


def normalize(mode: object) -> str | None:
    """대소문자 무시·공백 트림. 유효 모드가 아니면 None (review 포함 — 영속·상태 대상 아님)."""
    m = str(mode or "").strip().lower()
    return m if m in MODES else None


def default_mode(root: str | None = None, flag: str | None = None) -> str:
    """영속 기본값 해석 — 플래그 > env > 프로젝트 설정 > 글로벌 설정 > full (settings.py 경유)."""
    m = normalize(flag) or normalize(os.environ.get("LAGOM_MODE"))
    if m:
        return m
    try:
        from .settings import load_global, load_project

        root = root or os.getcwd()
        for cfg in (load_project(root), load_global()):  # 프로젝트가 글로벌을 이긴다
            m = normalize((cfg.get("lagom") or {}).get("mode"))
            if m:
                return m
    except Exception:
        pass  # 없거나 깨진 설정 = 이 계층 침묵 (fail-open)
    return DEFAULT_MODE


def state_path(root: str | None = None) -> str:
    return os.path.join(root or os.getcwd(), ".asgard", "state", STATE_FILE)


def _legacy_state_paths(root: str | None = None) -> list[str]:
    base = os.path.join(root or os.getcwd(), ".asgard")
    return [os.path.join(base, name) for name in LEGACY_STATE_FILES]


def read_state(root: str | None = None) -> str | None:
    """세션 런타임 모드 — state/ JSON 우선, 레거시(.asgard/ 직하 json·단일 문자열) 읽기 호환."""
    try:
        with open(state_path(root), encoding="utf-8") as f:
            return normalize(json.load(f).get("mode"))
    except Exception:
        pass
    for p in _legacy_state_paths(root):
        try:
            with open(p, encoding="utf-8") as f:
                raw = f.read()
            try:
                return normalize(json.loads(raw).get("mode"))
            except Exception:
                return normalize(raw)
        except Exception:
            continue
    return None


def write_state(root: str | None = None, mode: str = DEFAULT_MODE) -> bool:
    """상태를 ``{"mode": ...}`` JSON으로 기록 — best-effort. 반환 = 성공 여부."""
    m = normalize(mode)
    if not m:
        return False
    try:
        p = state_path(root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"mode": m}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        for old in _legacy_state_paths(root):  # 쓰기 시점에 레거시 이관 완료 (이원화 방지)
            try:
                os.remove(old)
            except FileNotFoundError:
                pass
        return True
    except Exception:
        return False


def clear_state(root: str | None = None) -> None:
    for path in (state_path(root), *_legacy_state_paths(root)):
        try:
            os.remove(path)
        except Exception:
            pass


def current_mode(root: str | None = None, flag: str | None = None) -> str:
    """유효 모드 — 세션 전환(상태파일)이 영속 기본값을 이긴다."""
    return read_state(root) or default_mode(root, flag)


def note(root: str | None = None, flag: str | None = None) -> str:
    """네이티브 루프 프롬프트 주입분 — off 면 빈 문자열 (프롬프트 무변화, 토큰 회귀 없음)."""
    mode = current_mode(root, flag)
    if mode == "off":
        return ""
    from .templates.lagom import render_lagom

    body = render_lagom(mode)
    return "\n\n" + body if body else ""
