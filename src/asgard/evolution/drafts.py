"""신호 → SKILL.md 초안. 트리거 이름 고르기와 카드 본문 쓰기가 여기 있다."""

from __future__ import annotations

import hashlib
import os
import re
import time

_STOPWORDS = frozenset(
    "the and for with that this from into over under test tests failed failure error while when"
    " 검증 실패 수정 추가 제거 변경 파일 명령 확인".split()
)
PLACEHOLDER_TRIGGER = "재발-트리거-직접-기입"
# 산문에서 건질 이름의 모양 — **밑줄이 든 것만**. `verifier_gate`·`_has_marker`·`craft_note.py`
# 는 이 저장소가 코드에 붙이는 이름이고, 옆에 있던 `verifier`·`gate` 는 낱말이다.
#
# **붙임표는 여기 없다.** 한때 있었고, 그래서 `read-only`·`fail-open` 같은 영어 산문 합성어와
# 하네스 서식 조각(`uv run --no-project` 의 `no-project`)이 트리거로 나갔다. 붙임표 이름은
# 실패 서명 하나에서만 온다 — 그건 정형 실패 카탈로그가 이 상황에 붙인 이름이고, 기준 산문에
# 우연히 섞인 합성어와 달리 다음에 같은 자리가 무너질 때 그대로 다시 적힌다.
#
# 점만 든 이름도 여기 없다. `os.environ`·`self.assertEqual` 이 그 부류인데, 앞이 표준 라이브러리나
# 시험 틀이라 다음 요청에서 이 자리를 안 가리킨다.
_IDENT = re.compile(r"[A-Za-z_]*[A-Za-z0-9]+_[A-Za-z0-9_]*[A-Za-z0-9](?:\.[A-Za-z_][A-Za-z0-9_]*)*")
# 기준 한 줄의 `| verify: …`·`| artifacts: …` 꼬리는 하네스 계약 서식이지 이 변경의 내용이 아니다.
# 안 자르면 모든 초안이 같은 명령줄에서 같은 조각을 건져 온다 (`tutor_rationale._goal` 과 같은 자름).
_CONTRACT_TAIL = "|"
# 카드 본문에 적을 때는 꼬리를 정확히 집는다. 맨 막대만 보고 자르면 기준 문장 안의 막대에서도
# 잘린다 — 26-08-12 실측: `자동 설치 정책 evolution.autonomy off|safe|full 로 넣는다` 가
# `… off` 에서 끊겼다. `_triggers` 쪽 맨 막대는 그대로 둔다: 거기서 짧게 자르는 것은 트리거
# 후보를 덜 건지는 쪽이라 손해가 조용하고, 그 자름은 이미 시험이 붙잡고 있다.
_CONTRACT_TAIL_RE = re.compile(r"\s*\|\s*(?:verify|artifacts)\s*:")
_DESC_FILES = 4  # description 에 적는 파일 이름 개수 — 한 줄로 읽히는 상한
_SEPARATORS = ("-", "_", ".")
_TRIGGER_MIN = 4  # 구분자가 든 이름의 하한 — 구분자 없는 낱말은 길이와 무관하게 안 받는다
_TRIGGER_CAP = 6
_SKIP_STEMS = frozenset({"__init__", "__main__", "conftest", "setup", "main", "utils", "index"})


def _correction_draft(row: dict) -> tuple[str, str]:
    """정정 신호 → (스킬명, SKILL.md 초안). 증거 카드 — 사용자 원문이 정본이다."""
    quote = row.get("user_text", "")
    name = "learned-" + _slug(quote, "correction")
    # 정정에는 실패 서명이 없다 — 사용자 원문에 코드 이름이 없으면 자리표시자가 나가고,
    # `approve` 가 그것을 막아 사람이 재발 조건을 직접 적게 한다.
    #
    # 트리거는 오딘의 말과 **정정을 부른 답**에서 뽑는다. `assistant_head` 는 그 정정에 답한
    # 뒤의 글이라 이미 고쳐진 답이고, 거기서 이름을 뽑으면 재발 조건 대신 수정 결과가 트리거가
    # 된다. `assistant_before` 가 비어 있으면(기록을 못 읽은 세션) 오딘의 말만 쓴다.
    before = str(row.get("assistant_before") or "")
    triggers = _triggers("", f"{quote} {before}".strip())
    body = [
        "---",
        f"name: {name}",
        f"description: 사용자 정정에서 증류 — {quote[:120]}",
        f"triggers: {', '.join(triggers)}",
        "agent: any",
        "origin: correction",
        f"created: {time.strftime('%Y-%m-%d')}",
        f"evidence: {row.get('signal', '')}",
        "---",
        "",
        "## 정정 (사용자 원문)",
        f"- 「{quote}」 ({row.get('ts', '')[:10]})",
        "",
        "## 정정을 부른 응답",
        f"- {before or '(미기록 — 이 세션의 대화 기록을 못 읽었다)'}",
        "",
        "## 정정 뒤 응답 머리",
        f"- {row.get('assistant_head') or '(미기록)'}",
        "",
        "## 근거",
        "- 이 카드는 사용자 정정 발화의 증거 초안이다 — 승인 전에 '무엇을 어떻게 바꿔야 하는가'를",
        "  일반화 원칙으로 다듬어라 (특히 triggers와 description).",
        "",
    ]
    return name, "\n".join(body)


