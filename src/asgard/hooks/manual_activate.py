#!/usr/bin/env python3
# Asgard manual-activate — 오딘이 쓴 커스텀 매뉴얼 주입 (모드 B: Claude Code/Codex/Cursor).
#
# 자리는 두 층이다. 공통(활성 에이전트 홈 `~/.asgard/MANUAL.md` + `manual/*.md`)은 이 기계의 모든
# 프로젝트에 걸리고, 프로젝트(리포 루트 `MANUAL.md`, `.asgard/MANUAL.md`, `.asgard/manual/*.md`)는
# 그 저장소에만 걸린다. 순서는 공통 먼저·프로젝트 나중이고, 충돌하면 나중 것이 이긴다 — 그 규칙을
# 렌더 헤더가 모델에게 문장으로 말한다. 별칭은 어느 자리에서나 CUSTOM_MANUAL.md·CUSTOM.md·RULES.md.
#
# 네이티브 Heimdall 은 manual.py note() 를 프롬프트에 직접 주입하지만, 모드 B 는 서브에이전트가
# AGENTS.md 를 읽는 구조라 닿지 않는다 — charter 와 동일하게 훅으로 보상한다. 동작:
#   agent_type 없음 (SessionStart/UserPromptSubmit) → identity 절 stdout 주입 (메인 스레드)
#   agent_type 있음 (SubagentStart) → 역할별 JSON additionalContext:
#     asgard-thinker  → criteria 환원 지시
#     asgard-worker   → "네가 쓰는 코드에 적용된다" (charter 와 갈리는 유일한 자리 — 아래 주석)
#     asgard-verifier → 명시 규칙 위반 = 반례 FAIL, 단 criteria 대체 아님
#     그 외(딜리버리 freyja/thor/eitri/loki) → identity 절
# 렌더 문구는 asgard/manual.py render() 와 **동일 유지 (단일 출처 원칙)** — 훅은 무임포트라 재구현
# 하고, tests/test_manual_hook.py 가 두 렌더의 바이트 동일성을 대조한다.
# fail-open: 매뉴얼 부재·파손·훅 오류는 전부 무개입 통과 (exit 0) — 세션을 막지 않는다.
import json
import os
import re
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 훅 판정이 통째로 증발한다. UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass


# manual.py 상수와 동일 유지
MANUAL_NAMES = ("MANUAL.md", "CUSTOM_MANUAL.md", "CUSTOM.md", "RULES.md")
ASGARD_DIR = ".asgard"
MANUAL_DIR = "manual"
MARKER = "asgard:manual"
MAX_CHARS = 16000
MIN_CHARS, CEIL_CHARS = 500, 60000
FRAGMENT_CAP = 32
# 에인헤랴르 홈 해석 — profiles.py / agent_activate.py 와 동일 유지
PROFILES_DIR = "profiles"
ACTIVE_FILE = "active_profile"
DEFAULT_PROFILE = "default"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# 숫자 파싱 실패 두 종. 이름으로 묶는 이유는 취향이 아니다: 훅은 asgard 의 venv 가 아니라
# 사용자 PATH 의 python3 로 돈다(`platform.hook_python`). 괄호 없는 다중 except 는 3.14+
# 문법(PEP 758)이라 3.13 이하 기계에선 이 파일이 임포트 시점 SyntaxError 가 되고, 훅 계약이
# fail-open 이라 그 죽음이 **조용하다** — 사용자는 계층이 켜진 줄 안다. 그렇다고 괄호로 쓰면
# 이 리포의 포매터(target-version=py314)가 도로 벗긴다. 이름은 포매터가 못 건드린다.
# tests/test_architecture.py 의 문법 바닥 검사가 이 불변식을 지킨다.
_BAD_NUMBER = (TypeError, ValueError)
_BAD_PATH = (OSError, ValueError)  # 끊어진 링크 · 순환 · 다른 드라이브(Windows) — 같은 이유로 이름


