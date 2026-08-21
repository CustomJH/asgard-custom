"""doctor — 지도와 매뉴얼 검사. 드리프트·영역 지도 문법·오딘이 쓴 규칙 파일·실행 표면."""

import os
from pathlib import Path

from ... import io_files


def _map_drift_detail(managed) -> str:
    """맵 드리프트 사유 — 항목 집합이 같고 본문만 달라지면 `+0 -0` 이라는 빈 경고가 떴다
    (26-07-26 실측). 무엇이 다른지 못 말하는 경고는 잡음이므로 사실을 그대로 쓴다."""
    if managed.added or managed.removed:
        return f"managed drift: +{len(managed.added)} -{len(managed.removed)}"
    return "managed projection is stale — same entries, changed detail"


def _manual_area_issues(root: str, mdir: str) -> tuple[list[str], list[str], int, list[str]]:
    """수동 영역 파일의 (유령, 위험, 항목 수, 영역 목록).

    관리 파일은 수동 영역 문법의 대상이 아니다 — map_context.validate_area_maps와 같은 제외
    목록을 써야 한다. GRAPH.md가 빠져 있어 그래프의 API 라우트 노드가 절대경로 파일 참조로
    읽혔고, 생성 파일에 대해 영원히 지워지지 않는 unsafe가 떴다. 짝 저장소 지도(`PEER-*.md`)도
    같은 자리다 — 그 행은 뿌리 밖을 가리키는 것이 정상이라, 안 빼면 선언을 한 순간 진단이 빨갛게
    고정된다.
    """
    import re as _re

    from ...code_map import PEER_MAP_PREFIX

    entry_pat = _re.compile(r"^- `([^`]+)`", _re.M)
    ghosts: list[str] = []
    unsafe: list[str] = []
    entries = 0
    areas = sorted(
        f
        for f in os.listdir(mdir)
        if f.endswith(".md") and f not in ("GRAPH.md", "INDEX.md", "PROJECT.md") and not f.startswith(PEER_MAP_PREFIX)
    )
    for fname in areas:
        area_path = Path(mdir, fname)
        if _is_link(area_path):
            unsafe.append(f"{fname}: symlink/junction")
            continue
        try:
            body = area_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for match in entry_pat.finditer(body):
            entries += 1
            kind = _entry_kind(root, match.group(1))
            if kind == "unsafe":
                unsafe.append(f"{fname}: {match.group(1)}")
            elif kind == "ghost":
                ghosts.append(f"{fname}: {match.group(1)}")
    _add_area_validation(root, ghosts, unsafe)
    return (ghosts, unsafe, entries, areas)


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _entry_kind(root: str, entry_text: str) -> str:
    """항목 하나의 판정 — "ok" | "ghost" | "unsafe". 허용된 뿌리 밖을 가리키면 존재해도 위험이다.

    허용된 뿌리는 이 저장소와 선언된 짝 저장소다. 주입면의 `map_context._safe_path` 와 같은 집합을
    봐야 한다 — 한쪽만 짝을 알면, 사람이 그 저장소를 적은 영역 지도 한 줄이 주입에는 들어가고
    진단에는 위험으로 뜬다."""
    from ...map_context import _peer_bases

    entry = entry_text.rstrip("/")
    if os.path.isabs(entry):
        return "unsafe"
    candidate = Path(root, entry)
    resolved = candidate.resolve(strict=False)
    if not any(resolved == base or resolved.is_relative_to(base) for base in _peer_bases(Path(root))):
        return "unsafe"
    return "ghost" if not candidate.exists() else "ok"


def _add_area_validation(root: str, ghosts: list[str], unsafe: list[str]) -> None:
    from ...map_context import validate_area_maps

    _, area_issues = validate_area_maps(root)
    for issue in area_issues:
        detail = f"{Path(issue.source).name}: {issue.reason}"
        if detail not in unsafe and not any(detail.startswith(item.split(":", 1)[0] + ":") for item in ghosts):
            unsafe.append(detail)


def _map_status_detail(managed, areas: list[str], entries: int, ghosts: list[str], unsafe: list[str]) -> str:
    if unsafe:
        return "unsafe: " + ", ".join(unsafe[:5])
    if ghosts:
        return "ghost: " + ", ".join(ghosts[:5]) + (f" (+{len(ghosts) - 5})" if len(ghosts) > 5 else "")
    if managed.ok:
        return f"{len(areas)} manual area(s) · {entries} entries · managed current"
    if not managed.owned:
        return "PROJECT.md ownership marker missing"
    if not managed.index_current:
        return "INDEX.md drift"
    if not managed.trackable:
        return "managed map is git-ignored — not shareable"
    if managed.peer_drift:
        return "declared work root moved on: " + ", ".join(managed.peer_drift[:5])
    return _map_drift_detail(managed)


