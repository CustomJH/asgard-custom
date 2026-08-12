"""evolution — 회고 증류기 + 진화 인박스 (자가발전 C1/C2, CUS-253·254).

quest 로그(.asgard/quest/*.jsonl)에서 hard-won 신호(실패를 딛고 PASS에 도달한 퀘스트)만
결정론적으로 선별해 스킬 초안을 만들고, .asgard/evolution/pending/ 인박스에 스테이징한다.

learned 스킬 뱅크(.asgard/skills/)로 설치하는 함수는 `approve` 하나다. 그 하나를 누가 누르는지는
자율 등급이 정한다 (`autonomy_mode` — 기본 safe 는 퀘스트 로그 채굴분을 스스로 설치하고, 정정
채굴분은 사람에게 남긴다). 등급이 무엇이든 검사는 approve 안에 있고, 설치된 것은
`evolve archive` 로 물러난다.

설계 근거 (CUS-251 리서치):
- 선별은 결정론, 가치 판단은 사용자 — 저신호 휴리스틱 양산은 승인율을 0으로 만든다는
  실증 교훈. 여기서는 "FAIL→PASS 전환"이라는 고신호만 후보가 된다 (hard-won 교훈).
- 캡처 금지 필터 — 환경 의존 실패·일시 장애는 스킬이 아니다 (실전 교훈: 도구 부정 주장을
  캡처하면 몇 달간 자기 인용해 스스로 거부하게 된다).
- 거부 신호는 latch — 같은 신호를 다시 제안하지 않는다 (consent-first, 제안 피로 방지).
- 초안은 증거 카드 (실측 failure_sig·통과 명령·criteria) — 추측 서사를 쓰지 않는다.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import time

from . import io_files
from .skill_bank import APPROVAL_FILE, SKILL_FILE, approval_receipt, learned_skills, parse_skill_md

EVO_DIR = "evolution"
PENDING = "pending"
REJECTED = "rejected"
SEEN_FILE = "seen.json"
CORRECTIONS_FILE = "corrections.jsonl"
_SCAN_CAP = 3  # 스캔 1회당 신규 후보 상한 — 인박스 폭탄 방지
_CORRECTIONS_CAP = 200  # corrections.jsonl 보존 상한 — 최신 우선

# 캡처 금지 — 환경 의존/일시 실패·크레덴셜·도구 부정 주장은 교훈이 아니라 그날의 사정이다
# (26-07-16: unconfigured credentials + tool-negativity 패턴 보강)
_FORBIDDEN_SIG = re.compile(
    r"command not found|no such file|enoent|permission denied|not installed|"
    r"missing (?:binary|tool|dependency)|rate.?limit|connection|network|timed?.?out|"
    r"unavailable|미설치|권한 거부|없는 (?:파일|명령)|"
    r"credential|api.?key|token|unauthorized|forbidden|\b40[13]\b|인증|자격 증명|"
    r"(?:tool|mcp|browser)s?\s+(?:is\s+)?(?:broken|not\s+work)|does not work|not supported",
    re.IGNORECASE,
)
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


def _evo_dir(root: str, *parts: str) -> str:
    return os.path.join(root, ".asgard", EVO_DIR, *parts)


def _load_seen(root: str) -> dict:
    d = io_files.read_json(_evo_dir(root, SEEN_FILE))
    return d if isinstance(d, dict) else {}


def _save_seen(root: str, seen: dict) -> None:
    io_files.write_json(_evo_dir(root, SEEN_FILE), seen)


def _read_quest(path: str) -> list[dict]:
    events = []
    try:
        with open(path, encoding="utf-8") as handle:
            lines = list(handle)
        for line in lines:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue  # 절단 줄 = 크래시 흔적 — 나머지 이벤트는 유효
    except OSError:
        pass
    return events


def _quest_signal(events: list[dict]) -> dict | None:
    """퀘스트 1개 → hard-won 신호 또는 None. 결정론 — LLM 없음.

    조건: 최종 verdict PASS + 도중 FAIL(또는 ESCALATE) 존재. 금지 시그니처면 제외."""
    if not events:
        return None
    verdicts = [e for e in events if e.get("verdict") in ("PASS", "FAIL", "ESCALATE")]
    if not verdicts or verdicts[-1]["verdict"] != "PASS":
        return None
    fails = [e for e in verdicts if e["verdict"] in ("FAIL", "ESCALATE")]
    if not fails:
        return None  # 순탄한 PASS = 교훈 없음
    sig = next((str(e.get("failure_sig") or "") for e in reversed(fails) if e.get("failure_sig")), "")
    if sig and _FORBIDDEN_SIG.search(sig):
        return None
    final = verdicts[-1]
    pass_cmds = [c for c in (final.get("commands") or []) if isinstance(c, dict) and c.get("exit_code") == 0]
    subtasks = [str(e.get("subtask") or "") for e in events if e.get("subtask")]
    return {
        "quest_id": str(events[0].get("quest_id") or ""),
        "signal": sig or f"quest:{events[0].get('quest_id', '')}",
        "failure_sig": sig,
        "fail_count": len(fails),
        "escalated": any(e["verdict"] == "ESCALATE" for e in fails),
        "criteria": [str(c) for c in (final.get("criteria") or [])][:6],
        "pass_commands": [str(c.get("cmd", ""))[:200] for c in pass_cmds][:6],
        "changed_files": [str(f) for f in (final.get("changed_files") or [])][:10],
        "subtasks": subtasks[:4],
        "task_class": str((events[0].get("risk") or {}).get("task_class") or ""),
        # 함정 섹션 수록분도 금지 필터 적용 — 마지막 sig만 걸러도 앞선 환경 노이즈가
        # 초안 본문에 박제되는 누수가 있었다 (26-07-16)
        "fail_whys": [
            str(e.get("failure_sig"))[:200]
            for e in fails
            if e.get("failure_sig") and not _FORBIDDEN_SIG.search(str(e["failure_sig"]))
        ][:4],
    }


# ── 사용자 정정 신호 (제2 채굴원 — 26-07-24) ─────────────────────────────────────
#
# "그게 아니야" / "~하지 마" / "~말고 …로 해" 류의 정정은 FAIL→PASS 만큼 고신호다:
# 사용자가 방금 실제로 교정했다는 실측 증거. 탐지는 0-LLM 보수 패턴 — 애매하면 버린다
# (false positive 1건이 승인 피로 10건보다 나쁘다). 처분은 기존 인박스 계약 그대로 후보
# 스테이징이고, 기본 등급 safe 는 이 채굴원을 자동 설치에서 뺀다 (_AUTONOMY_ORIGINS).
#
# 26-08-11 실측: 이 채굴원은 열린 이래 산출이 0건이었고, `corrections.jsonl` 이 만들어진 적도
# 없다. 원인은 상한도 배선도 아니었다 — 실제 오딘 발화 12건에 3건만 걸렸다. 패턴이 **문형이
# 아니라 어간**에 걸려 있어서다: `하지\s*마` 는 "하지"라는 낱말을 요구하므로 "쓰지 마"·"붙이지
# 마"를 못 잡고, `아니(야|라니까)` 는 "아닌 것 같은데"를 못 잡으며, `(로|으로)\s*해\s*줘?$` 는
# "써줘"를 못 잡는다. 한국어는 어간이 바뀌므로 어간을 적으면 그 동사를 골랐을 때만 걸린다.
#
# 그래서 축을 어미로 옮긴다 — `-지 마`, `-면 안 되`, `아니-`, `말고`. 어미는 동사와 무관하게
# 같은 모양으로 남는 자리라 하나만 적어도 그 문형 전체를 덮는다.
#
# 넓힐 때 서술문 거부권을 하나 같이 뒀다가 지웠다. 이 저장소 산문이 온통 "…가 아니라 …다" 꼴이라
# 먹힐 줄 알았는데, 재 보니 그 형태는 아래 어느 패턴에도 안 걸린다 — 거부권이 막은 것은 오탐이
# 아니라 진짜 정정 둘이었다("그게 아니라 이렇게 해", "이건 캐시가 아니라 큐니까 지우지 마").
# 실측 없이 넣은 안전장치가 정확히 지키려던 것을 깎고 있었다.
# 세 번째 판이다. 앞의 둘은 다 **어미 목록을 고쳐 적는** 수리였고, 두 번 다 한쪽을 막자 반대쪽이
# 열렸다 — 오탐을 닫으면 재현이 뚫리고 재현을 메우면 오탐이 났다. 목록이 뿌리가 아니라는 뜻이라
# (Canon 9) 판정 **단위**를 바꾼다.
#
# 왜 목록으로는 안 되는가. 부분 문자열 정규식은 `이미지`의 끝 `지`와 `하지`의 어미 `지`를,
# `이해`의 `해`와 종결형 `해`를, `혼자`의 `자`와 청유형 `자`를 구조적으로 못 가른다. 한국어는
# 조사와 어미가 앞말에 붙어 쓰이므로 낱말 경계가 곧 형태소 경계가 아니고, 어느 음절을 더 넣고
# 빼도 그 벽은 안 넘는다.
#
# 그래서 규칙 하나로 바꾼다: **닻은 절 끝에만 박는다.** 종결형은 문장이나 절이 끝나는 자리에
# 서고, 낱말 속 동음 음절은 거기 못 온다 — `혼자 남는다`의 `자` 뒤에는 문장이 더 이어지고,
# `빨라지는지`의 `라` 뒤에는 음절이 더 붙는다. 그 자리를 못 잡는 갈래는 넓히는 대신 **버린다**
# (이 층의 계약: 애매하면 버린다, false positive 1건이 승인 피로 10건보다 나쁘다).
#
# 버린 것 셋과 그 값:
#   · `-면 안 되` 의 연결형(`안 되니까`·`안 되면`) — 관형형 `안 되는 이유가 뭐야?`(질문)와 같은
#     모양이라 문장 끝 형태(`안 되지`·`안 돼`)만 남겼다. "그거 하면 안 되니까 빼줘" 를 놓친다.
#   · `-지 말고` — `이미지 말고`·`페이지 말고` 와 글자가 같다. 대조는 아래 `말고|대신` 이 지시
#     어미를 닻으로 잡으므로 이 갈래를 지워도 진짜 정정은 그쪽에서 걸린다.
#   · 종결 어미 `라`·`자` — `빨라`·`혼자`·`글자`와 안 갈린다. `해라`·`하자` 같은 온전한 형태만 남겼다.
#
# 절 경계는 **한 자리에만 적는다**. 처음에는 갈래마다 따로 적었고, 그래서 `-지 마` 만 진짜 절
# 경계를 알고 나머지 셋은 `$`(메시지 끝)를 요구했다 — 정정 뒤에 이유 한 줄이 더 붙으면 그 셋이
# 통째로 죽었다("opus 말고 sonnet 으로 돌려줘. 비용이 두 배라서…"는 미탐이었다). 오딘이 실제로
# 쓰는 꼴이 그 모양이라 8건 중 4건을 놓쳤다. 같은 규칙을 네 번 적으면 네 번째가 반드시 갈라진다.
#
# 변형 셋은 **한 글자 집합에서 조합한다** — 각각 따로 적으면 그것이 다시 네 벌이 된다. 빼는
# 무리마다 이유가 하나씩 붙는다:
#   · 금지에는 물음표가 없다. `안 돼요?`·`안 됩니까?` 는 금지가 아니라 허가를 묻는 질문이고,
#     물음표를 절 끝으로 세면 그 화행이 통째로 정정으로 읽힌다.
#   · 홑글자 `마` 에는 인용 마감이 없다. 이 저장소는 사용자 표면 문자열이 한국어라
#     `ui.warn("전체 트리를 stash 하지 마")` 를 붙여넣고 묻는 요청이 드물지 않다.
_CLOSERS = ",.!;:·…~"
_QUOTES = "\"'”’」』)\\]"
_CLAUSE_END = f"(?=[\\s?{_CLOSERS}{_QUOTES}]|$)"
_STATEMENT_END = f"(?=[\\s{_CLOSERS}{_QUOTES}]|$)"
_BARE_END = f"(?=[\\s?{_CLOSERS}]|$)"

_CORRECTION_PATTERNS = (
    re.compile(r"(그게|그거|그건|이게|저게)\s*아니"),
    # `아니다` 는 여기 없다. 평서형 계사라 이 저장소 산문에 흔하고("그건 회귀가 아니다"), 정정으로
    # 쓰인 "그건 아니다" 는 바로 위 지시대명사 패턴이 이미 잡는다.
    re.compile(r"아니(야|라니까|네|었|야지)"),
    re.compile(r"아닌\s*(것|거|듯)\s*같"),
    # `-지 마/말` 금지. 앞 동사는 무엇이든 온다 — 하지·쓰지·붙이지·지우지·넣지. `마`·`마라` 는
    # 절 끝에서만 센다(`이모지 마스크`·`하지 마라톤` 은 정정이 아니다 — 뒤에 음절이 더 붙으므로
    # 절 끝이 안 선다). `말아라` 는 아래 `말(…)` 갈래가 잡는데 그 축약형 `마라` 가 빠져 있었다
    # (26-08-12 실측: 표본 10개 중 `삭제하지 마라` 하나가 이 구멍으로 샜다).
    # `말고` 갈래는 여기 없다 — 위 주석 참조.
    re.compile(r"[가-힣]지\s*(는\s*)?(마(세요|십시오|요)|마라?" + _BARE_END + r"|말(라고|아라|아\s*줘|자))"),
    # `-면 안 되` 는 평서형 종결만. 관형형·연결형은 질문과 글자가 같다. 해요체·명사형까지 세는
    # 이유는 이 저장소 터미널 정본이 해요체라서다. 긴 형태를 먼저 적는다 — `돼` 가 먼저 맞으면
    # 뒤의 `요` 에서 절 경계가 안 서서 `안 돼요` 가 통째로 미탐이 된다.
    re.compile(r"[가-힣]면\s*안\s*(되지|된다|됩니다|돼요|됨|돼)" + _STATEMENT_END),
    # 대조에는 지시 어미가 붙어야 정정이다. "대신 저 함수를 쓰면 어떤 차이가 있어?" 는 질문이고,
    # "머지 말고 리베이스로 해줘" 는 정정이다. 어미는 **절 끝**에서만 센다.
    re.compile(r"(말고|대신)\s+\S.{0,40}?(주세요|해야지|해라|하자|야지|세요|줘)" + _CLAUSE_END),
    # `…로 해` 는 앞 조사가 닻이다 — `로`/`으로` 바로 뒤의 종결 `해` 만 센다. 그것 없이 문장이
    # `해` 로 끝나는 자리는 `이해`·`편해`·`급해` 라 정정이 아니다.
    re.compile(r"(말고|대신)\s+\S.{0,40}?(로|으로)\s*해" + _CLAUSE_END),
    # 종전에 `(로|으로)\s*해\s*줘?$` 가 대조 없이 홀로 있었고 지웠다. "해요체로 써줘"·"영어로
    # 바꿔줘"는 맥락 없이는 정정과 첫 요청을 못 가른다 — 실측에서 "근거는 링크로 해줘"·"한 줄로
    # 적어 줘" 같은 평범한 지시가 같이 걸렸다. 대조가 드러난 형태는 위 둘이 잡는다.
    #
    # 영어 `don't` 는 뒤따르는 동사가 닻이다. `dont know`·`dont pass` 는 서술이고 `don't add`·
    # `don't use` 는 금지다 — 영어는 활용이 없어서 목록 하나가 그 자리를 다 덮는다.
    re.compile(
        r"\bstop doing\b|\bnot what i (asked|meant)\b|\bthat'?s wrong\b|\binstead of\b|"
        r"\bdon'?t\s+(do|use|add|change|remove|delete|touch|put|make|write|commit|push|call|run)\b",
        re.IGNORECASE,
    ),
)
_CORRECTION_MAX_CHARS = 500  # 정정은 짧다 — 장문은 설명/새 요청일 확률이 높다


def correction_signal(user_text: str) -> str | None:
    """정정 발화 판정 (0-LLM) — 매치 구절을 반환, 아니면 None. 보수적: 장문·서술문 배제."""
    text = (user_text or "").strip()
    if not text or len(text) > _CORRECTION_MAX_CHARS:
        return None
    for pattern in _CORRECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)[:40]
    return None


def record_correction(root: str, user_text: str, assistant_text: str = "") -> bool:
    """정정 발화를 corrections.jsonl에 스테이징한다 (탐지 실패·중복·위협 = False, 무해).

    저장은 신호 원문뿐 — 스킬 초안 변환은 mine()이 latch와 함께 수행한다."""
    try:
        phrase = correction_signal(user_text)
        if not phrase:
            return False
        from .memory import scan_secrets, scan_threats

        if scan_threats(user_text) or scan_secrets(user_text):
            return False  # 오염 발화는 증거로도 넣지 않는다
        signal = "correction:" + hashlib.sha1(user_text.strip().encode()).hexdigest()[:12]
        os.makedirs(_evo_dir(root), exist_ok=True)
        path = _evo_dir(root, CORRECTIONS_FILE)
        rows: list[dict] = []
        try:
            with open(path, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle if line.strip()]
        except OSError, ValueError:
            rows = []
        if any(r.get("signal") == signal for r in rows):
            return False  # 같은 발화 재기록 방지 (재실행·중복 훅)
        rows.append(
            {
                "signal": signal,
                "phrase": phrase,
                "user_text": user_text.strip()[:_CORRECTION_MAX_CHARS],
                "assistant_head": re.sub(r"\s+", " ", (assistant_text or "").strip())[:200],
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        rows = rows[-_CORRECTIONS_CAP:]
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        os.replace(tmp, path)
        return True
    except Exception:
        return False  # 채굴원 장애가 턴을 막지 않는다


def _corrections(root: str) -> list[dict]:
    try:
        with open(_evo_dir(root, CORRECTIONS_FILE), encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except OSError, ValueError:
        return []


def _correction_draft(row: dict) -> tuple[str, str]:
    """정정 신호 → (스킬명, SKILL.md 초안). 증거 카드 — 사용자 원문이 정본이다."""
    quote = row.get("user_text", "")
    name = "learned-" + _slug(quote, "correction")
    # 정정에는 실패 서명이 없다 — 사용자 원문에 코드 이름이 없으면 자리표시자가 나가고,
    # `approve` 가 그것을 막아 사람이 재발 조건을 직접 적게 한다.
    triggers = _triggers("", quote + " " + row.get("assistant_head", ""))
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
        "## 직전 맥락 (에이전트 응답 머리)",
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


_POLISH_SYS = (
    "스킬 초안 편집기. 입력은 에이전트 세션의 실측 증거로 만든 SKILL.md 초안이다. "
    "같은 SKILL.md 형식으로만 다시 써서 출력한다 (설명·코드펜스 금지, --- frontmatter로 시작). "
    "규칙: (1) 증거에 없는 사실을 지어내지 않는다 — 전략·함정 서술을 일반화 가능한 원칙 문장으로 "
    "다듬는 것만 허용. (2) frontmatter의 name/agent/origin/created/evidence는 그대로 보존. "
    "(3) triggers는 재발 상황을 잡을 실질 키워드로 개선 가능. (4) description은 한 문장. "
    "(5) 환경 의존 실패·도구에 대한 부정 주장은 쓰지 않는다."
)


def polish(root: str, cid: str) -> tuple[bool, str]:
    """LLM 증류 (opt-in) — pending 초안을 원칙 수준 서술로 다듬는다. 실패 = 초안 유지 (fail-open).

    닫힌 과업이다: LLM은 초안 '재작성'만 한다 — 스킬 가치 판단(승인)은 여전히 사용자 몫이고,
    산출물은 pending에 머무른다 (LLM open-ended 판단 금지, CUS-251)."""
    draft = show(root, cid)
    if draft is None:
        return False, f"후보 없음: {cid}"
    try:
        from .agent.oneshot import complete_once

        raw = complete_once(root, _POLISH_SYS, draft, max_tokens=3000)
    except RuntimeError as e:  # provider 미충족 — 사전 조건 메시지 그대로
        return False, str(e)
    except Exception as e:
        return False, f"LLM 호출 실패 — 결정론 초안 유지 ({type(e).__name__})"
    start = raw.find("---")
    parsed = parse_skill_md(raw[start:]) if start != -1 else None
    if not parsed:
        return False, "LLM 출력이 SKILL.md 형식이 아님 — 결정론 초안 유지"
    old_meta, _ = parse_skill_md(draft) or ({}, "")
    new_meta, _ = parsed
    if str(new_meta.get("name")) != str(old_meta.get("name")):
        return False, "LLM이 보존 필드(name)를 바꿈 — 결정론 초안 유지 (satisficing backstop)"
    p = _evo_dir(root, PENDING, cid, SKILL_FILE)
    orig = f"{p}.orig"
    if not os.path.exists(orig):  # 결정론 초안 백업 — latch 때문에 재생성 불가, 내용 열화 시 복구선
        io_files.write_text(orig, draft)
    io_files.write_text(p, raw[start:].rstrip() + "\n")
    return True, f"증류 완료 — {cid} 초안이 다듬어졌다 (여전히 pending, 승인 필요. 원본: SKILL.md.orig)"


def _stage_candidate(root: str, seen: dict, signal: str, name: str, skill_md: str, meta_extra: dict) -> dict:
    """후보 1건을 pending에 스테이징 + seen latch. 반환 = 후보 메타 (채굴원 공용)."""
    cid = _cand_id(signal)
    d = _evo_dir(root, PENDING, cid)
    os.makedirs(d, exist_ok=True)
    io_files.write_text(os.path.join(d, SKILL_FILE), skill_md)
    meta = {
        "id": cid,
        "name": name,
        "signal": signal,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **meta_extra,
    }
    io_files.write_json(os.path.join(d, "meta.json"), meta)
    seen[signal] = {"status": "proposed", "id": cid, "ts": meta["created"]}
    return meta


def mine(root: str, cap: int = _SCAN_CAP) -> list[dict]:
    """2채굴원 스캔 — quest 로그(FAIL→PASS) + 사용자 정정(corrections.jsonl) → pending 스테이징."""
    seen = _load_seen(root)
    created: list[dict] = []
    qdir = os.path.join(root, ".asgard", "quest")
    if os.path.isdir(qdir):
        for fname in sorted(os.listdir(qdir)):
            if not fname.endswith(".jsonl") or len(created) >= cap:
                continue
            sig = _quest_signal(_read_quest(os.path.join(qdir, fname)))
            if not sig or sig["signal"] in seen:
                continue
            name, skill_md = _draft(sig)
            created.append(
                _stage_candidate(
                    root,
                    seen,
                    sig["signal"],
                    name,
                    skill_md,
                    {"quest_id": sig["quest_id"], "fail_count": sig["fail_count"], "origin": "retrospective"},
                )
            )
    for row in _corrections(root):
        if len(created) >= cap:
            break
        signal = str(row.get("signal") or "")
        if not signal or signal in seen:
            continue
        name, skill_md = _correction_draft(row)
        created.append(_stage_candidate(root, seen, signal, name, skill_md, {"origin": "correction"}))
    if created:
        _save_seen(root, seen)
    return created


def unmined_signals(root: str, qid: str | None = None) -> int:
    """미제안 신호 수 (쓰기 없음) — 넛지·doctor 용. qid 지정 시 해당 퀘스트만 (정정 제외)."""
    seen = _load_seen(root)
    n = 0
    qdir = os.path.join(root, ".asgard", "quest")
    if os.path.isdir(qdir):
        for fname in sorted(os.listdir(qdir)):
            if not fname.endswith(".jsonl"):
                continue
            if qid and fname != f"{qid}.jsonl":
                continue
            sig = _quest_signal(_read_quest(os.path.join(qdir, fname)))
            if sig and sig["signal"] not in seen:
                n += 1
    if qid is None:
        n += sum(1 for row in _corrections(root) if str(row.get("signal") or "") not in seen)
    return n


AUTOSCAN_ENV = "ASGARD_EVOLVE_AUTOSCAN"


def autoscan_enabled() -> bool:
    """퀘스트가 닫힐 때 스스로 채굴하는가 — env > 글로벌 `evolution.autoscan`, 기본 on.

    채굴 자체는 **능력을 바꾸지 않는다**: 결과는 pending 인박스의 초안 파일이다. 그 초안이
    라우팅에 서느냐는 별개의 손잡이가 정한다 (`autonomy_mode`) — 이 스위치를 꺼도 저 등급이
    켜져 있으면 채굴이 없어 설치도 없고, 이 스위치만 켜면 초안까지만 생긴다.

    왜 기본을 켜는가. 넛지만 두었더니 신호가 **실제로 채굴되지 않았다** (26-07-31 실측: 이
    저장소에 hard-won 신호 2건이 닷새째 남아 있었고 인박스는 한 번도 만들어진 적이 없다).
    넛지는 신호 집합이 바뀔 때 한 번만 말하는 latch라 놓치면 영영 조용하고, 퀘스트 로그는
    keep-last-N으로 지워진다 — 교훈이 조용히 사라지는 쪽이 기본값이었다."""
    value = str(os.environ.get(AUTOSCAN_ENV) or "").strip().lower()
    if value:
        return value in ("on", "1", "true", "yes")
    try:
        from .settings import load_global

        setting = (load_global().get("evolution") or {}).get("autoscan", True)
    except Exception:
        return True
    return str(setting).strip().lower() not in ("off", "0", "false", "no")


def autoscan(root: str) -> list[dict]:
    """퀘스트 종료 시 자동 채굴 — 실패는 삼킨다 (성장은 부가 기능이지 종료 조건이 아니다)."""
    if not autoscan_enabled():
        return []
    try:
        return mine(root)
    except Exception:
        return []


AUTONOMY_ENV = "ASGARD_EVOLVE_AUTONOMY"
AUTONOMY_MODES = ("off", "safe", "full")
# 어느 채굴원까지 스스로 설치해도 되는가. 등급은 채굴원의 증거 무게로 가른다 (pattern 의
# explicit/deductive 경계와 같은 물음이다).
#
# retrospective = 퀘스트 하나가 실제로 FAIL 을 내고 그 다음에 PASS 한 기록이다. 실패 서명도
# 통과 명령도 하네스가 관측한 값이라 사람이 다시 확인할 것이 적다.
#
# correction = 오딘의 발화 한 줄이다. 그 한 줄이 검증된 수정인지 그때의 기분인지 문장만으로는
# 안 갈리고, 정정은 대개 취향을 담으므로 잘못 설치하면 그 취향이 다음 배차마다 되풀이된다.
# 그래서 safe 에서는 초안으로만 남기고 사람이 읽고 넘긴다.
_AUTONOMY_ORIGINS = {
    "off": frozenset(),
    "safe": frozenset({"retrospective"}),
    "full": frozenset({"retrospective", "correction"}),
}


def autonomy_mode() -> str:
    """자율 성장 등급 — env `ASGARD_EVOLVE_AUTONOMY` > 글로벌 `evolution.autonomy`, 기본 safe.

    off 는 종전 계약 그대로다: 채굴은 하고 설치는 사람만 한다. safe·full 은 그 승인 관문을
    없애는 것이 아니라 **대신 눌러 준다** — `approve` 를 그대로 지나므로 약한 트리거 거부와
    이름 충돌 거부가 한 자리도 빠지지 않고 선다. 금지 서명 필터는 그보다 앞선 채굴 단계에
    있어서(`_quest_signal`) 자동 설치분도 애초에 후보가 안 된다.

    기본을 켜는 근거는 autoscan 과 같다. 26-08-12 실측: 이 저장소에 초안 7건이 대기 중이고
    설치된 학습 스킬은 0건이었다 — 사람 손 하나에 레인 전체가 걸려 있으면 그 레인은 안 돈다.
    자율의 상한은 '가역'에 둔다: 자동 설치분은 영수증에 표식을 남기고 `evolve archive` 한 줄로
    물러난다. 판정 표면(Verifier·loki)에는 어느 등급에서도 안 들어간다 (skill_bank 헌법)."""
    value = str(os.environ.get(AUTONOMY_ENV) or "").strip().lower()
    if value in AUTONOMY_MODES:
        return value
    try:
        from .settings import load_global

        setting = str((load_global().get("evolution") or {}).get("autonomy", "safe")).strip().lower()
    except Exception:
        return "safe"
    return setting if setting in AUTONOMY_MODES else "safe"


def autoapprove(root: str, mined: list[dict]) -> list[dict]:
    """방금 캔 초안 중 등급 자격분을 스스로 설치한다 — 반환 = 실제로 설치된 후보 메타.

    **이번 스캔이 캔 것만** 본다. 인박스에 이미 있던 초안은 사람이 읽고 그대로 둔 것일 수
    있고, 그것을 뒤늦게 설치하면 "설치하지 않는다"는 판단을 정책이 뒤집는다. 자율은 새로
    자라는 자리에만 서고 사람이 손댄 자리는 사람의 것으로 남긴다.

    설치 실패(약한 트리거·이름 충돌)는 조용히 넘긴다 — 초안은 pending 에 그대로 있고 사람이
    `evolve list` 에서 같은 것을 본다."""
    allowed = _AUTONOMY_ORIGINS.get(autonomy_mode(), frozenset())
    if not allowed or not mined:
        return []
    installed: list[dict] = []
    for meta in mined:
        if str(meta.get("origin") or "") not in allowed:
            continue
        try:
            ok, _msg = approve(root, str(meta.get("id") or ""), auto=True)
        except Exception:
            continue  # 성장 실패가 턴을 막지 않는다
        if ok:
            installed.append(meta)
    return installed


def _latched(root: str, digest: str, count: int) -> bool:
    """같은 집합으로 두 번 말하지 않기 — 반복 넛지는 거부 피로를 만든다."""
    state_path = os.path.join(root, ".asgard", "state", "evolve-nudge.json")
    try:
        if (io_files.read_json(state_path) or {}).get("digest") == digest:
            return True
    except AttributeError:
        pass
    try:
        io_files.write_json(
            state_path,
            {"digest": digest, "count": count, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            indent=None,
        )
    except OSError:
        return True  # latch를 기록할 수 없으면 침묵 — 반복 넛지가 침묵보다 나쁘다
    return False


def nudge_line(root: str) -> str | None:
    """채굴하고, **승인 대기 초안**을 한 줄로 — 대기 집합이 변했을 때만 (latch).

    네 모드가 전부 이 한 지점을 지난다: 외부 클라이언트는 Stop 훅(memory-activate)이
    `asgard evolve nudge`로, 네이티브 루프는 quest close에서 직접 부른다.

    종전에는 "미채굴 신호가 있다"고 알리고 채굴은 사람이 치게 했다 — 그래서 놓친 넛지 하나가
    교훈 하나의 영구 소실이었다. 이제 채굴까지는 하니스가 하고(가역·비활성), 사람에게는
    **승인할 것이 있다**고 말한다. 채굴을 끈 사람에게는 종전 문장 그대로다.

    한 줄이 말해야 하는 것 셋: 기다리는 것이 무엇인가(스킬 초안), 어디서 나왔는가(어느 퀘스트의
    어떤 실패), 승인하면 무엇이 되는가(다음 워커 배차부터 자동으로 쓰인다). 셋 중 하나라도 빠지면
    읽는 사람은 "학습 후보"가 무엇을 가리키는 말인지부터 되물어야 한다 (26-08-11 오딘 지적).

    자율 등급이 켜져 있으면(`autonomy_mode`) 자격분은 여기서 바로 설치되고, 그 턴의 한 줄은
    대기 안내가 아니라 **무엇이 늘었는지**를 말한다."""
    mined = autoscan(root)
    installed = autoapprove(root, mined)
    items = pending_list(root)
    if installed:
        return _installed_line(installed, len(items))
    if items:
        ids = sorted(str(item.get("id") or "") for item in items)
        digest = hashlib.sha1("\0".join(ids).encode()).hexdigest()
        if _latched(root, digest, len(items)):
            return None
        return f"진화 인박스 — 스킬 초안 {len(items)}건이 승인을 기다린다{_fresh(mined)}. {_INBOX_TAIL}"
    qdir = os.path.join(root, ".asgard", "quest")
    seen = _load_seen(root)
    signals = sorted(
        sig["signal"]
        for fname in (os.listdir(qdir) if os.path.isdir(qdir) else [])
        if fname.endswith(".jsonl")
        for sig in [_quest_signal(_read_quest(os.path.join(qdir, fname)))]
        if sig and sig["signal"] not in seen
    )
    signals += sorted(
        str(row["signal"]) for row in _corrections(root) if row.get("signal") and str(row["signal"]) not in seen
    )
    if not signals:
        return None
    digest = hashlib.sha1("\0".join(signals).encode()).hexdigest()
    if _latched(root, digest, len(signals)):
        return None
    return (
        f"진화 인박스 — 실패를 딛고 통과한 퀘스트 {len(signals)}건이 아직 초안이 안 됐다. "
        "`asgard evolve scan` 이 초안을 뜨고, 그 뒤는 승인해야 실린다."
    )


# 승인이 무엇을 하는지 한 번은 적는다 — 이 줄을 읽는 사람 대부분은 인박스를 처음 본다.
_INBOX_TAIL = "승인하면 그 뒤 워커 배차부터 자동으로 쓰이고, 안 하면 아무 데도 안 쓰인다 — `asgard evolve list`"


def _installed_line(installed: list[dict], waiting: int) -> str:
    """스스로 설치한 스킬을 알리는 한 줄. latch 를 안 건다 — 설치는 능력이 늘어난 사건이라
    사람이 못 보고 지나가면 안 되고, 같은 스킬이 두 번 설치되는 경로도 없다."""
    names = ", ".join(str(m.get("name") or "?") for m in installed[:2])
    more = f" 외 {len(installed) - 2}건" if len(installed) > 2 else ""
    tail = f" 초안 {waiting}건은 그대로 승인을 기다린다 — `asgard evolve list`." if waiting else ""
    return (
        f"진화 — 학습 스킬 {len(installed)}건을 스스로 설치했다 ({names}{more}). 다음 워커 배차부터 쓰이고, "
        f"물리려면 `asgard evolve archive <이름>` (등급 {autonomy_mode()} — 설정 `evolution.autonomy`).{tail}"
    )


def _fresh(mined: list[dict]) -> str:
    """방금 뜬 초안이 어느 퀘스트의 무엇에서 나왔는지. 없으면 빈 문자열."""
    if not mined:
        return ""
    row = mined[0]
    where = str(row.get("quest_id") or "") or str(row.get("origin") or "")
    fails = row.get("fail_count")
    detail = f"{where} — 실패 {fails}회 뒤 통과" if where and isinstance(fails, int) else where
    head = f" (방금 {len(mined)}건: `{row.get('name')}`"
    return head + (f" ← {detail})" if detail else ")")


def pending_list(root: str) -> list[dict]:
    d = _evo_dir(root, PENDING)
    if not os.path.isdir(d):
        return []
    out = []
    for cid in sorted(os.listdir(d)):
        try:
            out.append(io_files.read_json(os.path.join(d, cid, "meta.json"), {}))
        except OSError:
            continue
    return out


def show(root: str, cid: str) -> str | None:
    return io_files.read_text(_evo_dir(root, PENDING, cid, SKILL_FILE)) or None


def approve(root: str, cid: str, *, auto: bool = False) -> tuple[bool, str]:
    """승인 — dry-run 검증 통과 시 learned 스킬 뱅크로 설치. (성공, 메시지) 반환.

    이곳이 pending → 활성의 유일한 관문이다. `auto=True` 는 그 관문을 여는 손이 사람이
    아니라 정책이었다는 표식일 뿐이고(`autonomy_mode`), 아래 검사는 한 자리도 안 건너뛴다.
    누가 눌렀는지는 영수증과 seen 기록에 남아 나중에 되짚을 수 있다."""
    text = show(root, cid)
    if text is None:
        return False, f"후보 없음: {cid} (asgard evolve list로 확인)"
    parsed = parse_skill_md(text)
    if not parsed:
        return False, "frontmatter 불량 — name/triggers 필수. pending SKILL.md를 고친 뒤 재시도."
    meta, _body = parsed
    name = str(meta["name"])
    loose = weak_triggers(meta["triggers"])
    if loose:
        return False, (
            f"이 트리거로는 재발을 못 알아본다: {', '.join(loose)} — 무엇에나 걸리거나 아무것에도 안 "
            "걸린다. 코드가 부르는 이름으로 바꿔라 (파일 이름·함수 이름·실패 서명). 짧은 이름은 자리를 "
            "붙여 늘린다 (`k6` → `asgard-k6`)."
        )
    if name in learned_skills(root):
        return False, f"이름 충돌: learned 스킬 '{name}'이 이미 있다."
    if name in _bundled_names():
        return False, f"이름 충돌: 번들 스킬 '{name}'과 겹친다."
    dst = os.path.join(root, ".asgard", "skills", name)
    os.makedirs(dst, exist_ok=True)
    io_files.write_text(os.path.join(dst, SKILL_FILE), text)
    approval = approval_receipt(
        root,
        name,
        text,
        create_key=True,
        approved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        candidate_id=cid,
        approved_by="policy" if auto else "user",
    )
    io_files.write_json(os.path.join(dst, APPROVAL_FILE), approval, indent=None, sort_keys=True)
    src = _evo_dir(root, PENDING, cid)
    cmeta = io_files.read_json(os.path.join(src, "meta.json"), {"id": cid, "signal": cid})
    seen = _load_seen(root)
    seen[str(cmeta.get("signal", cid))] = {
        "status": "approved",
        "id": cid,
        "name": name,
        "by": "policy" if auto else "user",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save_seen(root, seen)
    shutil.rmtree(src, ignore_errors=True)
    # 클라이언트 서브에이전트는 스킬 명단을 자기 파일에서 읽는다. 그 파일은 설치 시점에 구워지므로
    # 여기서 다시 그리지 않으면 방금 깐 스킬이 다음 `asgard sync` 까지 배차에 안 보인다
    # (26-08-12 실측: 워커 둘 다 이 스킬을 못 받았고 명단에도 없었다). 실패는 삼킨다 — 명단이
    # 낡는 것과 설치가 안 되는 것 중에는 앞이 낫다.
    with contextlib.suppress(Exception):
        from .commands.setup import refresh_role_agents

        refresh_role_agents(root)
    return True, f"설치됨: .asgard/skills/{name}/ — 다음 디스패치부터 자동 라우팅 (재시작 불필요)"


def reject(root: str, cid: str, reason: str = "") -> tuple[bool, str]:
    """거부 — latch 기록 (동일 신호 재제안 금지) + 후보는 rejected/ 로 보존 (감사 가능)."""
    src = _evo_dir(root, PENDING, cid)
    if not os.path.isdir(src):
        return False, f"후보 없음: {cid}"
    cmeta = io_files.read_json(os.path.join(src, "meta.json"), {"signal": cid})
    seen = _load_seen(root)
    seen[str(cmeta.get("signal", cid))] = {
        "status": "rejected",
        "id": cid,
        "reason": reason[:300],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save_seen(root, seen)
    dst = _evo_dir(root, REJECTED, cid)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.move(src, dst)
    return True, f"거부됨 — 같은 신호는 다시 제안하지 않는다{' (' + reason[:80] + ')' if reason else ''}"


def reset(root: str) -> tuple[int, int, list[str]]:
    """인박스를 비우고 다시 채굴할 수 있게 연다. 반환 = (치운 초안 수, 푼 latch 수, 초안 이름들).

    왜 필요한가. 초안의 모양은 생성기가 정하는데 생성기는 고쳐진다 — 26-08-11 에 트리거 규칙이
    산문 낱말에서 이름 축으로 바뀌자, 그 전에 뜬 초안 다섯이 전부 승인 문턱에 걸린 채 인박스에
    남았다. 그것들은 고칠 값이 있는 문서가 아니라 옛 규칙의 산물이고, 같은 퀘스트 로그에서 새
    규칙으로 다시 뜨는 편이 낫다. 그런데 `seen` latch 가 "이 신호는 이미 제안했다"를 붙들고 있어
    재채굴이 막힌다 — 그 latch 를 사람이 손으로 지우게 두면 `.asgard` 를 직접 여는 습관이 생긴다.

    **아무것도 잃지 않는다.** 초안은 `rejected/` 로 옮겨 그대로 남고(감사 가능), latch 는 퀘스트
    로그와 `corrections.jsonl` 에서 언제든 다시 만들어지는 파생물이다. 이미 설치된 learned 스킬은
    이 함수가 아예 안 본다 — 그쪽을 내리는 것은 `archive_skill` 의 일이다.
    """
    stamp = time.strftime("%Y%m%d%H%M%S")
    names = []
    for meta in pending_list(root):
        cid = str(meta.get("id") or "")
        if not cid:
            continue
        src, dst = _evo_dir(root, PENDING, cid), _evo_dir(root, REJECTED, f"{cid}-{stamp}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        names.append(str(meta.get("name") or cid))
    seen = _load_seen(root)
    # 사람이 내린 판단은 초기화가 안 지운다. 승인은 이미 스킬이 서 있어서 다시 제안하면 이름이
    # 충돌하고, 거절은 `reject` 가 "같은 신호는 다시 제안하지 않는다"고 약속한 자리다 — 그 약속과
    # 거절 사유는 `seen.json` 에만 있어서 여기서 지우면 사람이 한 번 내친 초안이 다시 올라온다.
    # 초기화가 푸는 것은 기계가 붙인 `proposed` 뿐이다.
    kept = {sig: row for sig, row in seen.items() if str((row or {}).get("status")) in ("approved", "rejected")}
    freed = len(seen) - len(kept)
    _save_seen(root, kept)
    _clear_nudge_latch(root)
    return (len(names), freed, names)


def _clear_nudge_latch(root: str) -> None:
    """넛지 지문도 같이 지운다 — 안 지우면 초기화 뒤 첫 채굴이 "같은 집합" 으로 읽혀 조용하다."""
    try:
        os.remove(os.path.join(root, ".asgard", "state", "evolve-nudge.json"))
    except OSError:
        pass  # 없으면 지울 것도 없다 — 초기화가 이 한 줄로 실패하지 않는다


def archive_skill(root: str, name: str) -> tuple[bool, str]:
    """보관 전이 — 삭제 없는 비활성화 (라우팅 스캔이 .archive를 건너뛴다). 복원 = 되돌리기."""
    src = os.path.join(root, ".asgard", "skills", name)
    if not os.path.isdir(src):
        return False, f"learned 스킬 없음: {name}"
    dst = os.path.join(root, ".asgard", "skills", ".archive", f"{name}-{time.strftime('%Y%m%d%H%M%S')}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return True, f"보관됨: {dst} (복원: asgard evolve restore {name})"


def restore_skill(root: str, name: str) -> tuple[bool, str]:
    """보관 해제 — 최신 아카이브 스냅샷을 활성 위치로 복귀 (충돌 검증 포함)."""
    adir = os.path.join(root, ".asgard", "skills", ".archive")
    snaps = sorted(
        d for d in (os.listdir(adir) if os.path.isdir(adir) else []) if re.fullmatch(rf"{re.escape(name)}-\d{{14}}", d)
    )
    if not snaps:
        return False, f"아카이브에 없음: {name}"
    dst = os.path.join(root, ".asgard", "skills", name)
    if os.path.isdir(dst):
        return False, f"활성 스킬 '{name}'이 이미 있다 — 먼저 archive 하거나 이름을 정리하라."
    if name in _bundled_names():
        return False, f"이름 충돌: 번들 스킬 '{name}'과 겹친다 (아카이브 중 번들이 추가됨)."
    shutil.move(os.path.join(adir, snaps[-1]), dst)
    return True, f"복원됨: .asgard/skills/{name}/ — 다음 디스패치부터 다시 라우팅 (최신 스냅샷 {snaps[-1]})"


def _bundled_names() -> frozenset[str]:
    """번들 스킬 이름 — 충돌 방지용 (lazy import — 상수 본문이 크다)."""
    try:
        from .templates.bragi import BRAGI_SKILLS
        from .templates.eitri import EITRI_SKILLS
        from .templates.freyja import FREYJA_SKILLS
        from .templates.lagom import LAGOM_SKILLS
        from .templates.mimir import MIMIR_SKILLS
        from .templates.thor import THOR_SKILLS
        from .templates.worker import WORKER_SKILLS

        return frozenset(
            n
            for n, _ in [
                *FREYJA_SKILLS,
                *THOR_SKILLS,
                *EITRI_SKILLS,
                *MIMIR_SKILLS,
                *WORKER_SKILLS,
                *LAGOM_SKILLS,
                *BRAGI_SKILLS,
            ]
        )
    except Exception:
        return frozenset()
