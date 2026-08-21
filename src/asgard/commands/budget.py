"""asgard budget — 한 세션이 얼마나 썼는지의 사람 표면.

어느 세션인가는 호출자가 정한다. CLI 는 자기를 부른 세션의 id 를 알 방법이 없으므로,
`--session`/`--transcript` 를 안 주면 이 프로젝트에서 **가장 최근에 쓰인** 트랜스크립트를
고르고 화면에 그렇게 적는다. 그 구분을 안 하던 판은 병렬 세션이 도는 트리에서 형제 세션의
값을 "이 세션이 쓴 것"이라고 적었다 (26-08-21 실측 — opus-5 세션에서 물으니 다른 세션의
100,752 와 `claude-opus-4-8` 을 답했다).

왜 게이트만으론 부족한가: 상한은 벽이고, 벽은 부딪혀야 알게 된다. 부딪히고 나서야 아는 예산은
예산이 아니라 사고다. 이 화면의 계약은 **벽에 닿기 전에 보이게 하는 것** 하나다.

세 가지를 한 화면에 넣는다: ① 가중 비용 단위(판정에 실제로 쓰이는 값)와 남은 여유, ② 네 성분의
원시 값 — 가중치는 가정이고 가정이 바뀌어도 관측은 남아야 한다, ③ 레인별 귀속(메인 vs 역할별).
③ 이 없으면 "많이 썼다"는 알아도 "어디서 썼다"를 몰라 다음 세션이 똑같이 쓴다.
"""

from __future__ import annotations

import glob
import json
import os

from .. import ui
from ..hooks import budget_guard as bg


def _project_key(root: str) -> str:
    """Claude Code의 프로젝트 트랜스크립트 디렉터리 이름 — 경로 구분자를 `-`로 치환한 형태."""
    return os.path.abspath(root).replace(os.sep, "-").replace("_", "-")


# 형제 세션이 "같은 무렵에 살아 있었다"고 볼 시간 창. 이보다 가까이 쓰인 트랜스크립트가
# 여럿이면 최근순 고르기는 동전 던지기이므로, 골랐다고 말하지 않고 여럿이라고 말한다.
SIBLING_WINDOW_SECONDS = 300.0


def _transcript_dir(root: str) -> str:
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".claude", "projects", _project_key(root))


def transcript_for_session(root: str, session: str) -> str:
    """id 로 지목한 트랜스크립트. 없으면 빈 문자열 — 다른 것으로 대신 재지 않는다."""
    path = os.path.join(_transcript_dir(root), f"{session}.jsonl")
    return path if os.path.isfile(path) else ""


def latest_transcript(root: str) -> str:
    """이 프로젝트에서 가장 최근에 쓰인 트랜스크립트. 없으면 빈 문자열.

    **이것이 부른 쪽의 세션이라는 보장은 없다.** CLI 에는 자기 세션 id 가 없으므로 최근순으로
    고를 뿐이고, 병렬 세션이 도는 트리에서는 형제 것을 고른다. 화면이 그 사실을 말해야 한다
    (`sibling_transcripts` 가 후보 수를 센다)."""
    files = [p for p in glob.glob(os.path.join(_transcript_dir(root), "*.jsonl")) if os.path.isfile(p)]
    if not files:
        return ""
    return max(files, key=os.path.getmtime)


def sibling_transcripts(root: str, chosen: str) -> int:
    """고른 것 말고, 같은 무렵에 쓰인 트랜스크립트가 몇 개인가."""
    if not chosen:
        return 0
    try:
        picked_at = os.path.getmtime(chosen)
    except OSError:
        return 0
    near = 0
    for path in glob.glob(os.path.join(_transcript_dir(root), "*.jsonl")):
        if os.path.abspath(path) == os.path.abspath(chosen):
            continue
        try:
            if picked_at - os.path.getmtime(path) <= SIBLING_WINDOW_SECONDS:
                near += 1
        except OSError:
            continue
    return near


def _payload(
    ledger: bg.Ledger, limits: dict, spent: float, *, transcript: str = "", named: bool = False, siblings: int = 0
) -> str:
    weights = limits.get("weights") if isinstance(limits.get("weights"), dict) else None
    total = ledger.total()
    return json.dumps(
        {
            # 무엇을 쟀는가를 값과 같이 낸다 — 숫자만 보면 남의 세션인지 알 수 없다.
            "transcript": os.path.basename(transcript),
            "session_named": named,
            "sibling_sessions": siblings,
            "enforce": limits.get("enforce"),
            "cost_units": round(spent),
            "session_cost_units": limits.get("session_cost_units"),
            "warn_cost_units": round(bg.warn_threshold(limits)),
            "raw": {
                "input": total.input,
                "output": total.output,
                "cache_write": total.cache_write,
                "cache_read": total.cache_read,
            },
            "main_cost_units": round(ledger.main.cost_units(weights)),
            "agents": {
                role: {
                    "calls": ledger.agent_calls.get(role, 0),
                    "cost_units": round(usage.cost_units(weights)),
                }
                for role, usage in sorted(ledger.agents.items())
            },
            "agent_calls_without_usage": {
                role: n for role, n in sorted(ledger.agent_calls.items()) if role not in ledger.agents
            },
            "models": dict(sorted(ledger.models.items())),
            "read_error": ledger.read_error,
        },
        ensure_ascii=False,
        indent=2,
    )