def _triggers(sig: str, text: str, files: object = ()) -> list[str]:
    """재발을 알아볼 이름들 — 실패 서명, 코드가 부르는 이름, 파일 이름. 산문 낱말은 안 쓴다.

    종전에는 기준·부제 산문을 토큰으로 잘라 앞 여섯 개를 실었다. 그 산문은 판정 서식이라 같은
    낱말이 매번 들어간다 — 26-08-11 에 저장소에 남아 있던 후보 넷의 트리거가 `충족`·`기준`·
    `이번`·`turn`·`pass`·`import` 였고, 매칭은 부분 문자열이라 `이번`은 한국어 요청 거의 전부에,
    `import` 는 파이썬 리팩터링 요청 거의 전부에 걸린다. 승인되면 그 스킬은 배울 것을 가르치는
    대신 매 디스패치에 실리는 소음이 된다.

    한국어 어절은 조사를 달고 나오는 것(`캐시가`·`로케일을`)도 같은 문제였다 — 그 형태 그대로는
    다음 요청의 `캐시를` 과 안 맞는다. 그래서 낱말 축을 통째로 버리고 이름 축만 남긴다: 실패
    서명, 바뀐 파일 이름, 기준·부제에 적힌 식별자. 셋 다 다음에 같은 자리를 건드릴 때 요청문이나
    파일 목록에 그대로 다시 나타나는 이름이다. 하나도 못 찾으면 자리표시자를 내고, `approve` 가
    그 자리표시자를 막아 사람이 직접 적게 한다.

    갈래는 둘이고 규칙은 하나다. **실패 서명은 통째로** 받는다 — 정형 카탈로그가 이 상황에 붙인
    이름이라 붙임표가 들어 있어도 산문이 아니다. **나머지는 밑줄이 든 이름만** 받는다: 산문에서든
    바뀐 파일 이름에서든 같다.

    밑줄 하나가 축인 이유는 이 저장소가 코드에 이름을 붙이는 방식이다. 붙임표까지 받았더니
    `read-only`·`fail-open` 같은 영어 합성어와 하네스 서식 조각(`uv run --no-project` 의
    `no-project`)이 트리거가 됐고, 맨낱말 파일 이름을 다섯 자 문턱으로 받았더니 `state`·`paths`·
    `tools`·`shell` 이 통과해 각각 "add a statement to the README"·"fix the import paths" 류에
    걸렸다. 문턱을 글자 수로 잡는 한 흔한 낱말과 드문 이름은 안 갈린다.

    값은 있다: 파일 이름이 전부 한 낱말인 변경은 실패 서명 하나만 트리거로 갖는다. 그건 재발을
    좁게 잡는 것이지 못 잡는 것이 아니고, 넓게 잡아 매 배차에 실리는 쪽보다 낫다.
    """
    found: list[str] = []
    taken: set[str] = set()  # 순서는 found 가, 중복 판정은 이쪽이 진다
    rows = files if isinstance(files, (list, tuple, set, frozenset)) else ()
    stems = [stem for rel in rows if "_" in (stem := os.path.splitext(os.path.basename(str(rel)))[0])]
    prose = "\n".join(line.split(_CONTRACT_TAIL, 1)[0] for line in str(text).splitlines())
    # 공백이 든 서명은 통째로 못 쓴다 — 부분 문자열 매칭이라 그 문장이 그대로 다시 적힐 때만
    # 맞는다. 그런 서명의 알맹이는 아래 산문 훑기가 식별자로 건진다.
    head = [name for name in (str(sig).strip(),) if name and not any(c.isspace() for c in name)]
    for raw in [*head, *_IDENT.findall(prose), *stems]:
        name = str(raw).lower().strip("".join(_SEPARATORS))
        if not name or name in taken or name in _STOPWORDS or name in _SKIP_STEMS:
            continue
        if _too_loose(name):
            continue
        found.append(name)
        taken.add(name)
    return found[:_TRIGGER_CAP] or [PLACEHOLDER_TRIGGER]