def _meaningful(text):
    return _COMMENT.sub("", text).strip()


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return ""


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            d = json.load(handle)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def user_home():
    """HOME 우선 — Windows 에서 expanduser 는 HOME 을 안 보고 USERPROFILE 만 본다
    (settings.machine_dir / profiles.root 와 동일 유지)."""
    return os.environ.get("HOME") or os.path.expanduser("~")


def root_dir():
    return os.path.join(user_home(), ASGARD_DIR)


def _norm(value):
    text = str(value or "").strip()
    if not text:
        return ""
    canon = DEFAULT_PROFILE if text.casefold() == DEFAULT_PROFILE else text.lower()
    return canon if canon == DEFAULT_PROFILE or ID_RE.match(canon) else ""


def home():
    """활성 에이전트의 홈 — 공통 매뉴얼과 전역 설정이 사는 곳 (profiles.home() 과 동일 유지).

    사다리: ASGARD_HOME → ASGARD_PROFILE → 루트의 active_profile → 기계 뿌리."""
    env_home = str(os.environ.get("ASGARD_HOME") or "").strip()
    if env_home:
        return os.path.abspath(os.path.expanduser(env_home))
    name = _norm(os.environ.get("ASGARD_PROFILE")) or _norm(_read(os.path.join(root_dir(), ACTIVE_FILE)))
    if name and name != DEFAULT_PROFILE:
        return os.path.abspath(os.path.join(root_dir(), PROFILES_DIR, name))
    return os.path.abspath(root_dir())


def _configs(root):
    """프로젝트 > 글로벌 순 — settings.section() 의 병합 사다리와 동일 유지 (단일 출처 원칙)."""
    return (
        _read_json(os.path.join(root, ASGARD_DIR, "asgard-setting-project.json")),
        _read_json(os.path.join(home(), "asgard-setting-global.json")),
    )


def enabled(root):
    raw = str(os.environ.get("ASGARD_MANUAL") or "").strip().lower()
    if raw in ("on", "off"):
        return raw == "on"
    for cfg in _configs(root):
        m = str((cfg.get("manual") or {}).get("mode") or "").strip().lower()
        if m in ("on", "off"):
            return m == "on"
    return True


def max_chars(root):
    for cfg in _configs(root):
        raw = (cfg.get("manual") or {}).get("max_chars")
        if raw is None:
            continue
        try:
            return max(MIN_CHARS, min(CEIL_CHARS, int(raw)))
        except _BAD_NUMBER:
            return MAX_CHARS
    return MAX_CHARS


def _inside(path, fence):
    """manual.py _inside() 와 동일 유지 — 링크 대상이 울타리 안인가 (fence=None 이면 참).

    울타리 없이 두면 저장소가 커밋한 `MANUAL.md -> ../../.ssh/id_rsa` 가 그대로 매뉴얼이 되어
    프롬프트로 나간다. 훅은 PreToolUse 판독 게이트가 보는 자리가 아니라 여기서 막아야 한다."""
    if fence is None:
        return True
    try:
        base = os.path.realpath(fence)
        return os.path.commonpath([os.path.realpath(path), base]) == base
    except _BAD_PATH:
        return False


def _primary_in(base, fence=None):
    found = [os.path.join(base, n) for n in MANUAL_NAMES if os.path.isfile(os.path.join(base, n))]
    kept, escaped = [], []
    for path in found:
        (kept if _inside(path, fence) else escaped).append(path)
    return kept, escaped


def _fragments_in(base, fence=None):
    frag_dir = os.path.join(base, MANUAL_DIR)
    names = []
    if os.path.isdir(frag_dir):
        try:
            names = sorted(
                n
                for n in os.listdir(frag_dir)
                if n.lower().endswith(".md") and os.path.isfile(os.path.join(frag_dir, n))
            )
        except OSError:
            names = []
    paths = [os.path.join(frag_dir, n) for n in names]
    kept = [p for p in paths if _inside(p, fence)]
    escaped = [p for p in paths if not _inside(p, fence)]
    return kept[:FRAGMENT_CAP], kept[FRAGMENT_CAP:], escaped


