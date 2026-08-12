"""projects registry — ~/.asgard/projects.json. setup이 스캐폴딩한 프로젝트를 기록해
`asgard sync`가 "asgard가 세팅된 모든 디렉토리"를 찾을 수 있게 한다 (파일시스템 스캔 없음).

엔트리 = {root, cc, cursor, codex, updated}. root로 dedupe (재-init은 프로필 갱신).
엔트리가 빠지는 길은 둘이다 — `forget`, 그리고 쓰기마다 도는 `alive` 정리.
이 파일은 로컬 머신 상태다 — credentials.json과 같은 계층, 프로젝트 repo 에는 절대 안 들어간다."""

import json
import os
import time

_FILE = "projects.json"


def _path() -> str:
    return os.path.join(os.path.expanduser("~"), ".asgard", _FILE)


def load() -> list[dict]:
    """등록된 프로젝트 목록 (없거나 파손 → 빈 목록, fail-open)."""
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        projects = data.get("projects")
        return [p for p in projects if isinstance(p, dict) and p.get("root")] if isinstance(projects, list) else []
    except Exception:
        return []


def alive(entry: dict) -> bool:
    """이 엔트리를 계속 들고 있을 것인가.

    루트 폴더가 있으면 당연히 유지한다. 없을 때가 갈리는데, 부모 디렉터리까지 같이 없으면
    유지한다 — 외장 디스크나 네트워크 볼륨이 빠져 있는 동안 `/Volumes/ext/proj` 는 `proj` 도
    `ext` 도 안 보이고, 그때 지우면 디스크를 다시 꽂아도 그 프로젝트는 목록에서 사라진 채다.
    부모는 있는데 루트만 없으면 사람이 그 폴더를 지운 것이므로 뺀다."""
    root = str(entry.get("root") or "")
    return os.path.isdir(root) or not os.path.isdir(os.path.dirname(root))


def _others(root: str) -> list[dict]:
    """`root` 를 뺀 나머지 등록 중 살아 있는 것만 — 쓰기마다 도는 정리.

    이 정리가 없으면 죽은 엔트리는 사람이 `asgard sync` 를 칠 때까지 쌓인다. 시험이 임시
    폴더에서 실물 `asgard init` 을 돌리면 그 경로가 여기 적히고 폴더는 시험 끝에 지워지므로,
    sync 한 번에 서른 줄씩 "폴더가 없어져서 뺄게요" 가 뜨던 자리다 (26-08-12).

    정리 대상은 **다른** 등록뿐이다. 지금 쓰는 root 를 같이 판정하면 `record` 가 아직 안 만든
    폴더를 등록할 때 그 등록이 같은 호출 안에서 사라진다 — 부른 쪽에는 성공으로 보이고."""
    return [p for p in load() if alive(p) and os.path.realpath(str(p["root"])) != root]


def _save(projects: list[dict]) -> None:
    """레지스트리 파일 교체 — 임시 파일에 쓰고 원자적으로 바꾼다."""
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"projects": projects}, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _path())


def record(root: str, cc: bool, cursor: bool, codex: bool) -> None:
    """프로젝트 upsert — root 정규화(realpath) 후 기존 엔트리 교체. 실패는 조용히 무시
    (레지스트리는 편의 기능 — setup 자체를 깨지 않는다)."""
    root = os.path.realpath(root)
    entry = {"root": root, "cc": cc, "cursor": cursor, "codex": codex, "updated": int(time.time())}
    try:
        _save(_others(root) + [entry])
    except Exception:
        pass


def forget(root: str) -> None:
    """엔트리 제거 (sync가 사라진 루트를 정리할 때)."""
    root = os.path.realpath(root)
    try:
        _save(_others(root))
    except Exception:
        pass