def _too_loose(name: str) -> bool:
    """이 이름 하나로는 자리를 못 가리는가 — 구분자가 없거나 너무 짧으면 그렇다.

    맨낱말을 글자 수로 받던 판이 먼저 있었고, 거기서 `state`·`paths`·`tools`·`shell`·`session`·
    `boundary` 가 다 통과했다. 매칭이 부분 문자열이라 `state` 는 "add a statement to the README"
    에 걸린다. 흔한 낱말과 드문 이름은 글자 수로 안 갈리므로 축을 구분자로 바꿨다.

    `bragi` 처럼 쓸 만한 맨낱말도 같이 막힌다. 그래도 이 축을 고른 이유는 두 실패의 크기가
    다르기 때문이다 — 막힌 이름은 `bragi.py` 나 `asgard-bragi` 로 한 걸음에 고치지만, 넓은
    트리거 하나는 매 배차마다 스킬 본문을 프롬프트에 밀어 넣는다.
    """
    return not any(sep in name for sep in _SEPARATORS) or len(name) < _TRIGGER_MIN


def weak_triggers(triggers: object) -> tuple[str, ...]:
    """이 묶음에서 재발을 못 알아보는 트리거들. 전부 통과하면 빈 튜플.

    `_triggers` 와 **같은 `_too_loose` 를 쓴다** — 생성기가 안 내는 것을 승인이 받아 주면 그
    문턱은 문턱이 아니다. 검사가 여기 한 번 더 서는 이유는 pending 초안이 **승인 전에 사람이
    손으로 고치는 파일**이라서다. 생성기만 지키면 손으로 적어 넣은 `pass` 한 줄이 그대로
    설치되고, 이미 인박스에 쌓여 있던 옛 초안(옛 생성기 산물)도 그대로 들어간다.

    같은 문턱을 쓰되 생성기 쪽이 더 좁다: 산문과 파일 이름에서는 밑줄이 든 것만 받고, 붙임표는
    실패 서명 하나에서만 받는다. 좁은 쪽이 생성기인 것이 안전한 방향이다 — 사람이 고른 이름은
    사람이 책임지고, 기계가 대량으로 뜨는 이름은 기계가 더 조심한다.

    거르는 대신 **이름을 대고 거절**한다. 사람이 적은 트리거를 조용히 지우면 그 스킬은 자기가
    무엇에 걸리는지와 다른 것이 설치된다. 한 걸음으로 고칠 수 있는 거절이 조용한 수정보다 낫다.
    """
    rows = triggers if isinstance(triggers, (list, tuple, set, frozenset)) else str(triggers or "").split(",")
    names = [str(t).strip().lower() for t in rows if str(t).strip()]
    if not names:
        return (PLACEHOLDER_TRIGGER,)
    return tuple(name for name in names if name == PLACEHOLDER_TRIGGER or _too_loose(name))


def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9가-힣]+", "-", text.lower()).strip("-")[:40].strip("-")
    return s or fallback


def _more(rows: object, shown: int) -> str:
    """상한에 걸려 빠진 개수 — 잘랐다는 사실을 카드가 스스로 말한다 (빈 문자열 = 전부 들어갔다)."""
    total = len(rows) if isinstance(rows, (list, tuple)) else 0
    return f" 외 {total - shown}개" if total > shown else ""


