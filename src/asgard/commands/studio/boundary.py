"""자리 — 지금 어디를 보고 있고, 이 작업은 어디서 도는가.

창은 폴더가 아니라 사람의 것이다(`studio-app-first`). 그래서 "지금 자리"는 창의 상태고,
"이 작업의 자리"는 그 작업이 시작된 곳이다 — 둘은 다를 수 있고, 갈릴 때 무엇을 따르는지가
이 모듈의 전부다. 경로를 가두는 일(`_confine`)도 자리의 문제라 여기 있다.
"""

from __future__ import annotations

import os

from . import state

# ── 자리 · 기억 ────────────────────────────────────────────────────────────────


def current_root(default: str | None = None) -> str:
    """지금 보고 있는 작업 공간.

    호출자가 경계를 명시하면 그것이 정본이다 — 요청 핸들러는 늘 서버의 root를 넘기고,
    프로젝트 전환은 **그 서버의 root를 바꾼다**. 모듈 전역은 서버 없이 호출되는 경로
    (직접 dispatch, 테스트)를 위한 뒷받침일 뿐, 명시된 경계를 덮지 않는다."""
    if default:
        return os.path.abspath(default)
    with state._ROOT_LOCK:
        if state._CURRENT_ROOT:
            return state._CURRENT_ROOT
    return os.path.abspath(os.getcwd())


def resolve_start_root(explicit: str | None = None) -> str:
    """창이 처음 설 자리 — **언제나 개인 작업 공간**, 부른 쪽이 다른 자리를 지목하지 않는 한.

    여태는 cwd가 곧 프로젝트였고, 그다음은 최근에 열었던 프로젝트였다. 그래서 같은 앱이
    어디서 켜느냐에 따라 다른 자리에서 열렸다 — 저장소 안에서 켜면 그 저장소, 밖에서 켜면
    지난번 저장소. 창이 사람의 것이라면 그럴 수 없다: 클로드 코드도 챗지피티도 코덱스도,
    켜면 **자기 자리**에서 열리고 프로젝트는 그 안에서 고르는 값이다.

    그래서 사다리를 둘로 줄였다:
      1. 부른 쪽이 명시한 자리          `asgard open studio --root …` (저장소에서 바로 열고 싶을 때)
      2. ASGARD_STUDIO_ROOT           프로젝트 안에서 띄운 네이티브 창이 물려주는 값
      3. 개인 작업 공간                 나머지 전부 — 이게 스튜디오의 메인 루트다

    프로젝트를 잃는 것은 아니다. 등록부는 그대로고 창 안에서 고르면 그 자리로 옮겨 간다.
    다만 **고르는 것은 사람이지 cwd가 아니다.** 일감(`studio`)과 기획(`plan`)은 애초에
    이 경계 밖(워크스페이스)에 살아서, 어느 자리에서 열든 같은 목록이 뜬다."""
    from .. import studio_store

    for candidate in (explicit, os.environ.get("ASGARD_STUDIO_ROOT")):
        if candidate:
            target = os.path.abspath(os.path.expanduser(candidate))
            if os.path.isdir(target):
                return target
    return studio_store.ensure_scratch()


def workspace_label(root: str) -> str:
    """승인문과 계기 줄이 부르는 이름 — 개인 작업 공간은 경로가 아니라 이름으로 말한다."""
    from .. import studio_store

    if studio_store.is_scratch(root):
        return studio_store.SCRATCH_NAME
    return os.path.basename(os.path.abspath(root)) or root


def task_root(task: dict | None, fallback: str) -> str:
    """이 작업이 도는 자리. **작업에 적힌 경계가 창의 경계를 우선한다.**

    창이 다른 프로젝트를 보고 있어도, 어제 그 프로젝트에서 시작한 대화를 이어 가면 그 대화는
    자기 자리에서 돌아야 한다. 여태는 이어가기·승인이 전부 '지금 창이 보는 곳'에서 돌아서,
    프로젝트를 옮긴 뒤 옛 작업을 승인하면 **남의 저장소에서** 실행됐다."""
    root = str((task or {}).get("root") or "") or fallback
    target = os.path.abspath(os.path.expanduser(root))
    return target if os.path.isdir(target) else os.path.abspath(fallback)


def _known_root(params: dict[str, list[str]], fallback: str) -> tuple[str, str]:
    """질의가 가리키는 작업 공간 — `(root, error)`. 아는 자리만 연다.

    읽기 경로가 임의 경로를 받으면 그 순간 이 창은 파일 탐색기가 된다. 그래서 열 수 있는
    자리는 등록부 + 개인 작업 공간 + 지금 보는 곳으로 묶는다(경로 자체의 경계 검사는
    `_confine`이 그대로 한다 — 이건 그 위에 얹는 두 번째 문이다)."""
    from .. import studio_store

    wanted = (params.get("root") or [""])[0].strip()
    if not wanted:
        return os.path.abspath(fallback), ""
    target = os.path.abspath(os.path.expanduser(wanted))
    if target not in studio_store.known_roots(fallback):
        return "", "목록에 없는 작업 공간이에요 — 목록에 있는 자리만 열어요"
    return target, ""


def resolve_workspace(candidate: object, fallback: str) -> tuple[str, str]:
    """요청이 말한 작업 공간을 푼다 — `(root, error)`.

    창이 보내는 값만 믿지 않는다: 실재하는 디렉터리여야 하고, 개인 작업 공간이면 자리를
    만들어 준다. 값이 없으면 창이 지금 보는 곳이 그대로 답이다."""
    from .. import studio_store

    raw = str(candidate or "").strip()
    if not raw:
        return os.path.abspath(fallback), ""
    target = os.path.abspath(os.path.expanduser(raw))
    if studio_store.is_scratch(target):
        return studio_store.ensure_scratch(), ""
    if not os.path.isdir(target):
        return "", f"그 자리에 작업 공간이 없어요: {raw}"
    return target, ""


def _confine(root: str, rel: str) -> str | None:
    """프로젝트 경계 안의 실제 경로만 돌려준다.

    realpath로 비교하는 이유: `..`도, 밖을 가리키는 심링크도 문자열 검사로는 안 잡힌다.
    경계 밖이면 None — 창은 프로젝트를 보는 창이지 파일 시스템 탐색기가 아니다."""
    rel = str(rel or "").strip()
    if not rel or os.path.isabs(rel) or "\x00" in rel:
        return None
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(base, rel))
    if target != base and not target.startswith(base + os.sep):
        return None
    return target if os.path.isfile(target) else None
