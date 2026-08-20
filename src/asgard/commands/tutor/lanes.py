"""기본 갈래를 뺀 나머지 명령 갈래 — 성장·트랙·승급 시험·부채·서사·팁·예상·설명·향하는 곳·물음 닫기·브리핑.

부채 · 되짚기 서사 · 도중 팁 · 기대 사전 등록 넷은 같은 자리에서 왔다. 되짚기는 지금까지
**턴 시작**(brief)과 **턴 끝**(note) 두 시점에만 닿았는데, 사람이 실제로 항복하는 자리는 그
사이다 — 다섯 번째 변경에서, 검토가 얕아진 채로, 읽기 전에 닫는다. 그래서 세는 층(`--debt`)과
도중에 한 번 말하는 층(`--tip`)을 나눠 둔다.

`--expect`는 방향이 반대인 하나다. 나머지 셋은 이미 벌어진 일을 재지만 이것은 **벌어지기 전에**
사람의 견해를 먼저 받아 둔다. 근거는 하나다: 모델의 답을 본 뒤에 만든 견해는 그 답의 함수라
대조에 못 쓴다. 먼저 적어 둔 한 줄만이 나중에 "내가 예상한 것과 다르다"를 만들 수 있다.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from ... import tutor, tutor_growth, ui
from .engines import _as_dict, _engine, _explanation, _learned
from .labels import _EXAM_BLIND, _KIND, _LADDER, _LEVEL_MARK, _SIGNAL_LABEL, _TRACK_MARK
from .screen import _emit_explain, _emit_said


def _run_progress(root: str, json_out: bool) -> int:
    data = tutor_growth.summary(root)
    if json_out:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    ui.head("tutor · 같이 자란 기록")
    if not data["topics"]:
        ui.ok("아직 기록이 없어요 — 되짚기 카드가 한 번도 안 나왔거나, 이 저장소가 처음이거나요")
        ui.done()
        return 0
    ui.phase(f"가져간 것 — 답한 물음 {data['answered']}건 (그중 옮겨 적은 답 {data['deep']}건)")
    for row in data["topics"]:
        mark = _LADDER[row["level"]]
        tail = "  ← 접힘" if row["quiet"] else ""
        ui.step(f"{mark} {_KIND.get(row['kind'], row['kind'])}")
        ui.step(ui.dim(f"      물음 {row['asked']} · 답 {row['answered']} · 건너뜀 {row['skipped']}{tail}"))
    ui.phase(f"열린 물음 {data['open']}건 (그중 지금 때가 된 것 {data['due']}건)")
    if data["due"]:
        ui.step(ui.dim("    다음 되짚기 카드에 각도를 바꿔 다시 실어 드려요"))
    if data["quiet"]:
        ui.phase(f"튜터가 스스로 낮춘 종류 — {len(data['quiet'])}건이에요")
        for kind, why in sorted(data["quiet"].items()):
            ui.warn(f"{_KIND.get(kind, kind)}")
            ui.step(ui.dim(f"    {why}"))
        ui.step(ui.dim("    낮췄다고 안 묻는 게 아니라 한 줄로 접은 거예요 — 사실은 화면에 계속 남아요"))
    if data["expired"]:
        ui.step(ui.dim(f"    만료 {data['expired']}건 — 코드가 사라졌거나 끝까지 답이 없던 물음"))
    _emit_said(data)
    ui.done()
    return 0


def _placement(root: str) -> dict | None:
    """트랙 배치 하나. 엔진이 없거나 던지면 None — 침묵이지 실패가 아니다(튜터 계약 ②).

    `--track` 화면과 훅이 읽는 `track` 칸이 같은 자리에서 이걸 부른다. 부르는 자리가 둘이어도
    판정하는 자리는 여기 하나다 — 배치를 두 곳에서 만들면 카드 줄과 화면이 갈린다.
    """
    engine = _engine("tutor_track")
    if engine is None:
        return None
    try:
        return engine.place(root)
    except Exception:
        return None


def _run_track(root: str, json_out: bool) -> int:
    """지금 어느 영역까지 갔는가 — 트랙마다 지금 단계, 다음 단계의 기준, 아직 모자란 것.

    `--progress`가 물음의 **종류**를 세는 화면이라면 이쪽은 사람이 **어느 영역까지 갔나**를 놓는다.
    문장은 전부 `tutor_track.place`가 완성해서 보낸다 — 단계 이름도 기준 문장도 여기서 다시 만들지
    않는다. 어휘 사본이 둘이면 언젠가 갈리고, 그때 두 화면이 같은 트랙을 다르게 부른다.
    """
    placed = _placement(root)
    if json_out:
        print(json.dumps(placed, ensure_ascii=False, indent=2))
        return 0
    ui.head("tutor · 지금 어디까지 왔나")
    if placed is None:
        # 두 사정을 갈라 적는다 — 엔진이 없는 것과 배치가 죽은 것은 다음에 할 일이 다르다
        # (`_run_explain`과 같은 계약).
        ui.ok("트랙을 재는 기능이 아직 없어요" if _engine("tutor_track") is None else "이번엔 배치를 못 했어요")
        ui.done()
        return 0
    mission = str(placed.get("mission") or "").strip()
    if mission:
        ui.phase(f"향하는 곳 — {mission}")
    rows = placed.get("tracks") or []
    if not rows:
        ui.ok("아직 트랙이 없어요 — 되짚기 물음에 좌표가 붙으면 그때 생겨요")
    active = {str(name) for name in placed.get("active") or ()}
    for row in rows:
        _emit_track(row, str(row.get("track") or "") in active)
    notes = placed.get("notes") or ()
    # 못 본 것은 트랙 아래가 아니라 제 절에 놓는다 — 같은 들여쓰기로 이어 붙이면 마지막 트랙의
    # 사정으로 읽힌다(튜터 계약 ③: 못 본 것이 화면에 있어야 "0건"이 "안 봤다"와 안 겹친다).
    if notes:
        ui.phase("이 셈이 못 보는 것")
    for note in notes:
        ui.step(ui.dim(f"    {note}"))
    ui.done()
    return 0


def _emit_track(row: dict, live: bool) -> None:
    """트랙 한 줄과 그 아래 세 조각. 기준(`next_bar`)을 빼면 사다리가 아니라 점수판이 된다."""
    ui.step(f"{_TRACK_MARK[int(live)]} {row.get('track') or '?'} — {row.get('rung') or '?'} ({row.get('bar') or ''})")
    ui.step(ui.dim(f"    물음 {row.get('asked', 0)}건 · 자기 문장으로 답한 것 {row.get('deep', 0)}건"))
    ahead = str(row.get("next_bar") or "").strip()
    left = str(row.get("remaining") or "").strip()
    if ahead:
        ui.step(ui.dim(f"    다음 칸 — {ahead}"))
    if left:
        ui.step(ui.dim(f"    아직 — {left}"))


def _run_exam(root: str, track: str, answer: str, json_out: bool) -> int:
    """승급 시험. 인자 없이 부르면 물음, `--answer`와 같이 부르면 채점.

    여기는 채점하는 유일한 자리이고 그래도 계약 ①과 안 부딪힌다 — 안 채점하기로 한 것은 매일
    놓이는 카드 물음이고, 이건 오딘이 직접 부르는 별개 표면이다. 결과는 `track.json`에만 남는다.
    """
    engine = _engine("tutor_track")
    if engine is None:
        if json_out:
            print(json.dumps({"track": track, "question": ""}, ensure_ascii=False, indent=2))
        else:
            ui.head("tutor · 승급 시험")
            ui.ok("시험을 낼 기능이 아직 없어요")
            ui.done()
        return 0
    if answer:
        return _emit_grade(engine, root, track, answer, json_out)
    return _emit_exam(engine, root, track, json_out)


def _emit_exam(engine: Any, root: str, track: str, json_out: bool) -> int:
    question, qualname = engine.pick_exam(root, track)
    if json_out:
        print(json.dumps({"track": track, "question": question, "unit": qualname}, ensure_ascii=False, indent=2))
        return 0
    ui.head(f"tutor · 승급 시험 — {track}")
    if not question:
        ui.ok(
            "이 트랙에는 아직 낼 시험이 없어요 — 자기 문장으로 답한 자리가 있어야 하고, "
            f"그 단위를 부르는 자리가 {engine.EXAM_MIN}곳 이상이어야 해요"
        )
        ui.done()
        return 0
    ui.step(question)
    ui.step(ui.dim(f'    답: `asgard tutor --exam {track} --answer "경로 하나 경로 둘 ..."`'))
    ui.done()
    return 0


def _emit_grade(engine: Any, root: str, track: str, answer: str, json_out: bool) -> int:
    passed, hit, total, missing = engine.grade(root, track, answer)
    if json_out:
        print(
            json.dumps(
                {"track": track, "passed": passed, "hit": hit, "total": total, "missing": missing},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    ui.head(f"tutor · 승급 시험 채점 — {track}")
    if not total:
        ui.ok("채점할 시험이 없어요 — `asgard tutor --exam <트랙>`으로 먼저 물음을 받으세요")
        ui.done()
        return 0
    (ui.ok if passed else ui.warn)(f"{'통과예요' if passed else '아직이에요'} — 물은 {total}곳 중 {hit}곳")
    for site in missing:
        ui.step(ui.dim(f"    못 댄 자리 — {site}"))
    # 회수를 채우고도 떨어지는 길은 하나뿐이다 — 저장소에 없는 이름을 적은 것. `grade`는 그 목록을
    # 안 돌려주므로(못 댄 자리만 돌려준다) 통과선을 엔진 상수로 되짚어 사정만 적는다.
    if not passed and hit * engine.PASS_DEN >= total * engine.PASS_NUM:
        ui.step(ui.dim("    회수는 채웠는데 저장소에 없는 이름이 섞였어요 — 그건 회수가 아니라 지어낸 자리예요"))
    ui.step(ui.dim(f"    찾은 자리 전부가 아니라 그중 최대 {engine.EXAM_CAP}곳만 물어요"))
    ui.step(ui.dim(f"    {_EXAM_BLIND}"))
    ui.done()
    return 0


def _run_debt(root: str, sid: str, json_out: bool) -> int:
    """지금 이 저장소에서 **읽지 않고 받고 있는** 자리. 막지 않는다 — 세어서 보여 줄 뿐이다."""
    debt = _engine("tutor_debt")
    if debt is None:
        if not json_out:
            ui.head("tutor · 부채")
            ui.ok("부채를 재는 기능이 아직 없어요")
            ui.done()
        return 0
    book = debt.ledger(root, sid)
    if json_out:
        print(
            json.dumps(
                {
                    "level": book.level,
                    "open_debt": book.open_debt,
                    "oldest_days": book.oldest_days,
                    "turns": book.turns,
                    "added": book.added,
                    "signals": [asdict(s) for s in book.signals],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    ui.head("tutor · 지금 어디서 받고만 있나")
    ui.phase(f"답 없는 물음 {book.open_debt}건 · 가장 오래된 것 {book.oldest_days}일 · 이 세션 {book.turns}턴")
    live = [s for s in book.signals if s.level > 0]
    if not live:
        ui.ok("항복 신호는 없어요 — 재는 다섯 갈래가 전부 조용해요")
        ui.done()
        return 0
    for signal in sorted(live, key=lambda s: -s.level):
        mark = _LEVEL_MARK[min(signal.level, len(_LEVEL_MARK) - 1)]
        (ui.warn if signal.level >= 2 else ui.step)(
            f"{mark} {_SIGNAL_LABEL.get(signal.name, signal.name)} — {signal.fact}"
        )
        ui.step(ui.dim(f"    {signal.why}"))
        ui.step(ui.dim(f"    잰 것: {signal.source}"))
    ui.step(ui.dim("    이건 관문이 아니에요 — 아무것도 막지 않고, 지금 어디에 서 있는지만 알려 드려요"))
    ui.done()
    return 0


def _run_recap(root: str, sid: str, span: str, json_out: bool, quiet: bool) -> int:
    """세션·하루·한 주의 서사. 통계(`--progress`)와 다른 화면인 이유는 묻는 것이 달라서다 —
    `--progress`는 "무엇을 가져갔나"이고 이건 "방금 무슨 일이 있었나"다."""
    body = tutor.recap(root, sid, span) if hasattr(tutor, "recap") else ""
    if json_out:
        print(json.dumps({"span": span, "recap": body}, ensure_ascii=False, indent=2))
        return 0
    if body:
        print(body)
        return 0
    if not quiet:
        ui.head("tutor · 되짚기")
        ui.ok("되짚을 게 없어요 — 이 구간에 물음도 답도 안 남았어요")
        ui.done()
    return 0


def _run_tip(root: str, sid: str, cap: int) -> int:
    """작업 **도중** 한 번. 대부분의 호출은 아무것도 안 찍는다 — 매번 말하면 배경 소음이 되고,
    배경 소음이 된 안내는 켜져 있어도 꺼진 것과 같다(`tutor.brief`가 이미 적어 둔 실측)."""
    rows = tutor.tips(root, sid, cap) if hasattr(tutor, "tips") else []
    for line in rows:
        print(line)
    return 0


def _run_expect(root: str, sid: str, text: str, json_out: bool) -> int:
    """에이전트를 돌리기 **전에** 당신의 예상을 한 줄로 받아 둔다.

    Osmani 의 첫 번째 대책이다: 답을 본 뒤에 만든 견해는 그 답의 함수라 대조에 못 쓴다. 먼저
    적어 둔 한 줄만이 나중에 "내가 생각한 것과 다르다"를 만들 수 있고, 그 차이가 유일하게
    사람이 읽었다는 증거다. 옳고 그름은 여기서도 안 본다(성장 기록 계약 ①).
    """
    debt = _engine("tutor_debt")
    body = " ".join(str(text or "").split())
    if debt is None:
        if not json_out:
            ui.head("tutor · 예상 적어 두기")
            ui.warn("예상을 적어 둘 기능이 아직 없어요")
            ui.done()
        return 0
    if not body:
        rows = debt.expectations(root, sid)
        if json_out:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        ui.head("tutor · 아직 안 맞춰 본 예상")
        if not rows:
            ui.ok('적어 두신 예상이 없어요 — `asgard tutor --expect "..."`로 한 줄 남겨 두세요')
            ui.done()
            return 0
        for row in rows:
            ui.step(f"[{row.get('key')}] {row.get('text')}")
        ui.step(ui.dim('    맞춰 보기: `asgard tutor --settle <표식> "실제로는 이랬다"`'))
        ui.done()
        return 0
    key = debt.expect(root, sid, body)
    if json_out:
        print(json.dumps({"key": key, "text": body}, ensure_ascii=False))
        return 0
    ui.head("tutor · 예상 적어 두기")
    ui.ok(f"적어 뒀어요 [{key}]")
    ui.step(ui.dim(f'    끝나고 나서 `asgard tutor --settle {key} "실제로는 이랬다"`로 맞춰 보세요'))
    ui.done()
    return 0


def _run_settle(root: str, key: str, verdict: str) -> int:
    """예상과 실제를 맞춰 본다. **누가 맞았는지는 안 적는다** — 적으면 채점이 되고, 채점하는
    순간 사람은 맞을 만한 예상만 적기 시작한다."""
    debt = _engine("tutor_debt")
    ui.head("tutor · 예상 맞춰 보기")
    if debt is None:
        ui.warn("예상을 맞춰 볼 기능이 아직 없어요")
        ui.done()
        return 0
    ok, message = debt.settle(root, key, verdict)
    (ui.ok if ok else ui.warn)(message)
    ui.done()
    return 0


# ── 설명 레인 ──────────────────────────────────────────────────────
#
# `--report`가 "당신이 답할 것"을 놓는다면 이쪽은 "이걸 읽으려면 어디부터 보나"를 놓는다. 두 축을
# 한 화면에 섞지 않는 이유는 계약이다: 설명이 물음의 답을 대신 적으면 사람이 답할 자리가 사라진다.


def _run_explain(root: str, base: str, paths: tuple[str, ...], depth: str, json_out: bool) -> int:
    exp = _explanation(root, base, paths, depth)
    if json_out:
        print(json.dumps(_as_dict(exp), ensure_ascii=False, indent=2))
        return 0
    ui.head("tutor · 이 변경을 어떻게 읽나")
    if exp is None:
        # 두 사정을 갈라 적는다 — 엔진이 없는 것과 이번 변경에서 못 만든 것은 다음에 할 일이 다르다.
        ui.ok(
            "설명을 만드는 기능이 아직 없어요" if _engine("tutor_teach") is None else "이번 변경은 설명을 못 만들었어요"
        )
        ui.done()
        return 0
    _emit_explain(exp)
    _learned(root, exp)
    ui.done()
    return 0


def _run_mission(root: str, text: str, json_out: bool) -> int:
    """지금 향하는 곳 한 줄. 적으면 저장하고, 빈손으로 부르면 적혀 있는 것을 보여 준다.

    설명이 순서를 고르려면 이 줄이 있어야 한다 — 어디로 가는지 모르면 어느 자리부터 읽어야
    하는지도 못 고른다.
    """
    teach = _engine("tutor_teach")
    body = " ".join(str(text or "").split())
    if teach is None:
        if not json_out:
            ui.head("tutor · 지금 향하는 곳")
            ui.ok("향하는 곳을 적어 둘 기능이 아직 없어요")
            ui.done()
        return 0
    try:
        current = teach.set_mission(root, body) if body else teach.mission(root)
    except Exception:
        current = ""
    if json_out:
        print(json.dumps({"mission": current}, ensure_ascii=False))
        return 0
    ui.head("tutor · 지금 향하는 곳")
    if current:
        ui.ok(current)
    else:
        ui.ok('아직 안 적으셨어요 — `asgard tutor --mission "..."`으로 한 줄 남겨 두세요')
    ui.done()
    return 0


def _run_close(root: str, answer: str, dismiss: str, note: str) -> int:
    """답 하나를 닫는다. **옳은 답인지는 안 본다** — 채점은 이 층의 일이 아니다(성장 기록 계약 ①)."""
    ui.head("tutor · 물음 닫기")
    if answer:
        ok, message = tutor_growth.answer(root, answer, note)
    else:
        ok, message = tutor_growth.dismiss(root, dismiss, note)
    (ui.ok if ok else ui.warn)(message)
    if not ok:
        ui.step(ui.dim("    열린 물음은 `asgard tutor --progress`에 모여 있어요"))
    ui.done()
    return 0


def _run_brief(root: str, text: str, paths: tuple[str, ...], quiet: bool) -> int:
    """카드 한 장 또는 침묵.

    `--quiet`는 훅이 켠다. 훅에게 "없다"는 말은 사용자 화면에 그대로 들어갈 빈 카드가 되고, 빈
    카드는 다음 카드의 신뢰를 깎는다 — `ui.ok`는 판정 줄이라 quiet을 무시하므로(ui 계약) 여기서
    끊는다. 사람이 직접 친 경우에만 "없다"고 답한다.
    """
    card = tutor.brief(root, text, paths)
    if card:
        print(card)
        return 0
    if not quiet:
        ui.head("tutor · 들어가기 전")
        ui.ok("이 자리엔 답 안 한 물음이 없어요")
        ui.done()
    return 0