def _codebase_map_check(root: str) -> list[dict]:
    """유령 엔트리(디스크에 없는 경로) 탐지 — 지도 문법 3: 실재만 기재.

    영역 파일이 아직 없는 것은 정상이다 (fog-of-war). 없는 것을 결함이라 부르면 지도를 처음
    그리는 프로젝트가 영원히 빨간불이 된다.
    """
    from ...code_map import MapError, check_map

    mdir = os.path.join(root, ".asgard", "map")
    unsafe_component = next((p for p in (Path(root, ".asgard"), Path(mdir)) if _is_link(p)), None)
    if unsafe_component is not None:
        detail = f"unsafe managed map path: symlink/junction: {unsafe_component}"
        return [_map_row(False, detail, "symlink/junction 제거 후 asgard map update 실행")]
    if not os.path.isdir(mdir):
        return [_map_row(False, "missing .asgard/map/", "asgard init --force 로 지도 시드 생성")]
    ghosts, unsafe, entries, areas = _manual_area_issues(root, mdir)
    try:
        managed = check_map(root)
    except MapError as exc:
        detail = f"unsafe managed map path: {exc}"
        return [_map_row(False, detail, "symlink/junction 제거 후 asgard map update 실행")]
    # GRAPH.md 는 `map update` 가 안 건드린다. 그래프 드리프트를 이 행이 안 보던 판은 낡은
    # 노드·간선을 초록으로 통과시켰고, `map impact`·`map trace` 가 거기서 답을 낸다.
    graph_drift = _graph_drift(root)
    detail = _map_status_detail(managed, areas, entries, ghosts, unsafe)
    if graph_drift:
        detail = f"{detail} · GRAPH.md drift"
    return [
        _map_row(
            not ghosts and not unsafe and managed.ok and not graph_drift,
            detail,
            "asgard map scan (관계 그래프) · asgard map update (관리 지도); 수동 영역의 유령 경로는 제거",
        )
    ]


def _graph_drift(root: str) -> bool:
    """관계 그래프가 코드와 어긋났는가 — 다시 그리지 않고 묻기만 한다.

    아직 안 그린 그래프는 드리프트가 아니다. GRAPH.md 가 없는 것을 결함이라 부르면 지도를
    처음 그리는 저장소가 영영 빨간불이 된다 (영역 지도의 fog-of-war 와 같은 독법).
    `scan_graph` 의 쓰기는 전부 `dry_run` 뒤에 있어 이 호출은 아무것도 안 남긴다."""
    from ...map_graph import scan_graph

    if not os.path.isfile(os.path.join(root, ".asgard", "map", "GRAPH.md")):
        return False
    try:
        return bool(scan_graph(root, dry_run=True).changed)
    except Exception:
        return False


def _map_row(ok: bool, detail: str, fix: str) -> dict:
    return {"name": "codebase map", "ok": ok, "detail": detail, "fix": fix}


def _run_surface_check(root: str) -> dict | None:
    """실행 표면 — 이 저장소가 Justfile 을 쓰기로 했다면, 그것이 지금 매니페스트와 맞는가.

    **안 들인 저장소에는 행 자체가 없다.** 실행 표면은 `asgard just init` 으로 저장소가 고르는
    것이라, 안 고른 것을 진단에 올리면 초록이든 노랑이든 "들여야 할 것을 안 들였다"로 읽힌다 —
    그 판단은 도구가 아니라 오딘이 한다.

    들인 저장소에서는 두 가지가 갈린다. 러너가 PATH 에 없는 것과 관리 구역이 낡은 것은 처방이
    다르다(`asgard just install` 대 `asgard just sync`) — 한 줄에 실어도 무엇을 쳐야 하는지가
    갈리면 안 되므로 둘을 이어 적는다."""
    try:
        from ... import justfile

        path = justfile.find_justfile(root)
        if path is None:
            return None  # 이 저장소는 실행 표면을 안 쓴다 — 진단할 것이 없다
        parts = list(justfile.check(root))
        version = justfile.just_version()
        if not version:
            parts.append("just is not on PATH")
        recipes = len(justfile.parse_recipes(io_files.read_text(path)))
        detail = " · ".join(parts) if parts else f"{os.path.basename(path)} · {recipes} recipes · {version}"
        return {
            "name": "run surface",
            "ok": not parts,
            "detail": detail,
            "fix": "asgard just install (runner) · asgard just sync (recipes)",
        }
    except Exception:
        return None  # 진단이 진단 대상을 막지 않는다


