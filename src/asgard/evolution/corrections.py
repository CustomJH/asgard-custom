"""사용자 정정 발화 탐지와 `corrections.jsonl` 기록 — 제2 채굴원의 입구."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time

from .store import _CORRECTIONS_CAP, CORRECTIONS_FILE, _evo_dir

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


def record_correction(root: str, user_text: str, assistant_text: str = "", *, assistant_before: str = "") -> bool:
    """정정 발화를 corrections.jsonl에 스테이징한다 (탐지 실패·중복·위협 = False, 무해).

    저장은 신호 원문뿐 — 스킬 초안 변환은 mine()이 latch와 함께 수행한다.

    응답을 둘 적는다. `assistant_before` 는 정정을 **부른** 답이고 `assistant_text` 는 정정을
    **받고 낸** 답이다. 훅이 넘기는 짝은 뒤쪽뿐이라 종전에는 그것을 "직전 맥락"이라 적었는데,
    그건 이미 고쳐진 답이라 카드가 수정 결과를 실수로 지목했다."""
    try:
        phrase = correction_signal(user_text)
        if not phrase:
            return False
        from ..memory import scan_secrets, scan_threats

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
                "assistant_before": re.sub(r"\s+", " ", (assistant_before or "").strip())[:400],
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
