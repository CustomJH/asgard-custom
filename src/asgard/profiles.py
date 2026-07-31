"""에인헤랴르 (Einherjar) — 한 기계에 여러 에이전트를 세우는 계층.

발할라에 모인 전사들은 **하나의 군대이면서 각자 이름을 가진 개인**이다. 이 계층이 하는 일이
정확히 그것이다: 아스가르드를 여러 벌 설치하지 않고, 하나의 설치 위에 서로를 침범하지 않는
에이전트를 여럿 세운다. 그리고 프로젝트는 그 에이전트들을 **불러 쓰는** 자리다 (오딘 확정
26-07-29: "기본적으로는 루트로 구분하고, 프로젝트 하위에서는 설정된 에이전트를 활용").

두 개의 뿌리를 구분한다 — 이 구분이 이 파일의 전부다:

    root()   ~/.asgard                      기계 단위. 에이전트가 몇이든 하나다.
                                            credentials·auth·projects.json·sandboxes·
                                            completions·model-tiers 캐시·active_profile
    home()   ~/.asgard                      = 기본 에이전트 (마이그레이션 0 — 기존 설치가 곧 default)
             ~/.asgard/profiles/<id>        = 이름 붙은 에이전트의 사유 세계
                                            memory(1차 기억)·sessions·state·history·
                                            skills·asgard-setting-global.json·AGENT.md·profile.json

왜 credential을 안 가르는가: 에이전트마다 다시 로그인시키면 스웜을 못 쓴다. 자격은 기계의
것이고 기억은 에이전트의 것이다 — 이 경계가 흔들리면 "에이전트 추가"가 "설치 반복"이 된다.
대신 프로파일이 자기 `credentials.json`을 갖고 있으면 그게 이긴다 (별도 키를 쓰는 에이전트).

해석 사다리 (위가 이긴다):
    1. 컨텍스트 오버라이드   scoped() — 한 프로세스가 여러 에이전트를 돌릴 때 (스웜의 전제)
    2. ASGARD_HOME           경로 직접 지정 (docker·테스트·서브프로세스 전파)
    3. ASGARD_PROFILE        이름 지정 (CLI `--agent`가 이걸 세운다)
    4. ~/.asgard/active_profile   끈끈한 기본값 (`asgard agent use`)
    5. default               ~/.asgard 그대로

**서브프로세스는 반드시 ASGARD_HOME을 물려받아야 한다.** hermes가 같은 자리에서 크게 데였다
(이슈 18594: 활성 프로파일이 있는데 env를 안 넘겨 기본 프로파일에 남의 데이터를 썼다). 그래서
`subprocess_env()`를 제공하고, env 없이 기본으로 떨어지는 순간을 `fallback_warning()`이
말한다 — 조용한 교차 오염보다 시끄러운 경고가 낫다.

공유 지대: 메모리 서베이(arXiv 2603.07670)는 "전부 공유(사생활 유출) 아니면 완전 격리(지식
전이 불가) 둘뿐이고 그 사이가 비어 있다"고 지적한다. 여기서 고른 것은 **격리**이며,
**공유 통로는 이 패치에 없다** — 지금 상태는 그 서베이가 말한 두 극단 중
"완전 격리"쪽이고, 그건 의도된 선택이다: 에이전트 A가 올린 글을 B가 프롬프트로 읽는 통로는
곧 교차 프롬프트 인젝션 면이라(MAGPIE, arXiv 2510.15186) 예산·중복제거·출처 표기·오염 게이트를
같이 짓지 않으면 순손실이다. 검증 없이 반쯤 얹느니 없는 게 낫다. 다음 걸음은 "증류한 통찰만
명시 publish, 읽기는 전원" 형태의 공유 은행이며, 그때 필요한 것은 저장소가 아니라 **게이트**다.

fail-open: 이 모듈의 모든 읽기는 실패해도 예외를 안 던지고 default로 떨어진다. 프로파일
시스템의 버그가 아스가르드 시동을 막으면 안 된다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from contextvars import ContextVar, Token

# ── 이름 규약 ────────────────────────────────────────────────────────────────────

# 디렉터리 이름이 되므로 소문자·영숫자·하이픈·언더스코어만. 첫 글자는 영숫자 (숨김 파일 방지).
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")

DEFAULT = "default"
PROFILES_DIR = "profiles"
ACTIVE_FILE = "active_profile"
MANIFEST = "profile.json"
IDENTITY = "AGENT.md"

# 프로파일 홈 안에 만드는 사유 디렉터리. memory가 이 목록의 이유다 — 나머지는 그 곁이다.
HOME_DIRS = ("memory", "sessions", "state", "skills")

# 예약어 — CLI 하위 명령과 겹치면 `asgard agent use memory` 같은 문장이 어느 쪽인지 모호해진다.
RESERVED = frozenset(
    {
        DEFAULT,
        "agent",
        "agents",
        "profile",
        "profiles",
        "einherjar",
        "commons",
        "asgard",
        "auth",
        # `custom`은 active()가 "모르는 ASGARD_HOME"을 뜻할 때 쓰는 표지다. 같은 이름의
        # 에이전트를 만들면 둘을 구분할 수 없어 진짜 프로파일이 표지로 오인된다.
        "custom",
        "budget",
        "craft",
        "desktop",
        "doctor",
        "evolve",
        "health",
        "init",
        "k6",
        "manual",
        "map",
        "memory",
        "office",
        "plan",
        "plugins",
        "role",
        "setup",
        "skills",
        "start",
        "surface",
        "sync",
        "thor",
        "tools",
        "tutor",
        "uninstall",
        "update",
        "yggdrasil",
    }
)

_UNSET = object()
_SCOPE: ContextVar[object] = ContextVar("asgard_profile_scope", default=_UNSET)


# ── 뿌리 ─────────────────────────────────────────────────────────────────────────


def root() -> str:
    """기계 단위 아스가르드 뿌리 — 프로파일이 몇이든 하나.

    HOME을 명시 우선한다 (settings.global_dir과 **동일 유지** — Windows에서
    expanduser는 HOME을 안 보고 USERPROFILE만 본다)."""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".asgard")


def profiles_root() -> str:
    return os.path.join(root(), PROFILES_DIR)


CUSTOM = "custom"  # 이름 붙지 않은 홈 (컨테이너 볼륨 등) — 이름이 아니라 "지금 그 홈"을 뜻한다


def profile_dir(name: str) -> str:
    """이름 → 홈 경로. `default`는 뿌리 자신이다 (마이그레이션 0).

    `custom`은 이름이 아니라 **지금 이 프로세스의 홈**을 가리키는 표지다. 도커처럼
    `ASGARD_HOME=/opt/agent-data`를 통째로 준 경우가 여기다 — 그 홈은 `profiles/` 아래 있지
    않으므로 이름으로 되짚을 수 없고, 되짚으려 들면 `profiles/custom` 이라는 없는 자리를
    가리켜 정체성도 명세도 조용히 사라진다 (실측 26-07-29)."""
    canon = normalize(name)
    if canon == DEFAULT:
        return root()
    if canon == CUSTOM:
        # `home()`을 부르지 않는다 — scoped("custom") 이면 서로를 되불러 무한 재귀가 된다.
        return _env_home() or root()
    return os.path.join(profiles_root(), canon)


def _env_home() -> str:
    """ASGARD_HOME 원문 → 절대경로. 미설정이면 빈 문자열."""
    raw = str(os.environ.get("ASGARD_HOME") or "").strip()
    return os.path.abspath(os.path.expanduser(raw)) if raw else ""


# ── 활성 해석 ────────────────────────────────────────────────────────────────────


def normalize(name: str) -> str:
    """표시용 라벨을 온디스크 id로. 대시보드·CLI가 대문자를 넘겨도 같은 곳을 가리킨다."""
    text = str(name or "").strip()
    if not text:
        return DEFAULT
    return DEFAULT if text.casefold() == DEFAULT else text.lower()


def validate(name: str) -> str:
    """id 검증 — 통과하면 정규화된 id, 아니면 ValueError."""
    canon = normalize(name)
    if canon == DEFAULT:
        return canon
    if not ID_RE.match(canon):
        raise ValueError(f"이름 {name!r}은 쓸 수 없다 — [a-z0-9][a-z0-9_-]{{0,47}} 규약")
    if canon in RESERVED:
        raise ValueError(f"이름 {canon!r}은 예약어다 (CLI 하위 명령과 충돌) — 다른 이름을 골라라")
    return canon


def exists(name: str) -> bool:
    canon = normalize(name)
    if canon == DEFAULT:
        return True
    return os.path.isdir(profile_dir(canon))


def sticky() -> str:
    """`asgard agent use`로 고정된 이름 (env·스코프 무시 — 파일만 본다)."""
    try:
        with open(os.path.join(root(), ACTIVE_FILE), encoding="utf-8") as handle:
            return normalize(handle.read())
    except Exception:
        return DEFAULT


def active() -> str:
    """지금 이 프로세스가 어느 에이전트인가 — 해석 사다리 그대로.

    ASGARD_HOME이 프로파일 디렉터리를 안 가리키면 `custom`을 돌려준다 (거짓 이름을 지어내
    설정이 그 이름으로 저장되는 사고를 막는다)."""
    scoped_name = _SCOPE.get()
    if scoped_name is not _UNSET:
        return str(scoped_name)

    env_home = str(os.environ.get("ASGARD_HOME") or "").strip()
    if env_home:
        return _name_of(env_home)

    env_name = str(os.environ.get("ASGARD_PROFILE") or "").strip()
    if env_name:
        canon = normalize(env_name)
        return canon if canon == DEFAULT or ID_RE.match(canon) else DEFAULT

    return sticky()


def _name_of(path: str) -> str:
    """경로 → 프로파일 이름. 뿌리면 default, profiles/<id> 면 <id>, 그 외는 custom."""
    try:
        resolved = os.path.realpath(os.path.expanduser(path))
        if resolved == os.path.realpath(root()):
            return DEFAULT
        parent, base = os.path.split(resolved)
        if os.path.realpath(parent) == os.path.realpath(profiles_root()) and ID_RE.match(base):
            return base
    except Exception:
        pass
    return "custom"


def home() -> str:
    """활성 에이전트의 사유 홈 — 1차 기억·세션·설정이 사는 곳.

    이 함수가 이 파일의 유일한 공개 계약이다. `~/.asgard`를 직접 조립하는 코드는 전부
    여기(사유) 아니면 `root()`(기계) 중 하나로 가야 한다."""
    scoped_name = _SCOPE.get()
    if scoped_name is not _UNSET:
        return profile_dir(str(scoped_name))

    env_home = str(os.environ.get("ASGARD_HOME") or "").strip()
    if env_home:
        return os.path.abspath(os.path.expanduser(env_home))

    env_name = str(os.environ.get("ASGARD_PROFILE") or "").strip()
    if env_name:
        canon = normalize(env_name)
        if canon == DEFAULT or ID_RE.match(canon):
            return profile_dir(canon)

    return profile_dir(sticky())


# ── 스코프 (한 프로세스, 여러 에이전트) ──────────────────────────────────────────────


def push(name: str | None) -> Token:
    """컨텍스트 로컬 오버라이드. os.environ을 안 건드린다 — 그건 전 스레드 공유라
    스웜에서 서로의 홈을 덮어쓴다 (hermes가 같은 이유로 contextvar를 쓴다)."""
    return _SCOPE.set(_UNSET if name is None else normalize(name))


def pop(token: Token) -> None:
    _SCOPE.reset(token)


class scoped:
    """`with scoped("loki-qa"): ...` — 블록 안에서만 그 에이전트."""

    def __init__(self, name: str | None) -> None:
        self._name = name
        self._token: Token | None = None

    def __enter__(self) -> str:
        self._token = push(self._name)
        return home()

    def __exit__(self, *_exc: object) -> None:
        if self._token is not None:
            pop(self._token)


def env_overlay(name: str | None = None) -> dict[str, str]:
    """활성 에이전트를 가리키는 환경변수 **오버레이** (전체 환경이 아니라 덧입힐 두 키).

    SDK처럼 "os.environ 상속 + 오버레이" 형태로 자식을 띄우는 자리에서 쓴다.
    `custom`(모르는 ASGARD_HOME)일 때 ASGARD_PROFILE을 빈 문자열로 덮는 이유: 오버레이는
    상속된 값을 못 지운다 — 남겨 두면 자식이 낡은 이름으로 다른 홈을 고른다."""
    target = normalize(name) if name else active()
    if target == "custom":
        return {"ASGARD_HOME": home(), "ASGARD_PROFILE": ""}
    return {"ASGARD_HOME": profile_dir(target), "ASGARD_PROFILE": target}


def subprocess_env(env: dict[str, str] | None = None, name: str | None = None) -> dict[str, str]:
    """서브프로세스에 활성 에이전트를 **명시 전파**한 환경.

    hermes 이슈 18594의 교훈: 활성 프로파일이 있는데 env를 안 넘기면 자식은 기본 프로파일에
    쓴다. 조용한 교차 오염이라 며칠 뒤에야 발견된다. 자식을 띄우는 모든 자리는 이걸 쓴다."""
    out = dict(os.environ if env is None else env)
    overlay = env_overlay(name)
    out.update(overlay)
    if not overlay["ASGARD_PROFILE"]:
        out.pop("ASGARD_PROFILE", None)  # 완전한 환경을 만들 때는 아예 빼는 편이 정확하다
    return out


def fallback_warning() -> str:
    """끈끈한 활성 프로파일이 있는데 env가 비어 기본으로 떨어졌으면 그 사실을 문장으로.

    빈 문자열 = 정상. 호출측(doctor·훅)이 이 문장을 그대로 보여준다."""
    if os.environ.get("ASGARD_HOME") or os.environ.get("ASGARD_PROFILE"):
        return ""
    if _SCOPE.get() is not _UNSET:
        return ""
    name = sticky()
    if name == DEFAULT:
        return ""
    return (
        f"활성 에이전트는 {name!r} 인데 ASGARD_HOME/ASGARD_PROFILE이 비어 있다 — "
        f"이 프로세스는 기본 에이전트({root()})에 쓴다. 부모가 profiles.subprocess_env()로 "
        f"환경을 넘겨야 한다."
    )


def set_active(name: str) -> str:
    """끈끈한 기본 에이전트 고정. default는 파일 삭제로 표현한다 (없음 = 기본)."""
    canon = validate(name)
    if canon != DEFAULT and not exists(canon):
        raise FileNotFoundError(f"에이전트 {canon!r} 없음 — `asgard agent create {canon}`로 먼저 만들어라")
    path = os.path.join(root(), ACTIVE_FILE)
    os.makedirs(root(), exist_ok=True)
    if canon == DEFAULT:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    else:
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(canon + "\n")
        os.replace(tmp, path)
    return canon


# ── 명세 (profile.json) ──────────────────────────────────────────────────────────


def manifest(name: str) -> dict:
    """에이전트 명세 — 없으면 이름만 든 최소 뷰 (fail-open).

    `description`은 장식이 아니다: 스웜이 일을 어디로 보낼지 고를 때 읽는 유일한 문장이다
    (hermes가 kanban 분해기에 같은 값을 물린다). 그래서 create가 비워두지 않는다."""
    canon = normalize(name)
    path = os.path.join(profile_dir(canon), MANIFEST)
    data: dict = {}
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            data = loaded
    except Exception:
        data = {}
    data.setdefault("id", canon)
    data.setdefault("name", data.get("id") or canon)
    data.setdefault("based_on", None)
    data.setdefault("description", "")
    data.setdefault("capabilities", [])
    return data


def write_manifest(profile_id: str, /, **fields: object) -> str:
    """명세 갱신 — 준 키만 덮어쓴다 (부분 수정이 나머지를 지우면 안 된다).

    첫 인자는 위치 전용이다: 명세에 `name`(표시 이름) 키가 있어서, 키워드로 받으면
    `write_manifest(id, name="로키")`가 "인자 중복"으로 터진다."""
    canon = normalize(profile_id)
    d = profile_dir(canon)
    os.makedirs(d, exist_ok=True)
    data = manifest(canon)
    for key, value in fields.items():
        if value is not None:
            data[key] = value
    data["id"] = canon
    data["revision"] = int(data.get("revision") or 0) + 1
    path = os.path.join(d, MANIFEST)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def identity(name: str) -> str:
    """에이전트 정체성 문서 (AGENT.md) 본문 — 없으면 빈 문자열."""
    try:
        with open(os.path.join(profile_dir(normalize(name)), IDENTITY), encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return ""


# ── 정체성 주입 ──────────────────────────────────────────────────────────────────
#
# 렌더 문구는 hooks/agent_activate.py와 **동일 유지 (단일 출처 원칙)** — 훅은 임포트를 못 하므로
# 재구현하고, tests/test_profiles.py가 두 렌더가 같은 문자열을 내는지 대조한다.

IDENTITY_MAX = 8000  # 상한 (~2k 토큰). 정체성은 캐시 프리픽스라 1회 비용이지만 무한은 아니다.

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


def render_identity(display: str, body: str, truncated: bool = False) -> str:
    """주입 본문 — hooks/agent_activate.py `render()`와 바이트 동일해야 한다."""
    parts = [_HEADER % display, _AUTHORITY, body]
    if truncated:
        parts.append(_TRUNCATED)
    return "\n\n".join(parts)


def note(name: str | None = None) -> str:
    """프롬프트 주입분 — 정체성이 비었거나(주석뿐) 기본 에이전트면 **빈 문자열**.

    기본 에이전트에서 빈 문자열인 이유: 프로파일을 안 쓰는 설치의 프롬프트가 이 계층 도입 전과
    바이트 단위로 같아야 한다 (토큰 회귀 0). 기본 에이전트도 AGENT.md를 적으면 실린다 —
    "안 적었으면 침묵"이 규칙이지 "기본은 침묵"이 규칙이 아니다."""
    canon = normalize(name) if name else active()
    body = _meaningful(identity(canon))
    if not body:
        return ""
    truncated = len(body) > IDENTITY_MAX
    if truncated:
        head = body[:IDENTITY_MAX]
        nl = head.rfind("\n")
        body = head[:nl] if nl > IDENTITY_MAX // 2 else head
    return "\n\n" + render_identity(label_for(canon), body, truncated)


def label_for(name: str) -> str:
    """헤더에 쓸 이름 — hooks/agent_activate.py `label_for()`와 **동일 유지 (단일 출처 원칙)**.

    `custom`(이름 없는 홈 — 컨테이너 볼륨 등)은 id가 없으므로 명세의 표시 이름을 쓰고,
    그것도 없으면 홈 디렉터리 이름을 쓴다. "custom" 이라고만 적으면 컨테이너 여럿을 띄웠을 때
    로그에서 누가 누군지 구분이 안 된다."""
    canon = normalize(name)
    meta_name = str(manifest(canon).get("name") or "")
    if canon == CUSTOM:
        # manifest()는 이름이 없으면 id를 채워 넣는다 — 그 기본값은 이름이 아니다.
        if meta_name and meta_name != CUSTOM:
            return meta_name
        return os.path.basename(profile_dir(canon).rstrip(os.sep)) or CUSTOM
    display = meta_name or canon
    return display if display == canon else f"{display} ({canon})"


# ── 내장 명부 (아스가르드 고유 에이전트) ──────────────────────────────────────────────


def builtin_roster() -> dict[str, dict]:
    """`templates/roles/*.md`가 곧 내장 명부다 — 등록부가 따로 없다.

    반환 = {id: {name, description, delivery, source}}. id는 `asgard-` 접두를 뗀 짧은 이름
    (freyja·thor·mimir·loki·…). 사용자가 이 중 하나를 대표 에이전트로 고르면 create가
    그 정체성을 씨앗으로 프로파일을 짓는다."""
    out: dict[str, dict] = {}
    try:
        from .templates.roles import ROLE_AGENTS
    except Exception:
        return out
    for fname, body in ROLE_AGENTS:
        parts = body.split("---", 2)
        if len(parts) < 3:
            continue
        meta = {
            key.strip(): value.strip()
            for line in parts[1].splitlines()
            if ":" in line
            for key, value in (line.split(":", 1),)
        }
        full = meta.get("name") or fname.removesuffix(".md")
        short = full.removeprefix("asgard-")
        if not ID_RE.match(short):
            continue
        out[short] = {
            "name": full,
            "description": meta.get("description", ""),
            "delivery": meta.get("delivery"),
            "source": fname,
        }
    return out


def builtin_identity(short: str) -> str:
    """내장 에이전트의 정체성 본문 (frontmatter 제외) — 없으면 빈 문자열."""
    roster = builtin_roster()
    entry = roster.get(normalize(short))
    if not entry:
        return ""
    try:
        from .templates.roles import ROLE_AGENTS

        body = dict(ROLE_AGENTS)[str(entry["source"])]
        return body.split("---", 2)[2].lstrip()
    except Exception:
        return ""


# ── CRUD ────────────────────────────────────────────────────────────────────────


def _seed_home(d: str) -> None:
    os.makedirs(d, exist_ok=True)
    for sub in HOME_DIRS:
        os.makedirs(os.path.join(d, sub), exist_ok=True)


def create(
    name: str,
    *,
    based_on: str | None = None,
    description: str | None = None,
    capabilities: list[str] | None = None,
    clone_from: str | None = None,
    display: str | None = None,
) -> str:
    """에이전트 하나를 짓는다. 반환 = 홈 경로.

    based_on = 내장 명부의 짧은 이름 (freyja·loki·…). 주면 그 정체성을 AGENT.md 씨앗으로
    깔고 설명을 물려받는다 — "아스가르드 고유 에이전트를 대표로 세운다"가 이 경로다.
    clone_from = 기존 에이전트의 설정·정체성을 복사 (기억은 **안** 복사한다 — 남의 기억을
    물려받은 에이전트는 자기 일지의 주어가 누구인지 모른다)."""
    canon = validate(name)
    if canon == DEFAULT:
        raise ValueError("default는 내장 에이전트다 (~/.asgard) — 새로 만들 수 없다")
    d = profile_dir(canon)
    if os.path.exists(d):
        raise FileExistsError(f"에이전트 {canon!r} 이미 있음: {d}")

    roster = builtin_roster()
    seed = normalize(based_on) if based_on else ""
    if seed and seed not in roster:
        raise ValueError(f"내장 에이전트 {seed!r} 없음 — {'/'.join(sorted(roster)) or '(명부 비어 있음)'}")

    _seed_home(d)

    if clone_from:
        src_name = validate(clone_from)
        src = profile_dir(src_name)
        if not os.path.isdir(src):
            raise FileNotFoundError(f"복제 원본 {src_name!r} 없음: {src}")
        for fname in ("asgard-setting-global.json", IDENTITY):
            s = os.path.join(src, fname)
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(d, fname))
        src_skills = os.path.join(src, "skills")
        if os.path.isdir(src_skills):
            shutil.copytree(src_skills, os.path.join(d, "skills"), dirs_exist_ok=True)

    body = ""
    if seed:
        body = builtin_identity(seed)
    if body and not os.path.exists(os.path.join(d, IDENTITY)):
        header = f"<!-- seeded from the built-in Asgard agent `{roster[seed]['name']}` — edit freely; sync never touches this file -->\n\n"
        with open(os.path.join(d, IDENTITY), "w", encoding="utf-8") as handle:
            handle.write(header + body)
    elif not os.path.exists(os.path.join(d, IDENTITY)):
        with open(os.path.join(d, IDENTITY), "w", encoding="utf-8") as handle:
            handle.write(_BLANK_IDENTITY % (display or canon))

    desc = (description or "").strip()
    if not desc and seed:
        desc = str(roster[seed].get("description") or "")
    write_manifest(
        canon,
        name=display or canon,
        based_on=seed or None,
        description=desc,
        capabilities=list(capabilities or []),
        created=int(time.time()),
    )
    return d


# 안내 템플릿은 **주석뿐**이어야 한다. 제목 한 줄이라도 주석 밖에 있으면 `_meaningful`이 그걸
# 알맹이로 읽어, 아무것도 안 쓴 에이전트의 프롬프트에 빈 헤더가 실린다 (manual.py와 같은 규율 —
# 안내문을 배송해도 토큰 회귀 0 이라는 약속이 여기서 깨진다). 제목도 주석 안에 둔다.
_BLANK_IDENTITY = """<!--
%s — 이 에이전트의 정체성 문서

