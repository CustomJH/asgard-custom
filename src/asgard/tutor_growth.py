"""튜터 성장 기록 — 물음이 사용자에게 닿은 **뒤에** 무슨 일이 있었는지를 세는 층.

지금까지 이 층은 물음을 놓기만 했다. 놓은 다음은 아무도 안 봤고, 그래서 튜터는 매 턴 처음 만난
사람에게 말하는 도구였다 — 어제 답한 물음을 오늘 같은 얼굴로 다시 놓고, 넉 달째 건너뛰는 종류를
넉 달째 같은 문장으로 놓는다. 같이 자라려면 세 가지가 있어야 한다: 무엇을 이미 가져갔는지(인지),
그래서 얼마나 말을 줄일지(조절), 안 가져간 것을 언제 다시 꺼낼지(재방문).

근거는 바깥에서 왔다. ① 안내는 **줄어쓰는 것이 목표**다 — 학습자 수준 밖의 비계(scaffold)는
이해를 돕는 게 아니라 방해한다(2508.06583, 인지 상태를 못 읽는 튜터의 대표 실패형이 "모두에게
같은 말"이다). ② 되짚기의 효과는 **인출**에서 나오고 인출은 간격을 둘 때 남는다 — 한 번 놓고
끝난 물음은 놓지 않은 것과 측정상 같다. ③ 답을 안 받으면 아무것도 못 잰다 — 설명 관문 실험에서
"코드는 받았지만 못 고치는" 격차 38%p는 사람이 **말로 옮겨 봤는가**에서 갈렸다(2602.20206).
그 실험은 막아서 받아냈고 우리는 안 막는다(계약 ②) — 대신 안 답한 것을 없던 일로 치지 않는다.

계약 다섯 줄:

  ① **맞았는지는 안 센다. 답했는지만 센다.** 채점하려면 의도를 알아야 하는데 의도는 사용자에게만
     있다. 틀린 채점 한 번이면 사람은 이 층을 끄고, 끈 층은 두 번 다시 안 켜진다.
  ② 안 답한 물음은 사라지지 않는다. 래치는 "지금 다시 안 묻는다"이지 "없던 일"이 아니다 —
     간격을 두고 돌아오되 **코드가 아직 거기 있을 때만**. 사라진 코드의 물음은 만료로 적는다.
  ③ 답이 쌓인 종류는 조용해진다. 사라지지는 않는다 — "0건"과 "접었다"는 다른 사실이고, 둘을
     같은 화면으로 만들면 이 도구가 거짓말을 하는 것이다.
  ④ 계속 건너뛰는 종류는 **더 크게 말하지 않는다.** 각도를 바꾸고, 그래도 안 되면 스스로 낮춘다.
     낮춘 사실은 기록에 남겨 화면에 넣는다 — 조용히 끄면 사용자는 자기가 뭘 껐는지도 모른다.
  ⑤ 기록은 관문이 아니다. 지워도 깨져도 코드는 그대로 간다. 모든 읽기는 fail-open.

스코프는 **프로젝트**다(`.asgard/tutor/growth.json`). 물음의 좌표가 이 저장소의 경로·단위라서
그렇다 — 다른 저장소로 들고 가면 좌표가 전부 죽는다. 종류별 통계만 개인 층으로 올릴 여지는 있고,
그건 여기 스키마를 안 바꾸고도 나중에 얹을 수 있다(topics는 좌표를 안 쓴다).
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass

from .io_files import read_json, write_json

GROWTH_REL = os.path.join(".asgard", "tutor", "growth.json")
VERSION = 1
DAY = 86400.0
# 재방문 사다리 (일). 답이 없으면 간격을 벌린다 — 같은 간격으로 계속 놓으면 그건 재방문이 아니라
# 잔소리다. 사다리 끝까지 가고도 답이 없으면 만료시킨다(계약 ④ — 다섯 번째는 묻지 않는다).
RUNGS = (1.0, 3.0, 7.0, 21.0)
CLOSED_CAP = 300  # 닫힌 물음 보존 상한 — 최신 우선. 기록이 커져 못 읽게 되면 안 읽는 것과 같다
OWNED_AT = 3  # 이 종류를 몇 번 답하면 "당신 것"으로 보는가
QUIET_AT = 4  # 답 없이 몇 번 건너뛰면 탐침을 스스로 낮추는가
THIN_CHARS = 12  # 이보다 짧은 답은 기록은 되지만 안내를 줄이지 않는다 (아래 _depth 주석)
SAID_CHARS = 300  # 남기는 답 본문 길이 — 되돌려 줄 때 한두 줄이면 충분하고, 길면 아무도 안 읽는다

# 답이 아닌 답. 판정이 아니라 **길이와 상투구**만 본다 — 내용을 판정하기 시작하면 계약 ①이 깨진다.
_FILLER = re.compile(
    r"^(ok|okay|yes|no|done|fine|good|later|n/?a|-|\.|네|넵|응|어|음|확인|알겠|알았|나중에|패스|스킵|모름|몰라)"
    r"[.!\s]*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Revisit:
    """돌아온 물음 하나 — 처음 놓았을 때의 좌표와 문장을 그대로 들고 온다.

    `unit`은 화면에 찍는 자리고 `key`는 이름을 만드는 자리다. 둘이 갈리는 물음이 있다(의존·표식은
    `unit`이 비어 있다) — 다시 실을 때 `key`를 안 들고 가면 같은 물음이 새 이름으로 다시 열린다.
    """

    cid: str
    kind: str
    path: str
    unit: str
    ask: str
    asks: int
    opened: float
    key: str = ""

    @property
    def where(self) -> str:
        return f"{self.path}" + (f" {self.unit}" if self.unit else "")

    def days(self, now: float) -> int:
        return max(0, int((now - self.opened) // DAY))


# ── 좌표 ───────────────────────────────────────────────────────────


def cid(kind: str, path: str, unit: str = "") -> str:
    """물음 하나의 안정된 이름. **줄 번호는 안 넣는다** — 위에서 함수 하나가 길어지면 아래 물음이
    전부 새것이 되고, 그러면 어제 답한 것을 오늘 다시 묻게 된다(래칫과 같은 이유)."""
    raw = f"{kind}|{path}|{unit}".encode()
    return hashlib.sha256(raw).hexdigest()[:8]


# ── 기록 입출력 ────────────────────────────────────────────────────


def _path(root: str) -> str:
    return os.path.join(root, GROWTH_REL)


def load(root: str) -> dict:
    """없거나 깨졌으면 빈 기록. 기록 손상은 사고의 흔적이지 사용자의 잘못이 아니다(계약 ⑤)."""
    data = read_json(_path(root), None)
    if not isinstance(data, dict):
        return {"version": VERSION, "topics": {}, "open": {}, "closed": []}
    return {
        "version": int(data.get("version") or VERSION),
        "topics": data.get("topics") if isinstance(data.get("topics"), dict) else {},
        "open": data.get("open") if isinstance(data.get("open"), dict) else {},
        "closed": data.get("closed") if isinstance(data.get("closed"), list) else [],
    }


def save(root: str, data: dict) -> bool:
    """못 써도 예외를 올리지 않는다 — 기록 실패가 되짚기를 막으면 관문이 된다(계약 ⑤)."""
    data["closed"] = list(data.get("closed") or [])[-CLOSED_CAP:]
    try:
        write_json(_path(root), data)
        return True
    except OSError:
        return False


def _topic(data: dict, kind: str) -> dict:
    row = data["topics"].get(kind)
    if not isinstance(row, dict):
        row = {"asked": 0, "answered": 0, "deep": 0, "skipped": 0, "dismissed": 0}
        data["topics"][kind] = row
    for key in ("asked", "answered", "deep", "skipped", "dismissed"):
        row[key] = int(row.get(key) or 0)
    return row


# ── 물음을 놓았다 ──────────────────────────────────────────────────


def note_asked(root: str, points: object, now: float | None = None) -> dict[str, str]:
    """놓은 물음을 기록한다. 반환 = cid → "new" | "again" | "waiting".

    **같은 호출을 두 번 해도 두 번 세지 않는다.** 이미 열려 있고 아직 때가 안 된 물음은
    "waiting"으로 지나간다 — 훅과 네이티브 루프가 같은 턴에 각자 판정을 돌려도 숫자가 부풀지 않아야 한다.
    다시 셀 자격은 **때가 됐을 때**뿐이고, 그때 비로소 직전 회차가 "건너뛴 것"으로 확정된다.
    """
    stamp = time.time() if now is None else now
    rows = [p for p in _iter_points(points)]
    if not rows:
        return {}
    data = load(root)
    out: dict[str, str] = {}
    for kind, path, unit, mark, ask in rows:
        key = cid(kind, path, mark)
        entry = data["open"].get(key)
        if not isinstance(entry, dict):
            data["open"][key] = {
                "kind": kind,
                "path": path,
                "unit": unit,
                "key": mark,
                "ask": ask,
                "asks": 1,
                "opened": stamp,
                "due": stamp + RUNGS[0] * DAY,
                "stage": 0,
            }
            topic = _topic(data, kind)
            topic["asked"] += 1
            topic.setdefault("first", stamp)
            topic["last"] = stamp
            out[key] = "new"
            continue
        if stamp < float(entry.get("due") or 0):
            out[key] = "waiting"
            continue
        stage = int(entry.get("stage") or 0) + 1
        entry["asks"] = int(entry.get("asks") or 1) + 1
        entry["ask"] = ask  # 각도가 바뀐 문장을 그대로 들고 간다 — 다음 화면이 이 문장을 쓴다
        entry["stage"] = stage
        entry["due"] = stamp + RUNGS[min(stage, len(RUNGS) - 1)] * DAY
        topic = _topic(data, kind)
        topic["asked"] += 1
        topic["skipped"] += 1  # 때가 되도록 답이 없었다 = 직전 회차는 건너뛴 것
        topic["last"] = stamp
        if stage >= len(RUNGS):
            _close(data, key, entry, "expired", stamp)
            out[key] = "expired"
            continue
        out[key] = "again"
    save(root, data)
    return out


def _iter_points(points: object):
    """Checkpoint 든 dict 든 같은 다섯 칸으로 읽는다 — 훅은 JSON을, 네이티브는 객체를 넘긴다.

    네 번째 칸이 이름을 만드는 구분자다. 없으면 `unit`이 그 일을 한다 — 대부분의 물음은 단위
    이름만으로 유일하고, 안 그런 두 종류(의존·표식)만 자기 구분자를 들고 온다.
    """
    if not isinstance(points, (list, tuple)):
        return
    for point in points:
        if isinstance(point, dict):
            kind, path = str(point.get("kind") or ""), str(point.get("path") or "")
            unit, ask = str(point.get("unit") or ""), str(point.get("ask") or "")
            mark = str(point.get("key") or "")
        else:
            kind, path = str(getattr(point, "kind", "")), str(getattr(point, "path", ""))
            unit, ask = str(getattr(point, "unit", "")), str(getattr(point, "ask", ""))
            mark = str(getattr(point, "key", "") or "")
        if kind and path:
            yield (kind, path, unit, mark or unit, ask)


def _close(data: dict, key: str, entry: dict, reason: str, stamp: float, depth: str = "", said: str = "") -> None:
    """닫힌 물음을 **답 본문까지** 남긴다.

    본문을 안 남기면 사용자가 적은 답은 그 자리에서 죽는다 — 그러면 이 층은 사람만 자라게 하고
    자기는 그대로다. 여기 남은 문장이 나중에 같은 자리를 다시 열 때 "그때 당신은 이렇게 답했다"로
    돌아간다(`recall`). 길이를 자르는 이유는 하나뿐이다: 기록이 커져 못 읽게 되면 안 읽는 것과 같다.
    """
    data["open"].pop(key, None)
    data["closed"].append(
        {
            "cid": key,
            "kind": entry.get("kind", ""),
            "path": entry.get("path", ""),
            "unit": entry.get("unit", ""),
            "key": entry.get("key", ""),
            "ask": entry.get("ask", ""),
            "asks": int(entry.get("asks") or 1),
            "at": stamp,
            "reason": reason,
            "depth": depth,
            "said": " ".join(str(said or "").split())[:SAID_CHARS],
        }
    )


# ── 답이 왔다 ──────────────────────────────────────────────────────


def answer(root: str, key: str, text: str, now: float | None = None) -> tuple[bool, str]:
    """물음 하나를 답으로 닫는다. 반환 = (닫았는가, 사람이 읽을 한 줄).

    **답의 옳고 그름은 안 본다**(계약 ①). 보는 것은 하나뿐이다 — 답의 자리에 실제로 무언가를
    옮겨 적었는가. 그마저 안 보면 `ok` 세 글자가 "이 종류는 이제 당신 것"이 되고, 그러면 조절
    (fading)이 근거를 잃는다.
    """
    stamp = time.time() if now is None else now
    data = load(root)
    found = _resolve(data, key)
    if found is None:
        return (False, f"열린 물음 중에 `{key}`로 시작하는 게 없어요")
    full, entry = found
    depth = _depth(text)
    topic = _topic(data, entry.get("kind", ""))
    topic["answered"] += 1
    if depth == "full":
        topic["deep"] += 1
        topic["last_answered"] = stamp
    _close(data, full, entry, "answered", stamp, depth, text)
    save(root, data)
    if depth == "thin":
        return (True, "적어 뒀어요. 다만 한 줄짜리 답은 안내를 줄이지 않아요 — 줄이는 근거로는 안 써요")
    return (True, "적어 뒀어요. 이 종류의 안내가 다음부터 한 단계 줄어들어요")


def dismiss(root: str, key: str, reason: str = "", now: float | None = None) -> tuple[bool, str]:
    """오탐으로 물음을 닫는다. 이건 사용자가 튜터를 고치는 통로다 — 같은 종류가 계속 오탐으로
    닫히면 그 탐침은 스스로 낮아진다(계약 ④). 오탐을 답으로 세면 조절이 거꾸로 간다.

    `key` 는 셋 중 하나다: 표식(cid) 앞자리, `all`, 또는 경로. 뒤의 둘이 뒤에 생긴 이유가 이
    층의 실측이다 — 한 자리에 물음 열두 건이 쌓이면 출구가 표식 여덟 자짜리 명령 열두 번뿐이고,
    그러면 아무도 안 치운다. 안 치우는 목록은 다음 턴부터 읽히지도 않는다 (26-08-11 오딘 지적).
    치우는 값이 쌓이는 값보다 싸야 이 층이 산다.
    """
    stamp = time.time() if now is None else now
    data = load(root)
    bulk = _bulk(data, key)
    if bulk is not None:
        return _dismiss_all(root, data, bulk, key, reason, stamp)
    found = _resolve(data, key)
    if found is None:
        return (False, f"열린 물음 중에 `{key}`로 시작하는 게 없어요")
    full, entry = found
    _topic(data, entry.get("kind", ""))["dismissed"] += 1
    _close(data, full, entry, "dismissed", stamp, "", reason)
    save(root, data)
    return (True, "오탐으로 닫았어요. 같은 종류가 반복되면 이 탐침을 스스로 낮춰요")


def _bulk(data: dict, key: str) -> list[str] | None:
    """묶음 닫기 대상 — `all` 이면 전부, 경로면 그 파일. 표식 갈래면 None (한 건 닫기로 넘긴다).

    표식과 경로를 가르는 것은 글자 모양이 아니라 **무엇에 맞았는가**다. 표식은 16진 여덟 자라
    경로와 겹칠 수 없고, 경로는 열려 있는 물음의 `path` 와 통째로 같을 때만 경로로 읽는다 —
    오타 하나가 열두 건을 통째로 닫으면 그건 출구가 아니라 함정이다.
    """
    raw = str(key or "").strip()
    rows = [(k, e) for k, e in data["open"].items() if isinstance(e, dict)]
    if raw.lower() == "all":
        return [k for k, _ in rows]
    wanted = raw.replace(os.sep, "/")
    hits = [k for k, e in rows if str(e.get("path") or "").replace(os.sep, "/") == wanted]
    return hits or None


def _dismiss_all(root: str, data: dict, keys: list[str], key: str, reason: str, stamp: float) -> tuple[bool, str]:
    if not keys:
        return (False, f"`{key}` 에 열린 물음이 없어요")
    for full in keys:
        entry = data["open"].get(full)
        if not isinstance(entry, dict):
            continue
        _topic(data, entry.get("kind", ""))["dismissed"] += 1
        _close(data, full, entry, "dismissed", stamp, "", reason)
    save(root, data)
    where = "이 저장소" if str(key).strip().lower() == "all" else f"`{key}`"
    return (True, f"{where}의 열린 물음 {len(keys)}건을 오탐으로 닫았어요. 반복되는 종류는 탐침이 스스로 낮아져요")


def _resolve(data: dict, key: str) -> tuple[str, dict] | None:
    """cid 앞자리만 쳐도 찾는다 — 여덟 글자를 정확히 옮겨 적게 하면 아무도 안 답한다."""
    raw = str(key or "").strip().lower()
    if not raw:
        return None
    hits = [(k, v) for k, v in data["open"].items() if k.startswith(raw) and isinstance(v, dict)]
    return hits[0] if len(hits) == 1 else None


def _depth(text: str) -> str:
    """`thin` = 답의 자리를 채우긴 했으나 옮겨 적은 것이 없다. 판정이 아니라 계측이다."""
    body = " ".join(str(text or "").split())
    if not body or _FILLER.match(body) or len(body) < THIN_CHARS:
        return "thin"
    return "full"


# ── 조절 (얼마나 말할 것인가) ──────────────────────────────────────


def level(data: dict, kind: str) -> int:
    """0 처음 · 1 봤다 · 2 답해 봤다 · 3이 종류는 당신 것이다.

    올라가는 근거는 **깊은 답**뿐이다(`deep`). 짧은 답도 답으로 세지만 조절의 근거로는 안 쓴다 —
    그러지 않으면 `ok`를 세 번 쳐서 안내를 끌 수 있고, 그건 사용자가 자기를 속이는 통로다.
    """
    row = data["topics"].get(kind)
    if not isinstance(row, dict):
        return 0
    deep = int(row.get("deep") or 0)
    if deep >= OWNED_AT:
        return 3
    if deep >= 1:
        return 2
    return 1 if int(row.get("asked") or 0) > 0 else 0


def form(data: dict, kind: str) -> str:
    """이 종류를 이번 화면에 어떤 크기로 실을 것인가 — `full` · `ask` · `fold`.

    - `full`  사실 + 왜 당신 눈이 필요한가 + 물음 (처음 만나는 종류)
    - `ask`   사실 + 물음 (왜가 이미 전달된 종류 — 세 번째로 같은 설명을 놓으면 그건 소음이다)
    - `fold`  한 줄 접기 — 이미 당신 것이 된 종류
    - `quiet` 한 줄 접기 — 튜터가 **스스로 낮춘** 종류

    접힌 둘을 한 이름으로 부르지 않는 이유: "당신이 잘 아는 것"과 "내가 못 닿은 것"은 화면에서
    같은 줄로 보이면 안 된다. 앞의 것은 성과고 뒤의 것은 이 층의 실패다.
    """
    if quiet_reason(data, kind):
        return "quiet"
    return ("full", "full", "ask", "fold")[level(data, kind)]


def quiet_reason(data: dict, kind: str) -> str:
    """이 탐침을 스스로 낮췄는가, 낮췄으면 왜인가. 빈 문자열이면 안 낮춘 것이다.

    두 갈래뿐이고 둘 다 사용자가 만든 사실이다 — 계속 오탐으로 닫혔거나, 계속 건너뛰어졌거나.
    낮춘다는 것은 **안 묻는다**가 아니라 **한 줄로 접는다**이다. 안 묻기 시작하면 이 층은
    자기가 못 본 것을 화면에서 지우는 도구가 된다(계약 ③).
    """
    row = data["topics"].get(kind)
    if not isinstance(row, dict):
        return ""
    dismissed, skipped, deep = (int(row.get(k) or 0) for k in ("dismissed", "skipped", "deep"))
    if dismissed >= 3:
        return f"오탐으로 {dismissed}번 닫혔어요 — 이 저장소에는 잘 안 맞는 탐침으로 보고 접었어요"
    if skipped >= QUIET_AT and deep == 0:
        return f"{skipped}번 물었는데 한 번도 답이 없었어요 — 각도를 바꿔도 안 닿아서 접었어요"
    return ""


def angle(kind: str, asks: int) -> int:
    """같은 물음을 다시 놓을 때 몇 번째 각도로 놓을 것인가.

    같은 문장을 네 번째로 놓는 것은 재방문이 아니라 반복이다. 인출이 실패한 자리에서 같은 설명을
    되풀이하지 말고 각도를 바꾼다 — 물음의 문장은 `tutor.ANGLES`가 갖고, 여기서는 몇 번째인지만
    센다(문장과 셈을 한 자리에 두면 문장을 고칠 때마다 셈이 바뀐다).
    """
    return max(0, int(asks) - 1)


# ── 재방문 ─────────────────────────────────────────────────────────


def due(root: str, now: float | None = None, cap: int = 3) -> list[Revisit]:
    """때가 된 물음 — 오래 기다린 것부터. **코드가 아직 있는지는 여기서 안 본다.**

    좌표가 살아 있는지는 나무를 봐야 아는 사실이고 이 모듈은 기록만 본다. 확인은 호출부
    (`tutor.revisits`)의 몫이고, 죽은 좌표는 거기서 `expire`로 닫힌다.
    """
    stamp = time.time() if now is None else now
    data = load(root)
    rows = [
        Revisit(
            key,
            str(entry.get("kind") or ""),
            str(entry.get("path") or ""),
            str(entry.get("unit") or ""),
            str(entry.get("ask") or ""),
            int(entry.get("asks") or 1),
            float(entry.get("opened") or stamp),
            str(entry.get("key") or ""),
        )
        for key, entry in data["open"].items()
        if isinstance(entry, dict) and stamp >= float(entry.get("due") or 0)
    ]
    rows.sort(key=lambda r: r.opened)
    return rows[:cap]


def expire(root: str, keys: object, reason: str = "gone", now: float | None = None) -> int:
    """좌표가 사라진 물음을 닫는다. 반환 = 닫은 수.

    코드가 없어졌으면 물음도 없어져야 한다 — 없는 자리를 열라고 세 번 말하면 사용자는 이 카드를
    통째로 안 믿게 된다. 다만 **조용히 지우지는 않는다**: 만료도 닫힌 기록에 이유와 함께 남는다.
    """
    stamp = time.time() if now is None else now
    wanted = {str(k) for k in keys} if isinstance(keys, (list, tuple, set, frozenset)) else set()
    if not wanted:
        return 0
    data = load(root)
    hit = 0
    for key in list(data["open"]):
        if key in wanted and isinstance(data["open"].get(key), dict):
            _close(data, key, data["open"][key], reason, stamp)
            hit += 1
    if hit:
        save(root, data)
    return hit


# ── 성장 화면 재료 ─────────────────────────────────────────────────


def summary(root: str, now: float | None = None) -> dict:
    """`asgard tutor --progress`가 그릴 재료. 화면 문장은 여기서 안 만든다.

    이 화면 하나가 이 층의 산출물이다 — 튜터가 사람에게 남긴 것이 무엇인지 볼 수 있는 유일한
    자리이므로, 좋아 보이는 숫자만 넣지 않는다. 건너뛴 수와 스스로 낮춘 탐침을 같은 화면에
    올린다(계약 ④).
    """
    stamp = time.time() if now is None else now
    data = load(root)
    topics = []
    for kind, row in sorted(data["topics"].items()):
        if not isinstance(row, dict):
            continue
        topics.append(
            {
                "kind": kind,
                "level": level(data, kind),
                "asked": int(row.get("asked") or 0),
                "answered": int(row.get("answered") or 0),
                "deep": int(row.get("deep") or 0),
                "skipped": int(row.get("skipped") or 0),
                "dismissed": int(row.get("dismissed") or 0),
                "quiet": quiet_reason(data, kind),
                "last": float(row.get("last") or 0),
            }
        )
    topics.sort(key=lambda t: (-t["level"], -t["asked"], t["kind"]))
    closed = [c for c in data["closed"] if isinstance(c, dict)]
    return {
        "topics": topics,
        "open": len(data["open"]),
        "due": len(due(root, stamp, cap=10_000)),
        "answered": sum(1 for c in closed if c.get("reason") == "answered"),
        "deep": sum(1 for c in closed if c.get("reason") == "answered" and c.get("depth") == "full"),
        "dismissed": sum(1 for c in closed if c.get("reason") == "dismissed"),
        "expired": sum(1 for c in closed if c.get("reason") in ("expired", "gone")),
        "quiet": {t["kind"]: t["quiet"] for t in topics if t["quiet"]},
        "recent": closed[-8:][::-1],
    }


@dataclass(frozen=True)
class Said:
    """당신이 예전에 이 자리에 적어 둔 답 하나 — 기계의 판정이 아니라 **그때 당신의 문장**이다."""

    cid: str
    kind: str
    path: str
    unit: str
    ask: str
    said: str
    at: float
    dismissed: bool = False

    @property
    def where(self) -> str:
        return f"{self.path}" + (f" {self.unit}" if self.unit else "")

    def days(self, now: float) -> int:
        return max(0, int((now - self.at) // DAY))


def recall(root: str, paths: object, cap: int = 2, now: float | None = None) -> list[Said]:
    """이 자리에 대해 **당신이 예전에 한 답**. 최근 것부터.

    지금까지 답은 닫히면 끝이었다. 그러면 이 층은 사람만 자라게 하고 자기는 그대로다 — 6주 전에
    "여긴 상류가 죽어도 화면이 버텨야 해서 삼킨다"고 적어 둔 사람이, 같은 자리에서 같은 물음을
    다시 받는다. 그건 같이 자라는 게 아니라 매번 처음부터 다시 만나는 것이다.

    **되돌려 줄 뿐 판정하지 않는다.** 그때의 답이 지금도 맞는지는 코드가 그 사이 바뀌었을 수
    있으므로 기계가 못 정한다 — 그래서 날짜를 붙여 그대로 내놓고, 맞는지는 사람이 본다.
    """
    stamp = time.time() if now is None else now
    wanted = {str(p) for p in paths} if isinstance(paths, (list, tuple, set, frozenset)) else set()
    if not wanted:
        return []
    rows = [
        Said(
            str(row.get("cid") or ""),
            str(row.get("kind") or ""),
            str(row.get("path") or ""),
            str(row.get("unit") or ""),
            str(row.get("ask") or ""),
            str(row.get("said") or ""),
            float(row.get("at") or stamp),
            row.get("reason") == "dismissed",
        )
        for row in load(root)["closed"]
        if isinstance(row, dict)
        and row.get("path") in wanted
        and row.get("said")
        and row.get("reason") in ("answered", "dismissed")
    ]
    rows.sort(key=lambda r: -r.at)
    return rows[:cap]


def places(root: str) -> dict[str, set[str]]:
    """이 기록이 아는 자리 전부 — 경로 → 그 자리에서 물었던 단위 이름들. 열린 것과 닫힌 것 **둘 다**.

    닫힌 것을 빼면 안 되는 이유가 있다: **다 답한 자리야말로 답이 있는 자리다.** 열린 물음만 보고
    자리를 고르면, 마지막 물음을 답한 순간 그 자리의 회상이 통째로 사라진다(실측 — 테스트가 잡았다).
    """
    data = load(root)
    out: dict[str, set[str]] = {}
    for row in list(data["open"].values()) + list(data["closed"]):
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "")
        if path:
            out.setdefault(path, set()).add(str(row.get("unit") or ""))
    return out


def open_points(root: str) -> list[Revisit]:
    """열린 물음 전부 (때가 됐든 아니든) — 브리핑이 "이 자리에 남은 빚"을 세는 재료."""
    data = load(root)
    return [
        Revisit(
            key,
            str(e.get("kind") or ""),
            str(e.get("path") or ""),
            str(e.get("unit") or ""),
            str(e.get("ask") or ""),
            int(e.get("asks") or 1),
            float(e.get("opened") or 0.0),
            str(e.get("key") or ""),
        )
        for key, e in data["open"].items()
        if isinstance(e, dict)
    ]