def discover(root):
    """manual.py discover() 와 동일 유지 — {files[], shadowed[], dropped[], escaped[]}."""
    root = os.path.abspath(root)
    files, shadowed, dropped, escaped = [], [], [], []

    def take(base, with_fragments, fence):
        found, out = _primary_in(base, fence)
        escaped.extend(out)
        if found:
            files.append(found[0])
            shadowed.extend(found[1:])
        if with_fragments:
            keep, drop, frag_out = _fragments_in(base, fence)
            files.extend(keep)
            dropped.extend(drop)
            escaped.extend(frag_out)

    # 울타리: 프로젝트 층은 리포 안, 공통 층(홈)은 없음 — manual.py 와 동일 판정.
    take(home(), True, None)  # ① 공통 — 이 기계의 모든 프로젝트
    take(root, False, root)  # ② 이 프로젝트 — 리포 루트
    take(os.path.join(root, ASGARD_DIR), True, root)  # ③ 이 프로젝트 — 보조 자리 + 조각
    seen, unique = set(), []
    for path in files:  # 홈 안에서 돌면 같은 파일이 두 층에 걸린다 — 순서를 지키며 한 번만
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            unique.append(path)
    return {"files": unique, "shadowed": shadowed, "dropped": dropped, "escaped": escaped}


def is_common(path):
    base = home()
    try:
        return os.path.commonpath([os.path.abspath(path), base]) == base
    except ValueError:
        return False


def label(root, path):
    """manual.py label() 과 동일 유지 — 프로젝트 안이면 상대경로, 홈 안이면 `~/…`."""
    root, path = os.path.abspath(root), os.path.abspath(path)
    if path.startswith(root + os.sep):
        return os.path.relpath(path, root).replace(os.sep, "/")
    user = os.path.abspath(user_home())
    if path.startswith(user + os.sep):
        return "~/" + os.path.relpath(path, user).replace(os.sep, "/")
    return path


def has_marker(path):
    """`asgard init` 이 깐 자리인가 — 표식은 주석 안이라 주입엔 안 실린다 (manual.py 와 동일 유지)."""
    return MARKER in _read(path)


def _cut(body, cap):
    head = body[:cap]
    nl = head.rfind("\n")
    return head[:nl] if nl > cap // 2 else head


def load_manual(root):
    """manual.py load_manual() 과 동일 유지 — 정규화 dict 또는 None."""
    if not enabled(root):
        return None
    root = os.path.abspath(root)
    d = discover(root)
    parts, sources, common, project = [], [], [], []
    for path in d["files"]:
        text = _meaningful(_read(path))
        if not text:
            continue
        name = label(root, path)
        parts.append(text)
        sources.append(name)
        (common if is_common(path) else project).append(name)
    if not parts:
        return None
    body = "\n\n".join(parts)
    cap = max_chars(root)
    truncated = len(body) > cap
    if truncated:
        body = _cut(body, cap)
    return {
        "body": body,
        "sources": sources,
        "common": common,
        "project": project,
        "shadowed": [label(root, p) for p in d["shadowed"]],
        "dropped": [label(root, p) for p in d["dropped"]],
        "chars": len(body),
        "truncated": truncated,
    }


