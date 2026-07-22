"""데이터 계층 — 세스룸니르(스튜디오) 홈·프로젝트·아티팩트 조회. 소켓 없이 단위 테스트 가능한 순수 함수.

정본 = ~/.asgard/studio/projects/<slug>/ 디렉터리(아티팩트 파일들 + project.json 메타).
대시보드·CLI 는 여기서만 읽는다. 생성 파이프라인(CUS-261)·내보내기(CUS-263)가 붙어도
이 계층은 "디스크의 프로젝트 사실"만 말한다 — 게이트/판정은 여기 없다.
"""

from __future__ import annotations

import json
import os
import re
import time
from importlib.resources import files as _files

STUDIO_ENV = "ASGARD_STUDIO_DIR"
PROJECTS = "projects"
META = "project.json"
SETTINGS = "settings.json"  # 스튜디오 설정 (engine 등) — 쓰기는 commands/studio.py 소유
ENGINES = {  # 생성 엔진 = CLI 연결 모드 — provider 이름으로 저장
    "claude-native": "Claude Code",
    "openai-native": "Codex",
}
DEFAULT_ENGINE = "claude-native"
BOOK = ".studio"  # 프로젝트 내 북키핑 (숨김 = 아티팩트 아님) — 쓰기는 commands/studio.py 소유
STATE = "state.json"
RUNS = "runs.jsonl"
RUN_LOG = "run.log"

_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


def studio_dir() -> str:
    return os.environ.get(STUDIO_ENV) or os.path.join(os.path.expanduser("~"), ".asgard", "studio")


def ensure_home(d: str | None = None) -> str:
    """스캐폴드만 — 기존 내용은 건드리지 않는다. 심링크 홈은 거부(경계 보전)."""
    d = d or studio_dir()
    if os.path.islink(d):
        raise ValueError("studio home must not be a symlink")
    os.makedirs(os.path.join(d, PROJECTS), exist_ok=True)
    return d


def slug_ok(slug: str) -> bool:
    return bool(_SLUG.fullmatch(slug))


