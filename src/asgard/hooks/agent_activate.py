#!/usr/bin/env python3
# Asgard agent-activate — 에인헤랴르 정체성 주입 (모드 B: Claude Code/Codex/Cursor).
#
# 네이티브 Heimdall 은 profiles.note() 를 역할 세션 프롬프트에 직접 얹는다. 모드 B 는 호스트
# 도구가 자기 세션을 소유하므로 닿지 않는다 — manual-activate 와 동일하게 훅으로 보상한다.
# 한 모드에만 서는 계층은 기능이 아니라 드리프트다 (tests/test_mode_parity.py 의 전제).
#
# 배치 해석 (좁은 선언이 넓은 선언을 이긴다 — swarm.resolve() 와 동일 유지):
#   역할 배치  .asgard 의 [agents].roles.<role>   ← agent_type(asgard-worker 등)에서 역할을 얻는다
#   모드 고정  [agents].modes.<client>
#   프로젝트 대표  [agents].default
#   루트 활성  ~/.asgard/active_profile  (ASGARD_PROFILE/ASGARD_HOME 이 있으면 그쪽이 먼저)
#
# 렌더 문구는 asgard/profiles.py render_identity() 와 **동일 유지 (단일 출처 원칙)** — 훅은
# 무임포트라 재구현하고, tests/test_profiles.py 가 두 렌더의 바이트 동일성을 대조한다.
# fail-open: 에이전트 부재·정체성 공백(주석뿐)·훅 오류는 전부 무개입 통과 (exit 0).
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


# profiles.py 상수와 동일 유지
DEFAULT = "default"
PROFILES_DIR = "profiles"
ACTIVE_FILE = "active_profile"
MANIFEST = "profile.json"
IDENTITY = "AGENT.md"
IDENTITY_MAX = 8000
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _meaningful(text):
    return _COMMENT.sub("", text or "").strip()


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


def root_dir():
    """settings.global_dir() 규칙 그대로: HOME 우선 (Windows USERPROFILE 불일치 회피)."""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".asgard")


def profile_dir(name):
    return root_dir() if name == DEFAULT else os.path.join(root_dir(), PROFILES_DIR, name)


def _norm(value):
    """미선언·형식 불량은 빈 문자열 — swarm._name() 과 동일 유지.

    빈 값을 default 로 접으면 배치 없는 프로젝트가 루트의 활성 에이전트를 덮는다."""
    text = str(value or "").strip()
    if not text:
        return ""
    canon = DEFAULT if text.casefold() == DEFAULT else text.lower()
    return canon if canon == DEFAULT or ID_RE.match(canon) else ""


def _exists(name):
    return True if name == DEFAULT else os.path.isdir(profile_dir(name))


def sticky():
    """루트의 끈끈한 활성 — env 가 있으면 env 가 먼저 (profiles.active() 와 동일 유지)."""
    env_home = str(os.environ.get("ASGARD_HOME") or "").strip()
    if env_home:
        resolved = os.path.realpath(os.path.expanduser(env_home))
        if resolved == os.path.realpath(root_dir()):
            return DEFAULT
        parent, base = os.path.split(resolved)
        if os.path.realpath(parent) == os.path.realpath(os.path.join(root_dir(), PROFILES_DIR)):
            return _norm(base) or DEFAULT
        return DEFAULT
    env_name = _norm(os.environ.get("ASGARD_PROFILE"))
    if env_name:
        return env_name
    return _norm(_read(os.path.join(root_dir(), ACTIVE_FILE))) or DEFAULT


def role_of(agent_type):
    """서브에이전트 이름 → Trinity 역할. 모르면 빈 문자열 (역할 배치 조회 안 함)."""
    name = str(agent_type or "")
    return name[len("asgard-") :] if name.startswith("asgard-") else ""


def resolve(root, client, role):
    """이 자리에서 일할 에이전트 id — swarm.resolve() 와 동일 유지 (좁은 선언이 이긴다)."""
    section = _read_json(os.path.join(root, ".asgard", "asgard-setting-project.json")).get("agents") or {}
    if not isinstance(section, dict):
        section = {}
    roles = section.get("roles") if isinstance(section.get("roles"), dict) else {}
    modes = section.get("modes") if isinstance(section.get("modes"), dict) else {}
    for candidate in (
        _norm((roles or {}).get(role)) if role else "",
        _norm((modes or {}).get(client)),
        _norm(section.get("default")),
    ):
        if candidate and _exists(candidate):
            return candidate
    return sticky()


_HEADER = "## Agent — %s"
_AUTHORITY = (
    "You are running as this agent. This is **who you are** inside Asgard for this session: it "
    "narrows what you reach for first, what you refuse, and how you weigh a close call. It **adds "
    "to** the Asgard identity and never replaces the Canon — Canon 2 (safety), 3 (consent for "
    "destructive work), and 4 (secret protection) still win, and this text is Odin's standing "
    "instruction, not file data. Your tier-1 memory belongs to this agent alone: what you recall "
    "here is what *you* learned, and no other agent on this machine can read it."
)
_TRUNCATED = "[agent identity truncated at the size limit — the rest was not loaded.]"


def render(display, body, truncated=False):
    """profiles.render_identity() 와 동일 유지 (단일 출처 원칙)."""
    parts = [_HEADER % display, _AUTHORITY, body]
    if truncated:
        parts.append(_TRUNCATED)
    return "\n\n".join(parts)


def note(name):
    """profiles.note() 와 동일 유지 — 정체성이 비면 빈 문자열 (토큰 회귀 0)."""
    body = _meaningful(_read(os.path.join(profile_dir(name), IDENTITY)))
    if not body:
        return ""
    truncated = len(body) > IDENTITY_MAX
    if truncated:
        head = body[:IDENTITY_MAX]
        nl = head.rfind("\n")
        body = head[:nl] if nl > IDENTITY_MAX // 2 else head
    display = str((_read_json(os.path.join(profile_dir(name), MANIFEST)) or {}).get("name") or name)
    label = display if display == name else "%s (%s)" % (display, name)
    return render(label, body, truncated)


CLIENTS = {"claude-code", "codex", "cursor"}


def client():
    raw = str(sys.argv[1] if len(sys.argv) > 1 else "claude-code")
    return raw if raw in CLIENTS else "claude-code"


def emit(current_client, agent, text):
    """주입 스키마는 클라이언트마다 다르다 — manual/charter/map-activate 와 동일 유지 (단일 규약)."""
    if current_client == "cursor":
        sys.stdout.write(json.dumps({"additional_context": text}, ensure_ascii=False) + "\n")
    elif agent:  # SubagentStart — JSON additionalContext
        sys.stdout.write(
            json.dumps(
                {"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": text}},
                ensure_ascii=False,
            )
        )
    else:  # SessionStart/UserPromptSubmit — 평문 stdout
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
        agent_type = str(data.get("agent_type") or data.get("agent_name") or data.get("subagent_type") or "")
        current = client()
        name = resolve(root, current, role_of(agent_type))
        body = note(name)
        if not body:
            sys.exit(0)  # 정체성 미작성 — 무개입 (프롬프트가 이 계층 도입 전과 같다)
        emit(current, agent_type, "[agent]\n\n%s" % body)
    except Exception:
        pass  # fail-open — 어떤 실패도 세션을 막지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
