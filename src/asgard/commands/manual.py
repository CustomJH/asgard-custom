"""asgard manual — 커스텀 매뉴얼의 사람 표면.

이 명령이 있는 이유는 하나다: 주입 계층은 **조용히 실패한다**. 파일 이름을 틀리거나, 주석 밖으로
안 꺼냈거나, 별칭 둘을 만들어 하나가 가려졌거나, 상한에 잘렸을 때 — 어느 경우든 에이전트는 그냥
평소처럼 동작하고 사용자는 규칙이 먹은 줄 안다. 그래서 "무엇이 어디서 실려서 몇 자로 들어가는가"를
한 화면에 세운다. `--show` 는 모델이 실제로 받는 텍스트 그대로를 낸다 (요약 아님).
"""

from __future__ import annotations

import json
import os

from .. import manual as manual_mod
from .. import ui
from .health import _project_root


def _tilde(path: str) -> str:
    user = os.path.abspath(os.environ.get("HOME") or os.path.expanduser("~"))
    return "~" + path[len(user) :] if path.startswith(user + os.sep) else path


def _state(root: str) -> dict:
    """표시용 상태 — 로드 결과 + 로드 안 됐을 때의 이유까지."""
    found = manual_mod.discover(root)
    loaded = manual_mod.load_manual(root)
    lab = manual_mod.label
    # 파일은 있는데 로드가 없다 = 주석뿐(=시작 템플릿 그대로) 이라는 뜻 — 가장 흔한 "왜 안 먹지".
    inert = [lab(root, p) for p in found["files"] if not manual_mod._meaningful(manual_mod._read(p))]
    # 이름이 흔하다 — 아스가르드가 만든 자리가 아닌데 실리고 있다면 그 사실을 말한다.
    unmarked = [
        lab(root, p)
        for p in found["files"]
        if manual_mod._meaningful(manual_mod._read(p)) and not manual_mod.has_marker(p)
    ]
    return {
        "enabled": manual_mod.enabled(root),
        "files": [lab(root, p) for p in found["files"]],
        "shadowed": [lab(root, p) for p in found["shadowed"]],
        "dropped": [lab(root, p) for p in found["dropped"]],
        "escaped": [lab(root, p) for p in found["escaped"]],
        "inert": inert,
        "unmarked": unmarked,
        "sources": loaded["sources"] if loaded else [],
        "common": loaded["common"] if loaded else [],
        "project": loaded["project"] if loaded else [],
        "chars": loaded["chars"] if loaded else 0,
        "truncated": bool(loaded and loaded["truncated"]),
        "max_chars": manual_mod.max_chars(root),
        "home": manual_mod.home(),
        "active": loaded is not None,
    }


def run_manual(*, show: bool = False, section: str = "identity", json_out: bool = False, quiet: bool = False) -> int:
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out or quiet)
    st = _state(root)

    if json_out:
        print(json.dumps({**st, "root": root, "section": section}, ensure_ascii=False, indent=2))
        return 0

    if show:
        # 요약이 아니라 원문 — "모델이 뭘 받는지"를 눈으로 확인하는 통로다.
        text = manual_mod.note(root, section).strip()
        print(text if text else "(주입 없음)")
        return 0

    ui.head("manual · 커스텀 매뉴얼")
    if not st["enabled"]:
        ui.warn("꺼져 있음 — `manual.mode=off` (설정 또는 ASGARD_MANUAL=off). 어떤 모드에도 안 실린다")
        ui.done()
        return 0

    if not st["files"]:
        ui.step("매뉴얼 없음 — 규칙을 얹으려면 다음 파일을 만든다:")
        ui.step(ui.dim(f"    {_tilde(st['home'])}/MANUAL.md   공통 — 이 기계의 모든 프로젝트"))
        ui.step(
            ui.dim("    MANUAL.md              이 프로젝트만 (별칭: " + " · ".join(manual_mod.MANUAL_NAMES[1:]) + ")")
        )
        ui.step(ui.dim("    .asgard/manual/*.md    주제별 분할 (파일명 정렬 순)"))
        ui.done()
        return 0

    if st["active"]:
        ui.ok(f"실림 — {len(st['sources'])}개 파일 · {st['chars']}자 / 상한 {st['max_chars']}자")
        # 층을 갈라 보여 준다 — "이 규칙이 왜 여기서도 도나"의 답이 이 두 줄에 있다.
        for scope, label, rows in (("common", "공통", st["common"]), ("project", "프로젝트", st["project"])):
            for src in rows:
                ui.step(ui.dim(f"    [{label}] {src}"))
        if st["common"] and st["project"]:
            ui.step(ui.dim("    충돌하면 프로젝트 규칙이 이긴다 (공통 먼저, 프로젝트 나중)"))
        ui.step("4모드 전부에 주입된다 — 네이티브는 프롬프트 인라인, CC·Cursor·Codex 는 manual-activate 훅")
    else:
        ui.warn("파일은 있는데 실리는 내용이 없다 — 주석 밖에 규칙을 써야 켜진다")

    if st["inert"]:
        ui.step(ui.dim("    주석뿐(무주입): " + ", ".join(st["inert"])))
    if st["unmarked"]:
        # `MANUAL.md` 는 흔한 이름이다 — 아스가르드가 깐 자리가 아닌 문서가 실리고 있으면 말해 준다.
        ui.step(ui.dim("    asgard 스캐폴드 아님(직접 만든 파일이면 정상): " + ", ".join(st["unmarked"])))
    if st["shadowed"]:
        # 별칭을 여럿 만들면 디렉터리마다 하나만 이긴다 — 진 파일을 편집하는 사고가 여기서 잡힌다.
        ui.warn("별칭 중복 — 무시된다: " + ", ".join(st["shadowed"]))
    if st["truncated"]:
        ui.warn(
            f"상한 {st['max_chars']}자에서 잘렸다 — 뒷부분은 안 실린다. "
            "`.asgard/manual/*.md` 로 나누거나 설정 `manual.max_chars` 를 올린다"
        )
    if st["dropped"]:
        ui.warn(f"조각 상한({manual_mod.FRAGMENT_CAP}개) 초과로 제외: " + ", ".join(st["dropped"]))
    if st["escaped"]:
        # 링크 대상이 저장소 밖이다. 매뉴얼은 도구 호출이 아니라 판독 게이트가 안 보는 자리라,
        # 실었다면 그 파일이 통째로 프롬프트에 나갔다. 뺀 사실을 반드시 눈에 보이게 둔다.
        ui.warn("저장소 밖을 가리키는 링크 — 안 싣는다: " + ", ".join(st["escaped"]))
    if not st["common"]:
        ui.step(ui.dim(f"    모든 프로젝트 공통 규칙은 {_tilde(st['home'])}/MANUAL.md 에"))
    ui.done()
    return 0
