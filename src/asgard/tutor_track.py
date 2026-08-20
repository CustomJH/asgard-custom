"""튜터 트랙 — 물음의 **종류**가 아니라 사람이 **어느 영역까지 갔는가**를 재는 층.

`tutor_growth.level(data, kind)`은 종류(behavior-removed·test-removed…)를 잰다. 그건 탐침을
재는 자리다 — 탐침 다섯이 전부 1단계라는 말은 사람에 대해 아무것도 말하지 않는다. 사람을 재려면
축이 영역이어야 하는데, 그 축은 이미 디스크에 있다: 물음마다 `path`가 붙어 있고
`tutor_teach._area`가 경로를 영역 이름으로 접는다. 둘을 이으면 새 분류를 만들지 않고 트랙이 나온다.

단계 어휘는 `tutor_teach.DEPTHS`를 그대로 쓰고 바닥에 `unseen`만 얹는다. 같은 어휘를 여기 다시
적으면 사본이 둘이 되고, 사본은 갈린다 — 이 저장소는 지도 종류 어휘를 네 곳에 적어 셋이 갈린
적이 있다.

**한 번 오른 단계는 안 내려간다.** 근거가 감정이 아니라 계측이다: 배치의 근거인 `growth.json`은
줄어드는 기록이다. `tutor_growth.expire`는 코드가 사라진 물음을 닫고, `save`는 닫힌 물음을
`CLOSED_CAP`(300)까지만 남긴다. 그래서 단계를 매번 셈에서 다시 만들면, 사람이 아무것도 안 해도
코드가 움직이는 것만으로 단계가 스스로 지워진다. 그래서 셈은 growth에서 파생하고 **단계와 시험
결과는 `.asgard/tutor/track.json`에 적는다** — growth가 말할 수 없는 것만 이 파일이 진다.

채점 경계 둘:

  ① 매일 놓이는 카드 물음은 **여전히 안 채점한다**(`tutor_growth.py` 계약 ①). 여기서도 세는 것은
     답했는가뿐이고 답이 옳았는가는 안 본다.
  ② 승급 시험(`pick_exam`·`grade`)은 오딘이 스스로 치는 별개 표면이고, 채점하되 **회수만** 센다 —
     `surface.candidates`가 이름으로 찾는 후보라 동적 호출을 못 봐서, 못 댄 것은 세고 더 댄 것은
     안 깎는다. 시험 결과는 `track.json`에만 적고 `growth.json`에는 한 글자도 안 쓴다.

모든 읽기는 fail-open이고 쓰기 실패는 삼킨다. 이 층은 관문이 아니다.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from . import surface, tutor_growth, tutor_teach
from .io_files import read_json, write_json

TRACK_REL = os.path.join(".asgard", "tutor", "track.json")
VERSION = 1
# 어휘의 정본은 tutor_teach다. 여기서 새로 적지 않는다 — 사본이 둘이면 언젠가 갈린다.
RUNGS: tuple[str, ...] = ("unseen",) + tuple(tutor_teach.DEPTHS)
BARS: dict[str, str] = {
    "unseen": "아직 안 만났어요",
    "first": "물음을 받았어요",
    "familiar": "답해 봤어요",
    "owned": "당신 것이에요",
}
FAMILIAR_AT = 2  # 이 트랙에서 자기 문장으로 답한 물음 수
OWNED_AT = 5  # 가정 — tutor_growth.OWNED_AT(종류 축 3)을 넓은 트랙 축으로 옮긴 값이지 실측이 아니다
PASS_NUM, PASS_DEN = 2, 3  # 승급 시험 통과선 = 회수 2/3
EXAM_CAP = 5  # 한 번에 묻는 호출 자리 상한. 마흔 곳 중 스물일곱을 대라는 것은 이해가 아니라 암기다
EXAM_MIN = 4  # 부르는 자리가 이보다 적으면 시험을 안 낸다 — 2/3가 사실상 전부라서 받아쓰기가 된다
HISTORY_CAP = 40  # 단계 기록 보존 상한 — 커져서 안 읽히면 안 적은 것과 같다
_PATH_TOKEN = re.compile(r"[\w./\\-]+\.py")


@dataclass(frozen=True)
class Count:
    """한 트랙에 놓인 물음을 센 것. 전부 `growth.json`에서 파생하고 여기서는 안 적는다."""

    asked: int = 0
    deep: int = 0
    open_now: int = 0
    kinds: tuple[str, ...] = ()
    units: tuple[tuple[str, str], ...] = ()  # 깊은 답이 달린 (경로, 단위) — 시험 후보


_EMPTY = Count()


# ── 기록 입출력 ────────────────────────────────────────────────────


def _path(root: str) -> str:
    return os.path.join(root, TRACK_REL)


def load(root: str) -> dict:
    """없거나 깨졌으면 빈 기록. 기록 손상은 사고의 흔적이지 오딘의 잘못이 아니다."""
    data = read_json(_path(root), None)
    tracks = data.get("tracks") if isinstance(data, dict) else None
    return {
        "version": VERSION,
        "tracks": tracks if isinstance(tracks, dict) else {},
    }


def save(root: str, data: dict) -> bool:
    """못 써도 예외를 안 올린다 — 기록 실패가 화면을 막으면 이 층이 관문이 된다."""
    try:
        write_json(_path(root), data, indent=1, sort_keys=True)
        return True
    except OSError, TypeError, ValueError:
        return False


def _row(state: dict, track: str) -> dict:
    """트랙 한 줄을 꺼내되 없으면 만든다. `destination`·`cut`·`milestones`는 **빈 채로** 둔다 —
    다 배우면 무엇을 할 수 있는지, 지금 무엇을 안 보는지는 기계가 지어낼 것이 아니라 오딘이 적는다."""
    row = state["tracks"].get(track)
    if not isinstance(row, dict):
        row = {}
        state["tracks"][track] = row
    if row.get("rung") not in RUNGS:
        row["rung"] = "unseen"
    if not isinstance(row.get("exam"), dict):
        row["exam"] = {}
    for key in ("history", "cut", "milestones"):
        if not isinstance(row.get(key), list):
            row[key] = []
    row.setdefault("destination", "")
    row.setdefault("placed_at", 0.0)
    row.setdefault("placed_by", "auto")
    return row


# ── 트랙 축으로 다시 세기 ──────────────────────────────────────────


def _rows(data: dict):
    """열린 물음과 닫힌 물음을 같은 세 칸으로 읽는다 — (이름, 행, 지금 열려 있는가)."""
    for cid, row in data.get("open", {}).items():
        if isinstance(row, dict):
            yield (str(cid), row, True)
    for row in data.get("closed", []):
        if isinstance(row, dict):
            yield (str(row.get("cid") or ""), row, False)


def _is_deep(row: dict) -> bool:
    """자기 문장으로 답한 물음. `depth`는 `tutor_growth._depth`가 길이로 매긴 계측값이지 점수가 아니다."""
    return row.get("reason") == "answered" and row.get("depth") == "full"


def counts(root: str) -> tuple[dict[str, Count], int]:
    """`growth.json`을 트랙 축으로 다시 센다. 반환 = (트랙별 셈, 좌표가 없어 못 넣은 물음 수).

    같은 이름(cid)은 한 번만 센다. 안 그러면 한 물음을 다섯 번 답해서 `owned`에 닿는 길이 열리고,
    그건 사람이 자기를 속이는 통로다. 셈은 물음 수에 비례한다 — 트랙 찾기는 dict 조회다.
    """
    data = tutor_growth.load(root)
    acc: dict[str, dict] = {}
    asked_seen: set[str] = set()
    deep_seen: set[str] = set()
    homeless = 0
    for cid, row, live in _rows(data):
        path = str(row.get("path") or "").strip()
        if not path:
            homeless += 1
            continue
        bucket = acc.setdefault(
            tutor_teach._area(path),
            {"asked": 0, "deep": 0, "open_now": 0, "kinds": set(), "units": set()},
        )
        if cid not in asked_seen:
            asked_seen.add(cid)
            bucket["asked"] += 1
        if live:
            bucket["open_now"] += 1
        if _is_deep(row) and cid and cid not in deep_seen:
            deep_seen.add(cid)
            _note_deep(bucket, row, path)
    return ({name: _count(bucket) for name, bucket in acc.items()}, homeless)


def _note_deep(bucket: dict, row: dict, path: str) -> None:
    bucket["deep"] += 1
    kind = str(row.get("kind") or "").strip()
    unit = str(row.get("unit") or "").strip()
    if kind:
        bucket["kinds"].add(kind)
    if unit:
        bucket["units"].add((path, unit))


def _count(bucket: dict) -> Count:
    return Count(
        asked=bucket["asked"],
        deep=bucket["deep"],
        open_now=bucket["open_now"],
        kinds=tuple(sorted(bucket["kinds"])),
        units=tuple(sorted(bucket["units"])),
    )


# ── 단계 ───────────────────────────────────────────────────────────


def bar(rung: str) -> str:
    """단계 하나의 화면 문장. 조건만 있고 문장이 없으면 오딘은 무엇을 향해 가는지 모른다."""
    return BARS.get(rung, BARS["unseen"])


def derived(count: Count, exam_passed: bool) -> str:
    """지금 기록이 말하는 단계. 저장된 단계와 다를 수 있고, 낮으면 저장된 쪽이 우선한다."""
    if count.deep >= OWNED_AT and exam_passed:
        return "owned"
    if count.deep >= FAMILIAR_AT:
        return "familiar"
    return "first" if count.asked >= 1 else "unseen"


def remaining(count: Count, rung: str, exam_passed: bool) -> str:
    """다음 단계까지 무엇이 모자란가 — 한 문장. 기준만 걸어 두고 남은 몫을 안 적으면 사다리가 아니다."""
    if rung == "owned":
        return ""
    if rung == "unseen":
        return "이 영역에 물음이 아직 안 놓였어요 — 여기 코드를 고치면 물음이 생겨요"
    if rung == "first":
        return f"자기 문장으로 답한 물음이 {max(1, FAMILIAR_AT - count.deep)}건 더 필요해요"
    return _owned_gap(count, exam_passed)


def _owned_gap(count: Count, exam_passed: bool) -> str:
    short = max(0, OWNED_AT - count.deep)
    if short and not exam_passed:
        return f"깊은 답 {short}건과 승급 시험 1회 통과가 더 필요해요"
    if short:
        return f"깊은 답 {short}건이 더 필요해요 — 시험은 이미 통과했어요"
    return "승급 시험 1회 통과만 남았어요 — `pick_exam`이 물음을 골라 줘요"


def _keep(row: dict, want: str, stamp: float) -> tuple[str, bool]:
    """오르면 적고 내려가면 안 내린다. 반환 = (화면에 쓸 단계, 셈이 줄었는가)."""
    stored = str(row["rung"])
    if RUNGS.index(want) > RUNGS.index(stored):
        row["rung"] = want
        row["placed_at"] = stamp
        _log(row, want, f"기록이 `{want}` 조건을 채웠어요 — {bar(want)}", stamp)
        return (want, False)
    if RUNGS.index(want) < RUNGS.index(stored):
        _log(row, want, f"셈은 `{want}`로 줄었지만 단계는 `{stored}`로 둬요", stamp)
        return (stored, True)
    return (stored, False)


def _log(row: dict, rung: str, why: str, stamp: float) -> None:
    """같은 사실을 두 번 안 적는다 — 매 호출마다 회귀를 적으면 기록이 한 문장으로 가득 찬다."""
    history = row["history"]
    last = history[-1] if history else None
    if isinstance(last, dict) and last.get("rung") == rung and last.get("why") == why:
        return
    history.append({"rung": rung, "when": stamp, "why": why})
    del history[:-HISTORY_CAP]


# ── 화면 재료 ──────────────────────────────────────────────────────


def place(root: str, now: float | None = None) -> dict:
    """트랙을 스스로 배치한다. 설문을 안 시키고 이미 디스크에 있는 것만 읽는다.

    반환은 CLI가 다시 계산할 것이 없는 형태다 — `tracks`·`mission`·`active`, 그리고 못 본 것을
    적은 `notes`. 오른 단계는 이 호출에서 `track.json`에 적힌다(쓰기 실패는 삼킨다).
    """
    stamp = time.time() if now is None else now
    state = load(root)
    tally, homeless = counts(root)
    notes = _notes(root, tally, homeless)
    rows = []
    for name in sorted(set(tally) | set(state["tracks"])):
        row, shrank = _placed(state, name, tally.get(name, _EMPTY), stamp)
        rows.append(row)
        if shrank:
            notes.append(f"`{name}` — 물음이 만료·정리로 줄었지만 단계는 안 내려요")
    save(root, state)
    rows.sort(key=lambda row: (-RUNGS.index(row["rung"]), -row["deep"], -row["asked"], row["track"]))
    return {
        "tracks": rows,
        "mission": tutor_teach.mission(root),
        "active": [row["track"] for row in rows if row["open"]],
        "notes": notes,
    }


def _placed(state: dict, name: str, count: Count, stamp: float) -> tuple[dict, bool]:
    row = _row(state, name)
    passed = bool(row["exam"].get("passed"))
    rung, shrank = _keep(row, derived(count, passed), stamp)
    placed = {
        "track": name,
        "rung": rung,
        "bar": bar(rung),
        "asked": count.asked,
        "deep": count.deep,
        "open": count.open_now,
        "kinds": list(count.kinds),
        "next_bar": _next_bar(rung),
        "remaining": remaining(count, rung, passed),
        "exam_passed": passed,
    }
    return (placed, shrank)


def _next_bar(rung: str) -> str:
    index = RUNGS.index(rung) + 1
    return bar(RUNGS[index]) if index < len(RUNGS) else ""


def _notes(root: str, tally: dict[str, Count], homeless: int) -> list[str]:
    """못 본 것을 적는다. 조용히 자르면 "0건"과 "안 봤다"가 화면에서 같아진다."""
    notes = []
    if not tally:
        notes.append("성장 기록에 좌표가 붙은 물음이 없어서 트랙을 하나도 못 만들었어요 — 없는 트랙은 안 지어내요")
    if homeless:
        notes.append(f"경로가 없는 물음 {homeless}건은 어느 트랙에도 못 넣었어요")
    notes.append(
        f"닫힌 물음은 최근 {tutor_growth.CLOSED_CAP}건까지만 남고 코드가 사라진 물음은 만료로 닫혀요 — "
        "그래서 셈은 줄 수 있고, 한 번 오른 단계는 그래도 안 내려요"
    )
    return notes


def summary(root: str, now: float | None = None) -> dict:
    """`place`의 다른 이름. 배정이 두 이름으로 왔을 때 부르는 쪽이 안 깨지게 둘 다 연다."""
    return place(root, now)


# ── 승급 시험 ──────────────────────────────────────────────────────


def pick_exam(root: str, track: str) -> tuple[str, str]:
    """이 트랙에서 오딘이 이미 답한 자리 하나를 골라 "어디서 부르나"를 묻는다. 반환 = (물음, 단위 이름).

    고른 자리와 물은 호출 자리를 `track.json`에 적는다 — `grade`는 단위 이름을 인자로 안 받으므로
    적어 두지 않으면 채점할 대상이 없고, 적어 두지 않으면 물은 뒤에 코드가 움직였을 때 같은 시험이
    다른 난이도가 된다. 고르는 순서는 경로 정렬이라 같은 트랙의 시험은 매번 같은 자리에서 나온다.

    부르는 자리가 `EXAM_MIN`에 못 미치는 단위는 건너뛴다. 후보가 없으면 빈 물음을 돌려준다.
    저장소 훑기는 단위 수와 무관하게 **한 번**이다(`surface.candidates`가 이름 여럿을 같이 받는다).
    """
    units = counts(root)[0].get(track, _EMPTY).units
    if not units:
        return ("", "")
    survey = surface.candidates(root, [unit for _, unit in units])
    for path, unit in units:
        sites = sorted(set(survey.get(unit.rsplit(".", 1)[-1], ())) - {path})
        if len(sites) >= EXAM_MIN:
            return _open_exam(root, track, path, unit, sites)
    return ("", "")


def _open_exam(root: str, track: str, path: str, unit: str, sites: list[str]) -> tuple[str, str]:
    asked = sites[:EXAM_CAP]
    state = load(root)
    _row(state, track)["exam"] = {
        "qualname": unit,
        "path": path,
        "sites": asked,
        "found": len(sites),
        "asked_at": time.time(),
    }
    save(root, state)
    return (_question(unit, path, len(asked), len(sites)), unit)


def _question(unit: str, path: str, asked: int, found: int) -> str:
    """물음 문장. 얼마나 물었는지와 무엇을 못 보는지를 같이 적는다 — 안 적으면 채점이 전지해 보인다."""
    return (
        f"`{unit}`을 부르는 자리를 아는 대로 적어 볼까요? 저장소 뿌리 기준 경로로요 — "
        f"정의된 곳(`{path}`)은 빼고 셉니다. 찾은 {found}곳 중 {asked}곳만 물어요. "
        "이름으로 찾은 후보라 동적 호출은 못 봐요 — 그래서 못 댄 것만 세고 더 댄 것은 안 깎아요."
    )


def grade(root: str, track: str, answer_text: str) -> tuple[bool, int, int, list[str]]:
    """시험을 채점한다. 반환 = (통과했는가, 맞힌 수, 정답 수, 못 댄 자리).

    대조 상대는 `pick_exam`이 물어 둔 자리다. 그 목록은 `surface.candidates`가 **이름으로** 찾은
    후보라 동적 호출·문자열 참조는 못 본다. 그래서 회수(못 댄 것)만 세고 후보 밖의 이름은 안
    깎는다. 다만 저장소에 없는 파일을 적으면 떨어진다 — 그건 회수가 아니라 지어낸 것이다.
    """
    state = load(root)
    exam = _row(state, track)["exam"]
    qualname = str(exam.get("qualname") or "")
    if not qualname:
        return (False, 0, 0, [])
    wanted = _asked_sites(root, exam)
    named = _named_paths(answer_text)
    matched = {site for site in wanted if any(_same_file(site, token) for token in named)}
    bogus = [t for t in named if not any(_same_file(site, t) for site in wanted) and not _exists(root, t)]
    passed = bool(wanted) and len(matched) * PASS_DEN >= len(wanted) * PASS_NUM and not bogus
    _record_exam(root, state, track, passed, len(matched), len(wanted))
    return (passed, len(matched), len(wanted), sorted(wanted - matched))


def _asked_sites(root: str, exam: dict) -> set[str]:
    """물어 둔 자리. 기록이 없으면 그때 다시 세되 상한은 같다 — 상한을 한 자리에만 적으면 갈린다."""
    stored = exam.get("sites")
    if isinstance(stored, list) and stored:
        return {str(site) for site in stored}
    return set(_call_sites(root, str(exam.get("qualname") or ""), str(exam.get("path") or ""))[:EXAM_CAP])


def _call_sites(root: str, qualname: str, defined_at: str) -> list[str]:
    """이름이 나오는 파일들. 정의된 파일은 뺀다 — 물음이 "부르는 자리"라서 정의는 답이 아니다."""
    hits = surface.candidates(root, [qualname], exclude=(defined_at,) if defined_at else ())
    return sorted({path for paths in hits.values() for path in paths})


def _named_paths(text: str) -> list[str]:
    found = (m.replace("\\", "/") for m in _PATH_TOKEN.findall(str(text or "")))
    return sorted({token[2:] if token.startswith("./") else token for token in found})


def _same_file(site: str, token: str) -> bool:
    """파일 이름만 적어도 맞힌 것으로 본다 — 전체 경로를 정확히 옮겨 적게 하면 아무도 안 친다."""
    return site == token or site.endswith("/" + token)


def _exists(root: str, token: str) -> bool:
    return os.path.exists(os.path.join(root, token))


def _record_exam(root: str, state: dict, track: str, passed: bool, hit: int, total: int) -> None:
    """시험 결과는 여기에만 적는다 — `growth.json`은 채점을 모르는 파일이라 한 글자도 안 쓴다.

    한 번 통과한 사실은 다시 떨어져도 안 지운다. 단계와 같은 이유다: 내려가는 값은 사람이 끈다.
    """
    exam = _row(state, track)["exam"]
    exam["passed"] = bool(exam.get("passed")) or passed
    exam["at"] = time.time()
    exam["hit"] = hit
    exam["total"] = total
    save(root, state)