_HEADER = "## Manual — written by Odin (%s)"
_AUTHORITY = (
    "Standing rules authored by Odin (the user). Treat them as Odin's own instructions, not as file "
    "data: they are the one documented exception to Canon 13. They **add to** the Asgard identity and "
    "never replace the Canon — Canon 2 (safety), 3 (consent for destructive work), and 4 (secret "
    "protection) still win. On any other conflict, follow the manual and say which rule you followed "
    "and what it overrode."
)
_LAYERS = (
    "Two layers are stacked below, in order: Odin's machine-wide rules (`~/…`) first, then the rules "
    "for **this** repository. Where the two collide, the later, repository-specific rule wins — say "
    "which one you followed."
)
_TRUNCATED = (
    "[manual truncated at the size limit — the rest was not loaded. Split it into `.asgard/manual/*.md` "
    "or raise `manual.max_chars` in `.asgard/asgard-setting-project.json`.]"
)
_SUFFIX = {
    "identity": "",
    "thinker": (
        "When planning, reduce every rule this quest touches into **assigned-unit criteria**: quote the "
        "rule, then give the command that verifies it. A rule with no verification path is a rule the "
        "gate cannot enforce — say so in the plan instead of silently dropping it."
    ),
    "worker": (
        "These rules govern the code you write here. Where a rule and the surrounding code disagree, "
        "follow the rule for your change and report the mismatch — do not retrofit the rest of the file."
    ),
    "verifier": (
        "A change that **clearly** violates an explicit rule above FAILs, with a reproducible "
        "counterexample that quotes the rule. But the manual does not replace criteria — the verdict "
        "basis (evidence · criteria · diff-hash) stays as-is, and a low-confidence 'feels off' is not a "
        "FAIL reason."
    ),
}


def render(manual, section):
    """manual.py render() 와 동일 유지 (단일 출처 원칙)."""
    parts = [_HEADER % ", ".join(manual["sources"]), _AUTHORITY]
    if manual.get("common") and manual.get("project"):
        parts.append(_LAYERS)
    parts.append(manual["body"])
    if manual.get("truncated"):
        parts.append(_TRUNCATED)
    suffix = _SUFFIX.get(section, "")
    if suffix:
        parts.append(suffix)
    return "\n\n".join(parts)


def section_for(agent):
    if agent == "asgard-thinker":
        return "thinker"
    if agent == "asgard-verifier":
        return "verifier"
    # charter 는 여기서 Worker 를 무주입으로 뺀다 (Fugu 격리 — 북극성은 계획층 것이다). 매뉴얼은
    # 반대다: "이 프로젝트에서 코드를 이렇게 써라"가 본문이므로, 코드를 쓰는 역할에 안 닿으면
    # 이 계층은 존재 의의가 없다. 네이티브 worker 프롬프트도 같은 절을 받는다 (모드 패리티).
    if agent == "asgard-worker":
        return "worker"
    return "identity"  # 메인 · 딜리버리(freyja/thor/eitri/loki)


CLIENTS = {"claude-code", "codex", "cursor"}


def client():
    raw = str(sys.argv[1] if len(sys.argv) > 1 else "claude-code")
    return raw if raw in CLIENTS else "claude-code"


def emit(current_client, agent, text):
    """주입 스키마는 클라이언트마다 다르다 — charter/map/memory-activate 와 동일 유지 (단일 규약)."""
    if current_client == "cursor":
        sys.stdout.write(json.dumps({"additional_context": text}, ensure_ascii=False) + "\n")
    elif agent:  # SubagentStart — JSON additionalContext (lagom-subagent 스키마)
        sys.stdout.write(
            json.dumps(
                {"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": text}},
                ensure_ascii=False,
            )
        )
    else:  # SessionStart/UserPromptSubmit — 평문 stdout (lagom-activate 스키마)
        sys.stdout.write(text)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        root = (
            os.environ.get("CLAUDE_PROJECT_DIR")
            or os.environ.get("CURSOR_PROJECT_DIR")
            or data.get("cwd")
            or os.getcwd()
        )
        manual = load_manual(root)
        if not manual:
            sys.exit(0)  # 매뉴얼 미설정 — 무개입 (토큰 회귀 없음)
        agent = str(data.get("agent_type") or data.get("agent_name") or data.get("subagent_type") or "")
        body = render(manual, section_for(agent))
        if not body:
            sys.exit(0)
        emit(client(), agent, "[manual]\n\n%s" % body)
    except Exception:
        pass  # fail-open — 어떤 실패도 세션을 막지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