def _draft(sig: dict) -> tuple[str, str]:
    """신호 → (스킬명, SKILL.md 초안). 증거 카드 — 실측 데이터만 서술, 추측 금지."""
    cid_seed = sig["signal"]
    name = "learned-" + _slug(sig["failure_sig"] or (sig["subtasks"][0] if sig["subtasks"] else ""), "quest")
    trig_src = " ".join([sig["failure_sig"]] + sig["subtasks"] + sig["criteria"])
    triggers = _triggers(sig["failure_sig"], trig_src, sig["changed_files"])
    esc = " (ESCALATE 경유)" if sig["escalated"] else ""
    # 설명 첫 자리에 실패 서명을 둔다 — 카탈로그에서 이 한 줄만 읽고 스킬을 부를지 정하므로,
    # 잘려 나간 기준 문장보다 "무엇에 막혔던 자리인가"가 먼저 서야 한다.
    where = sig["failure_sig"] or sig["signal"]
    # 두 번째 자리는 **어느 파일에서였는가**다. 종전에는 퀘스트 부제를 그대로 적었는데, 부제는
    # 그 퀘스트가 스스로를 부른 이름이라(`… 등급 + 큐레이터 호출자 + 정정 뿌리 통일 + 마라 탐지`)
    # 다음 사람이 자기 작업과 맞춰 볼 것이 없다 (26-08-12 실측: 워커가 카드에서 쓸모를 찾은 것은
    # 함정 한 줄뿐이었다). 파일 이름은 다음에 같은 자리를 열 때 화면에 그대로 다시 뜬다.
    #
    # 자르는 축은 글자 수가 아니라 이름 개수다. 글자 수로 자르면 마지막 이름이 중간에서 끊겨
    # (`skill_`) 찾을 수 없는 이름이 설명에 남는다.
    #
    # 남은 개수는 **같은 이름끼리 묶은 뒤** 센다. 원본 목록으로 세면 `cli/evolve.py` 와
    # `commands/evolve.py` 처럼 이름이 겹치는 자리에서 실제보다 많이 남았다고 적힌다
    # (26-08-12 실측: 열 파일·아홉 이름인 퀘스트가 `외 6개`라고 했는데 남은 것은 다섯이었다).
    unique = list(dict.fromkeys(os.path.basename(str(f)) for f in sig["changed_files"]))
    area = ", ".join(unique[:_DESC_FILES]) + _more(unique, _DESC_FILES)
    fallback = sig["subtasks"][0] if sig["subtasks"] else (sig["criteria"][0] if sig["criteria"] else "")
    desc_src = area or _CONTRACT_TAIL_RE.split(str(fallback), 1)[0].strip()[:80]
    # 셋 다 비면 자리를 말할 것이 없다. 그때 `— 에서 겪고 고친 자리` 를 그대로 두면 명사 없는
    # 조사와 빈칸 둘이 남으므로 절을 통째로 뺀다.
    at = f" — {desc_src}에서 겪고 고친 자리" if desc_src else ""
    body = [
        "---",
        f"name: {name}",
        f"description: {where}{at} (FAIL {sig['fail_count']}회{esc} 뒤 PASS)",
        f"triggers: {', '.join(triggers)}",
        "agent: worker",
        "origin: retrospective",
        f"created: {time.strftime('%Y-%m-%d')}",
        f"evidence: {sig['quest_id']}",
        "---",
        "",
        # 퀘스트 로그가 실패에 대해 남기는 것은 서명 한 줄뿐이다(구조화 실패 카탈로그). 무슨 일이
        # 있었는지는 그 로그를 열어야 나오므로, 여기서 서사를 지어내는 대신 서명과 자리를 적는다.
        "## 함정 (먼저 실패한 지점 — 퀘스트 로그의 실패 서명)",
        *(f"- {w}" for w in (sig["fail_whys"] or ["(failure_sig 미기록 — 퀘스트 로그 참조)"])),
        f"- 무슨 일이었는지는 `.asgard/quest/{sig['quest_id']}.jsonl` 의 verify 이벤트에 있다.",
        "",
        # 아래 셋은 전부 상한이 있다. 상한이 없던 26-08-12 의 첫 카드는 기준 6줄·파일 10개·명령
        # 6줄이었고, 그것을 받은 워커가 "쓸모 있던 것은 함정 한 줄뿐이고 나머지는 그 퀘스트의
        # 장부였다"고 보고했다. 장부는 퀘스트 로그가 이미 갖고 있으므로 카드는 다음 사람이 옮겨
        # 쓸 수 있는 만큼만 진다. 기준 줄의 `| verify: …` 꼬리는 하네스 서식이라 여기서 자른다.
        "## 전략 (결국 통과한 접근)",
        *(f"- criteria: {_CONTRACT_TAIL_RE.split(str(c), 1)[0].strip()}" for c in sig["criteria"][:2]),
        *(
            [f"- 대상 파일: {', '.join(sig['changed_files'][:4])}{_more(sig['changed_files'], 4)}"]
            if sig["changed_files"]
            else []
        ),
        "",
        "## 검증 (성공을 입증한 명령)",
        *(f"- `{c}`" for c in (sig["pass_commands"][:3] or ["(명령 미기록)"])),
        "",
        "## 근거",
        f"- quest: {sig['quest_id']} — FAIL {sig['fail_count']}회 → PASS ({sig['task_class'] or 'unknown'})",
        "- 이 카드는 결정론 증거 초안이다 — 트리거와 전략 서술은 언제든 다듬어도 된다.",
        "",
    ]
    _ = cid_seed
    return name, "\n".join(body)


def _cand_id(signal: str) -> str:
    return "evo-" + hashlib.sha1(signal.encode()).hexdigest()[:8]