def _read_meta(pdir: str) -> dict:
    try:
        with open(os.path.join(pdir, META), encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:  # 메타 없음/파손 — 디렉터리 사실만으로 fail-open
        return {}


def _artifact_names(pdir: str) -> list[str]:
    """프로젝트 안 아티팩트 상대 경로 목록 (project.json·숨김 파일 제외, 하위 디렉터리 포함)."""
    out: list[str] = []
    for root, dirs, files in os.walk(pdir):
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        for f in sorted(files):
            if f == META or f.startswith("."):
                continue
            out.append(os.path.relpath(os.path.join(root, f), pdir))
    return out


def read_settings(d: str | None = None) -> dict:
    """스튜디오 설정 — settings.json (없으면 기본값, fail-open)."""
    try:
        with open(os.path.join(d or studio_dir(), SETTINGS), encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def engine(d: str | None = None) -> str:
    """현재 생성 엔진 (provider 이름) — 허용 밖 값은 기본으로 강등."""
    e = str(read_settings(d).get("engine") or "")
    return e if e in ENGINES else DEFAULT_ENGINE


# ── 템플릿 라이브러리 (CUS-264) — 패키징 에셋, import 시 인덱스 1회 로드 ──────────────

_TPL_ROOT = _files("asgard") / "assets" / "studio_templates"


def _load_template_index() -> list[dict]:
    try:
        raw = json.loads((_TPL_ROOT / "index.json").read_text(encoding="utf-8"))
        return [x for x in raw if isinstance(x, dict) and x.get("name")]
    except Exception:
        return []


_TEMPLATES = _load_template_index()


def templates_data() -> dict:
    """갤러리 데이터 — 항목 + 카테고리 카운트."""
    counts: dict[str, int] = {}
    for t in _TEMPLATES:
        counts[t["category"]] = counts.get(t["category"], 0) + 1
    return {"total": len(_TEMPLATES), "categories": counts, "templates": _TEMPLATES}


def template_meta(name: str) -> dict | None:
    for t in _TEMPLATES:
        if t["name"] == name:
            return t
    return None


def template_file(name: str, rel: str | None = None) -> tuple[str, bytes] | None:
    """템플릿 파일 읽기 — 인덱스에 등재된 항목의 화이트리스트 파일만 (열거 밖 경로 없음 = 순회 불가)."""
    t = template_meta(name)
    if t is None:
        return None
    if t.get("kind") == "design":  # 디렉터리 = name, 파일은 두 개뿐
        allowed = {"example.html": f"{name}/example.html", "SKILL.md": f"{name}/SKILL.md"}
        full = allowed.get(rel or "example.html")
    else:  # media — 인덱스에 적힌 단일 파일 고정
        full = str(t.get("file") or "") or None
    if not full:
        return None
    try:
        node = _TPL_ROOT
        for part in full.split("/"):
            node = node / part
        return full, node.read_bytes()
    except Exception:
        return None


def read_state(pdir: str) -> dict:
    """현재/최종 실행 상태 — .studio/state.json (없으면 빈 dict, fail-open)."""
    try:
        with open(os.path.join(pdir, BOOK, STATE), encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def read_runs(pdir: str, limit: int = 20) -> list[dict]:
    """실행 이력 — .studio/runs.jsonl 최신 우선 limit 건."""
    rows: list[dict] = []
    try:
        with open(os.path.join(pdir, BOOK, RUNS), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows[-limit:][::-1]


def read_run_log(pdir: str, tail: int = 200) -> str:
    try:
        with open(os.path.join(pdir, BOOK, RUN_LOG), encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-tail:])
    except OSError:
        return ""


def projects_data(d: str | None = None) -> list[dict]:
    """프로젝트 목록 — 최근 갱신 우선. 각 항목은 메타 + 아티팩트 수(파일 사실)."""
    d = d or studio_dir()
    base = os.path.join(d, PROJECTS)
    rows: list[dict] = []
    if not os.path.isdir(base):
        return rows
    for slug in sorted(os.listdir(base)):
        pdir = os.path.join(base, slug)
        if not os.path.isdir(pdir) or not slug_ok(slug):
            continue
        meta = _read_meta(pdir)
        arts = _artifact_names(pdir)
        rows.append(
            {
                "slug": slug,
                "name": str(meta.get("name") or slug),
                "brief": str(meta.get("brief") or ""),
                "created": str(meta.get("created") or ""),
                "updated": str(meta.get("updated") or ""),
                "artifacts": len(arts),
                "status": str(read_state(pdir).get("status") or ""),
                "mtime": os.path.getmtime(pdir),
            }
        )
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows


def project_data(slug: str, d: str | None = None) -> dict:
    """한 프로젝트의 메타 + 아티팩트 상세 (상대 경로·크기·수정 시각)."""
    d = d or studio_dir()
    pdir = os.path.join(d, PROJECTS, slug)
    if not slug_ok(slug) or not os.path.isdir(pdir):
        return {"error": "not found", "slug": slug}
    meta = _read_meta(pdir)
    artifacts = []
    for rel in _artifact_names(pdir):
        p = os.path.join(pdir, rel)
        try:
            st = os.stat(p)
            artifacts.append({"path": rel, "size": st.st_size, "mtime": st.st_mtime})
        except OSError:
            continue
    return {
        "slug": slug,
        "name": str(meta.get("name") or slug),
        "brief": str(meta.get("brief") or ""),
        "created": str(meta.get("created") or ""),
        "updated": str(meta.get("updated") or ""),
        "artifacts": artifacts,
        "state": read_state(pdir),
        "runs": read_runs(pdir),
    }


def artifact_path(slug: str, rel: str, d: str | None = None) -> str | None:
    """아티팩트 상대 경로 → 절대 경로. realpath 경계 밖(순회·심링크 탈출)은 None."""
    d = d or studio_dir()
    if not slug_ok(slug) or not rel or rel.startswith(("/", "\\")):
        return None
    pdir = os.path.realpath(os.path.join(d, PROJECTS, slug))
    if not os.path.isdir(pdir):
        return None
    target = os.path.realpath(os.path.join(pdir, rel))
    if target != pdir and not target.startswith(pdir + os.sep):
        return None
    if not os.path.isfile(target) or os.path.basename(target) == META:
        return None
    return target


def snapshot_data(d: str | None = None) -> dict:
    """대시보드 1회 페치 스냅샷 — 실데이터만 (목업 패널 데이터 바인딩은 CUS-263 잔여)."""
    d = d or studio_dir()
    rows = projects_data(d)
    return {
        "meta": {
            "home": d,
            "projects": len(rows),
            "artifacts": sum(r["artifacts"] for r in rows),
            "generated": time.time(),
        },
        "projects": rows,
    }