# 게이트가 가리키는 손잡이 — 이 표에 있는 키만 명령으로 바뀐다.
# 왜 명령이 필요한가: 상한에 닿은 게이트는 "`budget.session_cost_units` 를 올려라"라고 안내하는데
# 통제 표면 가드(`hooks/readonly_guard.py`)는 `.asgard/` 아래 편집을 어느 역할에게도 안 연다 —
# 하네스가 자기가 막는 편집을 지시하던 자리다 (26-08-05). 좁은 동사 하나가 그 짝을 맞춘다.
# `enforce` 는 여기 없다. 집행을 끄는 것은 상한을 올리는 것과 다른 종류의 결정이고, 이 명령을
# 실행하는 것은 방금 그 게이트에 막힌 역할이다 — 자기를 막은 문을 스스로 떼는 손잡이는 안 준다.
SETTABLE = {
    "session_cost_units": "이 세션이 쓸 수 있는 가중 비용 단위 상한",
    "warn_cost_units": "경고를 울리는 문턱 — 안 적으면 상한의 80%",
    "agent_cost_units": "역할 하나가 세션 내내 쓸 수 있는 누적 상한",
    "agent_calls": "역할 하나의 세션 내 호출 횟수 상한",
}
# 값의 상한. 막는 것은 `inf`·`1e400` 처럼 수가 아닌 수와 오타지, 오딘이 고를 수 있는 폭이
# 아니다 — 상한을 얼마로 둘지는 그의 결정이고 이 상수는 그 결정을 대신하지 않는다.
_MAX_UNITS = 10**12


def _parse_assignment(text: str) -> tuple[str, int]:
    """`key=value` 한 줄 → (키, 값). 형식·키·값이 어긋나면 ValueError 로 이유를 그대로 올린다."""
    key, sep, raw = str(text).partition("=")
    key, raw = key.strip(), raw.strip()
    if not sep or not key or not raw:
        raise ValueError(f"`{text}` 는 `키=값` 형태가 아니에요")
    if key not in SETTABLE:
        raise ValueError(f"`{key}` 는 이 명령이 바꾸는 키가 아니에요 — {', '.join(sorted(SETTABLE))}")
    try:
        # inf·1e400 은 float 으로는 살아남고 int() 에서 OverflowError 를 낸다 — ValueError 만
        # 잡으면 친절한 안내 대신 역추적이 나간다.
        number = int(float(raw.replace("_", "").replace(",", "")))
    except ValueError, OverflowError:
        raise ValueError(f"`{key}` 는 수를 받아요 (받은 값: {raw})") from None
    if not 0 < number <= _MAX_UNITS:
        raise ValueError(f"`{key}` 는 1 이상 {_MAX_UNITS:,} 이하여야 해요 (받은 값: {raw})")
    return key, number


def _project_root(start: str) -> str:
    """설정 파일이 실제로 읽히는 자리 — `.asgard` 나 `.git` 을 가진 가장 가까운 조상.

    `os.getcwd()` 를 그대로 쓰면 하위 폴더에서 부른 이 명령이 아무도 안 읽는
    `<하위폴더>/.asgard/asgard-setting-project.json` 을 새로 만든다 — 상한이 바뀐 것처럼
    보이고 실제로는 안 바뀐다."""
    current = os.path.realpath(start)
    while True:
        # 연결된 worktree 는 `.git` 이 파일이다 — isdir 로만 보면 그 뿌리를 지나쳐 올라간다.
        if os.path.isdir(os.path.join(current, ".asgard")) or os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.realpath(start)
        current = parent


