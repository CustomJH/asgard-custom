"""projects registry — ~/.asgard/projects.json. setup 이 스캐폴딩한 프로젝트를 기록해
`asgard sync` 가 "asgard 가 세팅된 모든 디렉토리" 를 찾을 수 있게 한다 (파일시스템 스캔 없음).

엔트리 = {root, cc, cursor, codex, updated}. root 로 dedupe (재-init 은 프로필 갱신).
이 파일은 로컬 머신 상태다 — credentials.json 과 같은 계층, 프로젝트 repo 에는 절대 안 들어간다."""

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


def record(root: str, cc: bool, cursor: bool, codex: bool) -> None:
    """프로젝트 upsert — root 정규화(realpath) 후 기존 엔트리 교체. 실패는 조용히 무시
    (레지스트리는 편의 기능 — setup 자체를 깨지 않는다)."""
    root = os.path.realpath(root)
    entry = {"root": root, "cc": cc, "cursor": cursor, "codex": codex, "updated": int(time.time())}
    try:
        projects = [p for p in load() if os.path.realpath(str(p["root"])) != root]
        projects.append(entry)
        os.makedirs(os.path.dirname(_path()), exist_ok=True)
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"projects": projects}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _path())
    except Exception:
        pass


def forget(root: str) -> None:
    """엔트리 제거 (sync 가 사라진 루트를 정리할 때)."""
    root = os.path.realpath(root)
    try:
        projects = [p for p in load() if os.path.realpath(str(p["root"])) != root]
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"projects": projects}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _path())
    except Exception:
        pass