def _code_style_check(root: str) -> dict | None:
    """코드 스타일 — 이 저장소가 규격을 들였다면, 선언한 도구가 몇이고 무엇인가.

    실행 표면과 같은 규약으로 **안 들인 저장소에는 행이 없다**. 다만 규격 파일은 있는데 선언이
    없는 경우는 한 줄 세운다 — `checkstyle.xml` 이 저장소에 있는데 게이트가 한 번도 안 도는
    상태는 사용자가 고를 만한 것이지, 모르고 지나갈 것이 아니다."""
    try:
        from ... import code_style, code_style_catalog

        declared = code_style.declared(root)
        if not declared:
            found = code_style_catalog.detect(root)
            if not found:
                return None  # 규격도 선언도 없다 — 진단할 것이 없다
            return {
                "name": "code style",
                "ok": True,
                "detail": f"{len(found)} tool(s) found in the repo, none declared — {', '.join(t.name for t in found[:4])}",
                "fix": "asgard style init",
            }
        autofix = sum(1 for t in declared if t.autofix)
        detail = f"{len(declared)} tool(s) — {', '.join(t.name for t in declared[:4])}"
        if autofix:
            detail += f" · {autofix} run their fix command automatically"
        return {
            "name": "code style",
            "ok": code_style.configured(root),
            "detail": detail if code_style.configured(root) else detail + " · disabled (enabled: false)",
            "fix": "asgard style check",
        }
    except Exception:
        return None  # 진단이 진단 대상을 막지 않는다


def _custom_manual_check(root: str) -> dict | None:
    """커스텀 매뉴얼 — 오딘이 쓴 프로젝트 규칙. 이 계층은 조용히 실패한다(이름 오타·주석 안·별칭
    중복·상한 절단) — 어느 쪽이든 에이전트는 평소처럼 돌고 사용자는 규칙이 적용된 줄 안다.
    그래서 "안 들어가는 이유"만 ⚠ 로 세운다. 매뉴얼 미작성은 결함이 아니다 (ok).
    매뉴얼 계층을 못 읽으면 None — 진단이 진단 대상을 막지 않는다 (fail-open)."""
    try:
        from ...manual import MANUAL_NAMES, MAX_CHARS, discover, enabled, has_marker, load_manual
        from ...manual import label as _rel  # 경로를 루트 기준 상대 표기로 줄인다

        found = discover(root)
        loaded = load_manual(root)
        problems = []
        if found["shadowed"]:
            problems.append("별칭 중복 — 무시해요: " + ", ".join(_rel(root, p) for p in found["shadowed"]))
        # 링크가 저장소 밖을 가리켜 뺀 것. 다른 항목과 달리 이건 사고일 수도, 심어진 것일 수도
        # 있다 — 어느 쪽이든 사용자가 알아야 한다 (조용히 빼면 심은 쪽만 이득이다).
        if found["escaped"]:
            problems.append(
                "저장소 밖을 가리키는 링크 — 안 실어요: " + ", ".join(_rel(root, p) for p in found["escaped"])
            )
        if loaded and loaded["truncated"]:
            problems.append(f"상한 절단 {loaded['chars']}자 — 뒷부분 미주입")
        if found["dropped"]:
            problems.append(f"조각 상한 초과 {len(found['dropped'])}개 제외")
        # `MANUAL.md`는 흔한 이름이다 — 이미 그 이름의 제품 문서를 가진 리포에 설치되면 그 문서가
        # 통째로 프롬프트에 들어간다. 손으로 쓴 진짜 매뉴얼과 구분할 방법이 없어 막지는 않고, **큰**
        # 표식 없는 파일만 짚는다 (작은 파일은 사용자가 직접 쓴 규칙일 가능성이 압도적이다).
        if loaded and loaded["chars"] >= MAX_CHARS // 2:
            stranger = [_rel(root, p) for p in found["files"] if os.path.dirname(p) == root and not has_marker(p)]
            if stranger:
                problems.append(
                    f"{', '.join(stranger)}가 통째로 실리는 중 ({loaded['chars']}자) — 의도한 매뉴얼이 맞는지 확인"
                )
        if not enabled(root):
            detail = "off (manual.mode) — 어떤 모드에도 안 실려요"
        elif loaded:
            layers = f"공통 {len(loaded['common'])} + 프로젝트 {len(loaded['project'])}"
            detail = f"{layers} · {loaded['chars']} chars · 4-mode injected"
        elif found["files"]:
            detail = "파일은 있으나 주입 없음 — 주석뿐 (규칙은 주석 밖에)"
        else:
            detail = f"없음 — 루트 {MANUAL_NAMES[0]}에 쓰면 4모드에 실려요"
        return {
            "name": "custom manual",
            "ok": not problems,
            "detail": detail if not problems else " · ".join(problems),
            "fix": "asgard manual — 무엇이 어디서 실리는지 대조",
        }
    except Exception:
        return None