def run_budget_set(assignments: list[str], *, json_out: bool = False) -> int:
    """`asgard budget --set key=value` — 프로젝트 설정의 budget 섹션만 고쳐 쓴다.

    섹션 교체(`settings.save_project`)라 지금 값을 먼저 읽어 병합한다. 기본값은 안 적는다:
    설정에 없던 키를 이 명령이 굳혀 놓으면 다음 판(`DEFAULTS`)이 올라가도 이 저장소만 옛 값에
    머문다."""
    from ..settings import load_project, project_path, save_project

    root = _project_root(os.getcwd())
    ui.set_quiet(json_out)
    changed: dict[str, int] = {}
    try:
        # 파일이 있는데 못 읽으면 여기서 멈춘다. `load_project` 는 그때 빈 dict 로 물러서고
        # `save_project` 는 섹션을 통째로 교체하므로, 그대로 두면 쉼표 하나 때문에
        # trinity_policy·paths·agents 가 한 번에 사라진다.
        settings_path = project_path(root)
        if os.path.exists(settings_path):
            with open(settings_path, encoding="utf-8") as handle:
                if not isinstance(json.load(handle), dict):
                    raise ValueError(f"{settings_path} 가 JSON 객체가 아니에요 — 고친 뒤 다시 불러 주세요")
        section = load_project(root).get("budget")
        values = dict(section) if isinstance(section, dict) else {}  # `"budget": 5` 는 섹션이 아니다
        for text in assignments:
            key, value = _parse_assignment(text)
            changed[key] = value
            values[key] = value
    except json.JSONDecodeError as error:
        message = f"{project_path(root)} 를 JSON 으로 못 읽었어요 — {error}"
        print(json.dumps({"error": message}, ensure_ascii=False)) if json_out else ui.warn(message)
        return 2
    except (ValueError, OSError) as error:
        message = str(error) if isinstance(error, ValueError) else f"{project_path(root)} 를 못 읽었어요 — {error}"
        if json_out:
            print(json.dumps({"error": message}, ensure_ascii=False))
        else:
            ui.warn(message)
        return 2
    path = save_project(root, "budget", values)
    if json_out:
        print(json.dumps({"path": path, "changed": changed, "budget": values}, ensure_ascii=False, indent=2))
        return 0
    ui.head("budget · 상한을 고쳤어요")
    for key, value in changed.items():
        ui.ok(f"{key} = {value:,}")
    ui.step(ui.dim(f"    {path}"))
    ui.done()
    return 0


def run_budget(*, transcript: str = "", session: str = "", json_out: bool = False, quiet: bool = False) -> int:
    """종료 코드 = 상한 도달이면 1, 경고면 0. 화면은 막지 않는다 — 막는 것은 훅의 일이다."""
    # 쓰는 쪽(`run_budget_set`)과 같은 자리를 봐야 한다. 하위 폴더에서 부르면 방금 고친 값이
    # 아니라 없는 파일의 기본값이 보인다.
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out or quiet)
    named = bool(transcript or session)
    path = transcript or (transcript_for_session(root, session) if session else latest_transcript(root))
    if session and not path:
        ui.set_quiet(quiet)
        ui.fail(f"그 세션의 트랜스크립트가 없어요: {session}")
        return 2
    siblings = 0 if named else sibling_transcripts(root, path)
    limits = bg.load_limits(root)
    ledger = bg.read_ledger(path)
    weights = limits.get("weights") if isinstance(limits.get("weights"), dict) else None
    spent = ledger.cost_units(weights)
    result = bg.verdict(ledger, limits)

    if json_out:
        print(_payload(ledger, limits, spent, transcript=path, named=named, siblings=siblings))
        return 1 if result.action == "block" else 0

    ui.head("budget · 이 세션이 쓴 것" if named else "budget · 가장 최근 세션이 쓴 것")
    if not path:
        ui.warn("이 프로젝트의 트랜스크립트를 못 찾았어요 — 잴 세션이 없네요")
        ui.done()
        return 0
    ui.step(ui.dim(f"트랜스크립트 {os.path.basename(path)}"))
    if siblings:
        ui.warn(
            f"같은 무렵에 쓰인 세션이 {siblings}개 더 있어요 — 이 값이 당신 세션의 것이 아닐 수 있어요. "
            "정확히 재려면 `asgard budget --session <id>`"
        )
    if ledger.read_error:
        ui.warn(f"일부만 읽었어요 — {ledger.read_error}")

    ceiling = float(limits.get("session_cost_units") or bg.DEFAULTS["session_cost_units"])
    warn_at = bg.warn_threshold(limits)
    pct = (spent / ceiling * 100) if ceiling else 0.0
    line = f"가중 비용 단위 {spent:,.0f} / {ceiling:,.0f} ({pct:.0f}%)"
    (ui.warn if spent >= warn_at else ui.ok)(line)
    ui.step(ui.dim(f"    경고 문턱 {warn_at:,.0f} · 집행 {limits.get('enforce')}"))

    total = ledger.total()
    ui.phase("원시 성분 (가중치는 가정, 관측은 사실)")
    for label, value, weight in (
        ("입력", total.input, bg.WEIGHTS["input"]),
        ("출력", total.output, bg.WEIGHTS["output"]),
        ("캐시 쓰기", total.cache_write, bg.WEIGHTS["cache_write"]),
        ("캐시 읽기", total.cache_read, bg.WEIGHTS["cache_read"]),
    ):
        ui.step(f"{label:<10} {value:>14,d}  ×{weight}")

    if ledger.agent_calls:
        ui.phase("레인별 귀속")
        ui.step(f"{'main':<24} {ledger.main.cost_units(weights):>14,.0f}")
        for role, calls in sorted(ledger.agent_calls.items(), key=lambda kv: -kv[1]):
            usage = ledger.agents.get(role)
            spent_role = usage.cost_units(weights) if usage else 0.0
            note = "" if usage else "  (usage 미제공)"
            ui.step(f"{role:<24} {spent_role:>14,.0f}  ×{calls}회{note}")

    if result.action == "block":
        ui.warn(result.message)
    ui.done()
    return 1 if result.action == "block" else 0