이 파일이 이 에이전트의 정체성이다. 세션이 시작될 때 아스가르드 정체성 **위에** 얹힌다
(.asgard/MANUAL.md와 같은 층위이되, 이쪽은 프로젝트가 아니라 에이전트에 붙는다).

아래 세 가지만 적어도 충분하다:
  · 무엇을 하는 에이전트인가 (한 문장)
  · 무엇을 특히 잘해야 하는가 / 무엇은 하지 않는가
  · 판단이 갈릴 때 어느 쪽으로 기우는가

비워두면 이 계층은 침묵한다 — 주석뿐인 파일은 없는 것으로 친다.
-->
"""


def delete(name: str) -> str:
    """에이전트 삭제. 활성이었으면 끈끈한 포인터를 default로 되돌린다 (죽은 이름을 가리키는
    active_profile은 모든 후속 프로세스를 custom으로 떨어뜨린다)."""
    canon = validate(name)
    if canon == DEFAULT:
        raise ValueError("기본 에이전트는 지울 수 없다 (~/.asgard 자체다)")
    d = profile_dir(canon)
    if not os.path.isdir(d):
        raise FileNotFoundError(f"에이전트 {canon!r} 없음")
    shutil.rmtree(d)
    if sticky() == canon:
        set_active(DEFAULT)
    return d


def listing() -> list[dict]:
    """전 에이전트 요약 — default가 항상 맨 앞. 이름 붙은 것은 사전순.

    각 항목: {id, name, description, based_on, path, active, memory_pages, has_identity}."""
    now_active = active()
    rows: list[dict] = []

    def _row(canon: str) -> dict:
        d = profile_dir(canon)
        m = manifest(canon)
        return {
            "id": canon,
            "name": m.get("name") or canon,
            "description": m.get("description") or "",
            "based_on": m.get("based_on"),
            "capabilities": m.get("capabilities") or [],
            "path": d,
            "active": canon == now_active,
            "memory_pages": _page_count(d),
            "has_identity": bool(_meaningful(identity(canon))),
        }

    rows.append(_row(DEFAULT))
    try:
        names = sorted(
            entry
            for entry in os.listdir(profiles_root())
            if ID_RE.match(entry) and os.path.isdir(os.path.join(profiles_root(), entry))
        )
    except OSError:
        names = []
    rows.extend(_row(n) for n in names)
    return rows


_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _meaningful(text: str) -> str:
    """주석을 걷어낸 알맹이 — manual.py `_meaningful`과 같은 규율 (주석뿐이면 없는 것)."""
    return _COMMENT.sub("", text or "").strip()


def _page_count(d: str) -> int:
    try:
        return sum(1 for n in os.listdir(os.path.join(d, "memory", "pages")) if n.endswith(".md"))
    except OSError:
        return 0


def ensure(name: str) -> str:
    """홈이 없으면 짓고 경로를 돌려준다 — 내장 명부의 이름이면 그 정체성으로 씨를 뿌린다.

    `asgard agent use freyja`가 이걸 부른다: 내장 에이전트를 고르는 행위가 곧 그 에이전트의
    1차 기억을 여는 행위다 (미리 만들어 둘 필요 없음)."""
    canon = validate(name)
    if canon == DEFAULT:
        _seed_home(root())
        return root()
    d = profile_dir(canon)
    if os.path.isdir(d):
        return d
    if canon in builtin_roster():
        return create(canon, based_on=canon)
    return create(canon)
