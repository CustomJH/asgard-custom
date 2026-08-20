"""훅과 스튜디오 창이 읽는 JSON. 칸은 더하기만 한다."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from ... import tutor
from .engines import _as_dict, _rationale_dict
from .labels import _point_counts, _shown_rows


def _payload(
    lesson: tutor.Lesson,
    rows: list[tuple[tutor.Checkpoint, str]],
    back: list,
    exp: Any = None,
    report_rel: str = "",
    limit: int = 1,
    why: Any = None,
    quiz: bool = True,
    track: Any = None,
) -> str:
    """훅과 화면이 같은 판정을 쓰도록 조절 결과까지 넣는다 — 판정기가 둘이면 반드시 어긋난다.

    칸은 더하기만 한다. 훅(`hooks/tutor_note.py`)과 스튜디오 창이 이 이름들을 그대로 읽으므로
    하나를 지우거나 고쳐 부르면 그쪽 화면이 조용히 빈다.
    """
    shown = _shown_rows(rows, limit)
    return json.dumps(
        {
            "base": lesson.base,
            "files": [asdict(f) for f in lesson.files],
            "added": lesson.touched[0],
            "removed": lesson.touched[1],
            "checkpoints": [{**asdict(p), "weight": p.weight, "cid": p.cid, "form": form} for p, form in rows],
            # 전체 후보는 기계 소비자에게 남기고, Stop 훅에는 사람이 실제로 볼 목록을 따로 준다.
            # 둘을 섞으면 화면에 없던 후보까지 질문·건너뜀으로 기록된다.
            "shown_checkpoints": [{**asdict(p), "weight": p.weight, "cid": p.cid, "form": form} for p, form in shown],
            "checkpoint_summary": _point_counts(rows),
            "revisits": [
                {"cid": r.cid, "kind": r.kind, "path": r.path, "unit": r.unit, "ask": r.ask, "asks": r.asks}
                for r in back
            ],
            "undetermined": [{"path": p, "why": w} for p, w in lesson.undetermined],
            "mandate": list(lesson.mandate),
            # 훅이 카드 마지막 줄에 적을 자리. 안 썼으면 빈 문자열이다 — 훅이 제 상수로 되메우게.
            "report": report_rel,
            # 설명 엔진(`tutor_teach`)이 아직 없거나 죽으면 null. 표면이 엔진보다 먼저 배송된다.
            "explain": _as_dict(exp),
            # 되짚기가 사람에게 무엇을 요구하는가. 훅은 이 칸으로 카드 모양을 고른다 — 훅이 제
            # 설정을 다시 읽으면 같은 저장소에서 화면 둘이 갈린다.
            "mode": "quiz" if quiz else "explain",
            # "왜 이렇게 했는가" — 퀘스트 기록에서 온 사실. quiz 모드거나 기록이 없으면 null.
            "rationale": _rationale_dict(why),
            # 지금 어느 영역까지 갔는가(`tutor_track.place`). 훅이 카드 첫 줄에 단계와 다음 기준을
            # 적는 자리다. 엔진이 없거나 던지면 null이고, 그러면 훅은 오늘 카드를 종전대로 그린다.
            "track": track,
        },
        ensure_ascii=False,
        indent=2,
    )
