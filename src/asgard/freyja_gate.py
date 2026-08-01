"""asgard freyja gate — 이번 변경분의 **시각 표면** 판정. craft가 형상을, thor가 정확성을 잰다면 이쪽은 표면이다.

왜 필요한가 (실측된 실패에서 나왔다):
    에이전트가 "프레이야 엔진 4로 했다"고 말하고, 엔진의 판정기 하나만 돌려 PASS를 받고,
    설계 흐름(장르·매크로 구조·사전 자기비평)은 건너뛰었다. 판정기는 산출물만 보므로 통과했고,
    사람은 그 화면을 보자마자 "AI 슬롭"이라고 했다.

    엔진들은 흐름을 **산문으로** 규정한다. 산문은 아무것도 막지 않는다. 이 모듈은 각 엔진이
    이미 가진 **자기 판정기를 불러** 이번에 손댄 표면에만 물린다. 규칙을 여기서 다시 쓰지
    않는 이유는 하나다 — 규칙이 두 곳에 있으면 둘은 반드시 갈라진다.

계약은 craft·thor와 같은 **래칫**이다:

    이미 있던 것은 막지 않는다. 이번 변경이 **더 나쁘게 만든 것**만 막는다.

그리고 하나 더 진다: **무엇을 못 쟀는지 같이 넣는다.** 엔진마다 판정기가 있을 수도, 없을 수도
있고(node 부재·플러그인 미설치), 판정기가 스스로 "이건 사람 몫"이라고 돌려주는 게이트도 있다.
0건이 "안 봤다"를 뜻할 수 있으면 게이트가 아니라 장식이다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from importlib.resources import files as _files

from .craft import _base_text, changed_paths

# 판정 대상 — 시각 표면. 파이썬 안에 박힌 템플릿 문자열까지 쫓지는 않는다(정직한 한계).
SURFACE_EXT = (".html", ".htm", ".css")
_TIMEOUT = 90


@dataclass(frozen=True)
class Engine:
    """엔진 하나. `runtime`은 그 엔진이 스스로 배송하는 판정기의 플러그인 상대 경로."""

    key: str
    name: str
    plugin: str
    runtime: str | None
    vault: str  # `.asgard/.vanadis/` 아래 그 엔진이 증거를 남기는 자리
    judges: str  # 이 판정기가 무엇을 보는가 (보고서에 그대로 들어간다)


# 프레이야 계열 + 토르. 토르는 시각이 아니라 절차라 판정기가 파이썬 쪽에 있고(thor_gate),
# 여기서는 "이 게이트가 그를 대신하지 않는다"는 사실을 싣기 위해 목록에 둔다.
ENGINES: tuple[Engine, ...] = (
    Engine("freyja1", "프레이야 1 · 디자인", "freyja-design", None, "engine1", "판정기 없음 — 흐름 증거만"),
    Engine("freyja2", "프레이야 2 · 커맨드", "freyja2", "engine/scripts/detect.mjs", "engine2", "디자인 탐지기"),
    Engine("freyja3", "프레이야 3 · 3D", "freyja-3d", "engine/scripts/cad_gate.mjs", "3d", "형상·씬 판정"),
    Engine(
        "freyja4",
        "프레이야 4 · 마르될",
        "freyja4",
        "engine/scripts/slop_gate.mjs",
        "engine4",
        "58게이트 중 기계 판정 가능분",
    ),
    Engine(
        "sjonhverfing",
        "프레이야 · 숀헤르빙",
        "freyja-sjonhverfing",
        "engine/scripts/depth_gate.mjs",
        "sjonhverfing",
        "의사 3D 깊이 판정",
    ),
    Engine("thor", "토르 · 절차", "asgard-thor-bilskirnir", None, "thor", "`asgard thor gate` 소관 — 여기서 안 잰다"),
)

_BY_KEY = {engine.key: engine for engine in ENGINES}


@dataclass
class Finding:
    path: str
    gate: str
    detail: str
    engine: str

    def line(self) -> str:
        return f"{self.path}  [{self.engine} {self.gate}] {self.detail}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    surfaces: tuple[str, ...] = ()
    unjudged: list[str] = field(default_factory=list)
    engines: list[str] = field(default_factory=list)

    def blocking(self) -> tuple[Finding, ...]:
        return tuple(self.findings)


def _plugin_root(plugin: str) -> str | None:
    """설치된 휠 안의 플러그인 자리. 개발 트리에서도 같은 경로다."""
    try:
        base = _files("asgard") / "assets" / "skill_plugins" / plugin / "skills"
        if not base.is_dir():
            return None
        for child in base.iterdir():
            if child.is_dir():
                return str(child)
    except Exception:
        return None
    return None


def runtime_path(engine: Engine) -> str | None:
    if not engine.runtime:
        return None
    root = _plugin_root(engine.plugin)
    if not root:
        return None
    path = os.path.join(root, *engine.runtime.split("/"))
    return path if os.path.isfile(path) else None


def _node() -> str | None:
    return shutil.which("node")


def _run_slop_gate(runtime: str, target: str, genre: str = "modern-minimal") -> list[tuple[str, str]] | None:
    """엔진 4 판정기를 JSON으로 돌린다. (gate, detail) 목록 — None 이면 판정 자체가 불가."""
    node = _node()
    if not node:
        return None
    try:
        proc = subprocess.run(
            [node, runtime, target, "--json", "--genre", genre],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
    except OSError, subprocess.SubprocessError:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    # 계약: 판정기는 게이트 전부를 `gates`로 주고 각자 status를 갖는다. 실패만 걷는다 —
    # `manual`은 판정기가 스스로 "이건 사람 몫"이라 한 것이라 게이트가 대신 막지 않는다.
    out: list[tuple[str, str]] = []
    for gate in payload.get("gates") or []:
        if gate.get("status") != "fail":
            continue
        gid = str(gate.get("id"))
        for finding in gate.get("findings") or [gate.get("title", "")]:
            out.append((gid, str(finding)))
    return out


def _judge_surface(root: str, rel: str, base: str, engine: Engine, runtime: str) -> tuple[list[Finding], bool]:
    """한 표면을 판정하고 **base 대비 새로 생긴 것만** 돌려준다.

    래칫의 구현부: 같은 판정기를 base 판본에도 돌려, 그때도 있던 지적은 통과시킨다.
    base 판본이 없으면(신규 파일) 전부 이번 변경의 책임이다."""
    target = os.path.join(root, rel)
    now = _run_slop_gate(runtime, target)
    if now is None:
        return [], False
    before: set[tuple[str, str]] = set()
    prior = _base_text(root, rel, base)
    if prior is not None:
        suffix = os.path.splitext(rel)[1] or ".html"
        handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
        try:
            handle.write(prior)
            handle.close()
            was = _run_slop_gate(runtime, handle.name)
            if was:
                # 자리(파일명·줄)는 판본마다 달라진다 — 게이트 정체로만 비교해야 래칫이 흔들리지 않는다
                before = {(gid, _strip_locus(detail)) for gid, detail in was}
        finally:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
    fresh = [Finding(rel, gid, detail, engine.key) for gid, detail in now if (gid, _strip_locus(detail)) not in before]
    return fresh, True


def _strip_locus(detail: str) -> str:
    """`파일:줄  본문`에서 자리를 떼어 낸다 — 같은 지적이 줄만 밀렸다고 새 결함이 되면 안 된다."""
    if "  " in detail:
        head, _, tail = detail.partition("  ")
        if ":" in head and head.rsplit(":", 1)[-1].isdigit():
            return tail.strip()
    return detail.strip()


def judge(root: str, paths: "tuple[str, ...] | list[str] | None" = None, base: str = "HEAD") -> Report:
    """이번 변경이 손댄 시각 표면만 각 엔진의 판정기에 건다."""
    root = os.path.abspath(root)
    rels = tuple(paths) if paths else changed_paths(root, base)
    surfaces = tuple(
        rel
        for rel in rels
        if rel.lower().endswith(SURFACE_EXT) and os.path.isfile(os.path.join(root, rel)) and "/node_modules/" not in rel
    )
    report = Report(surfaces=surfaces)
    if not surfaces:
        return report

    for engine in ENGINES:
        runtime = runtime_path(engine)
        if runtime is None:
            reason = "판정기를 배송하지 않는다" if not engine.runtime else "플러그인이 설치돼 있지 않다"
            report.unjudged.append(f"{engine.name} — {reason} ({engine.judges})")
            continue
        if engine.key != "freyja4":
            # 다른 엔진의 판정기는 입력 계약이 다르다(3D는 모델, 숀헤르빙은 장면). 표면 파일을
            # 그대로 물리면 거짓 판정이 난다 — 안 재는 편이 정직하다.
            report.unjudged.append(f"{engine.name} — 이 게이트가 물릴 입력이 아니다 ({engine.judges})")
            continue
        report.engines.append(engine.name)
        judged_any = False
        for rel in surfaces:
            fresh, judged = _judge_surface(root, rel, base, engine, runtime)
            judged_any = judged_any or judged
            report.findings.extend(fresh)
        if not judged_any:
            report.unjudged.append(f"{engine.name} — node를 못 찾아 판정기를 못 돌렸다")
            report.engines.remove(engine.name)
    return report


def run_gate(
    root: str | None = None,
    base: str = "HEAD",
    json_out: bool = False,
    paths: "tuple[str, ...]" = (),
) -> int:
    """`asgard freyja-gate` — 종료 코드 1 이면 이번 변경이 표면을 더 나쁘게 만들었다.

    JSON 키는 craft·thor gate와 같은 계약이다(`blocking`) — SubagentStop 훅이 세 게이트를
    같은 방식으로 읽어야 하나가 고장 나도 나머지 판정이 산다."""
    from . import ui

    root = os.path.abspath(root or os.getcwd())
    report = judge(root, paths or None, base=base)
    if json_out:
        rows = [{"path": f.path, "gate": f.gate, "detail": f.detail, "engine": f.engine} for f in report.findings]
        print(
            json.dumps(
                {
                    "base": base,
                    "surfaces": list(report.surfaces),
                    "engines": report.engines,
                    "unjudged": report.unjudged,
                    "blocking": rows,
                    "findings": rows,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return 1 if report.findings else 0

    ui.head("freyja · gate")
    if not report.surfaces:
        ui.ok("이번 변경에 시각 표면이 없습니다 — 잴 것이 없습니다")
        return 0
    ui.step(f"표면 {len(report.surfaces)}건: " + ", ".join(report.surfaces[:6]))
    for note in report.unjudged:
        ui.step(f"못 잰 것 — {note}")
    if not report.findings:
        ui.ok(f"이번 변경이 더 나쁘게 만든 것 없음 (판정: {', '.join(report.engines) or '없음'})")
        return 0
    for finding in report.findings:
        ui.fail(finding.line())
    ui.step("래칫입니다 — 이미 있던 지적은 안 막습니다. 위 목록은 이번 변경이 새로 만든 것입니다.")
    return 1
