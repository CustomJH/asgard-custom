"""evolution — 회고 증류기 + 진화 인박스 (자가발전 C1/C2, CUS-253·254).

quest 로그(.asgard/quest/*.jsonl)에서 hard-won 신호(실패를 딛고 PASS 에 도달한 퀘스트)만
결정론적으로 선별해 스킬 초안을 만들고, .asgard/evolution/pending/ 인박스에 스테이징한다.
승인(asgard evolve approve)만이 learned 스킬 뱅크(.asgard/skills/)로 설치하는 유일한 경로다.

설계 근거 (CUS-251 리서치):
- 선별은 결정론, 가치 판단은 사용자 — 저신호 휴리스틱 양산은 승인율을 0 으로 만든다는
  실증 교훈. 여기서는 "FAIL→PASS 전환"이라는 고신호만 후보가 된다 (hard-won 교훈).
- 캡처 금지 필터 — 환경 의존 실패·일시 장애는 스킬이 아니다 (실전 교훈: 도구 부정 주장을
  캡처하면 몇 달간 자기 인용해 스스로 거부하게 된다).
- 거부 신호는 latch — 같은 신호를 다시 제안하지 않는다 (consent-first, 제안 피로 방지).
- 초안은 증거 카드 (실측 failure_sig·통과 명령·criteria) — 추측 서사를 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time

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


def _evo_dir(root: str, *parts: str) -> str:
    return os.path.join(root, ".asgard", EVO_DIR, *parts)


def _load_seen(root: str) -> dict:
    try:
        d = json.load(open(_evo_dir(root, SEEN_FILE), encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_seen(root: str, seen: dict) -> None:
    os.makedirs(_evo_dir(root), exist_ok=True)
    p = _evo_dir(root, SEEN_FILE)
    tmp = f"{p}.{os.getpid()}.tmp"
    json.dump(seen, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _read_quest(path: str) -> list[dict]:
    events = []
    try:
        for line in open(path, encoding="utf-8"):
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
        # 함정 섹션 수록분도 금지 필터 적용 — 마지막 sig 만 걸러도 앞선 환경 노이즈가
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
# (false positive 1건이 승인 피로 10건보다 나쁘다). 처분은 기존 인박스 계약 그대로:
# 후보 스테이징 → 사람 승인만이 활성화.

_CORRECTION_PATTERNS = (
    re.compile(r"(그게|그거|그건)\s*아니"),
    re.compile(r"아니(야|라니까)\b"),
    re.compile(r"하지\s*마"),
    re.compile(r"(말고|대신)\s+\S.{0,60}?(해줘|해라|하세요|해야|할 것|로 해)"),
    re.compile(r"(로|으로)\s*해\s*줘?\s*[.!]?\s*$"),
    re.compile(r"\bstop doing\b|\bdon'?t do that\b|\bnot what i (asked|meant)\b", re.IGNORECASE),
)
_CORRECTION_MAX_CHARS = 500  # 정정은 짧다 — 장문은 설명/새 요청일 확률이 높다


def correction_signal(user_text: str) -> str | None:
    """정정 발화 판정 (0-LLM) — 매치 구절을 반환, 아니면 None. 보수적: 장문·위협 패턴 배제."""
    text = (user_text or "").strip()
    if not text or len(text) > _CORRECTION_MAX_CHARS:
        return None
    for pattern in _CORRECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)[:40]
    return None


def record_correction(root: str, user_text: str, assistant_text: str = "") -> bool:
    """정정 발화를 corrections.jsonl 에 스테이징한다 (탐지 실패·중복·위협 = False, 무해).

    저장은 신호 원문뿐 — 스킬 초안 변환은 mine() 이 latch 와 함께 수행한다."""
    try:
        phrase = correction_signal(user_text)
        if not phrase:
            return False
        from .memory import scan_secrets, scan_threats

        if scan_threats(user_text) or scan_secrets(user_text):
            return False  # 오염 발화는 증거로도 싣지 않는다
        signal = "correction:" + hashlib.sha1(user_text.strip().encode()).hexdigest()[:12]
        os.makedirs(_evo_dir(root), exist_ok=True)
        path = _evo_dir(root, CORRECTIONS_FILE)
        rows: list[dict] = []
        try:
            rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
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
        return [json.loads(line) for line in open(_evo_dir(root, CORRECTIONS_FILE), encoding="utf-8") if line.strip()]
    except OSError, ValueError:
        return []


def _correction_draft(row: dict) -> tuple[str, str]:
    """정정 신호 → (스킬명, SKILL.md 초안). 증거 카드 — 사용자 원문이 정본이다."""
    quote = row.get("user_text", "")
    name = "learned-" + _slug(quote, "correction")
    triggers = _tokens(quote + " " + row.get("assistant_head", ""))[:6] or ["재발-트리거-직접-기입"]
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
        "  일반화 원칙으로 다듬어라 (특히 triggers 와 description).",
        "",
    ]
    return name, "\n".join(body)


def _tokens(text: str) -> list[str]:
    """트리거 후보 토큰 — ascii 4자+ 또는 한글 2자+ 단어, 불용어 제외 (결정론)."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9_.-]{3,}|[가-힣]{2,}", text)
    out: list[str] = []
    for w in words:
        lw = w.lower().strip(".-_")
        if lw and lw not in _STOPWORDS and lw not in out:
            out.append(lw)
    return out


def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9가-힣]+", "-", text.lower()).strip("-")[:40].strip("-")
    return s or fallback


def _draft(sig: dict) -> tuple[str, str]:
    """신호 → (스킬명, SKILL.md 초안). 증거 카드 — 실측 데이터만 서술, 추측 금지."""
    cid_seed = sig["signal"]
    name = "learned-" + _slug(sig["failure_sig"] or (sig["subtasks"][0] if sig["subtasks"] else ""), "quest")
    trig_src = " ".join([sig["failure_sig"]] + sig["subtasks"] + sig["criteria"])
    triggers = _tokens(trig_src)[:6] or ["재발-트리거-직접-기입"]
    desc_src = sig["subtasks"][0] if sig["subtasks"] else (sig["criteria"][0] if sig["criteria"] else sig["signal"])
    esc = " (ESCALATE 경유)" if sig["escalated"] else ""
    body = [
        "---",
        f"name: {name}",
        f"description: {desc_src[:150]} — FAIL {sig['fail_count']}회{esc} 후 PASS 로 도달한 교훈",
        f"triggers: {', '.join(triggers)}",
        "agent: worker",
        "origin: retrospective",
        f"created: {time.strftime('%Y-%m-%d')}",
        f"evidence: {sig['quest_id']}",
        "---",
        "",
        "## 함정 (먼저 실패한 지점)",
        *(f"- {w}" for w in (sig["fail_whys"] or ["(failure_sig 미기록 — 퀘스트 로그 참조)"])),
        "",
        "## 전략 (결국 통과한 접근)",
        *(f"- criteria: {c}" for c in sig["criteria"]),
        *([f"- 대상 파일: {', '.join(sig['changed_files'])}"] if sig["changed_files"] else []),
        "",
        "## 검증 (성공을 입증한 명령)",
        *(f"- `{c}`" for c in (sig["pass_commands"] or ["(명령 미기록)"])),
        "",
        "## 근거",
        f"- quest: {sig['quest_id']} — FAIL {sig['fail_count']}회 → PASS ({sig['task_class'] or 'unknown'})",
        "- 이 카드는 결정론 증거 초안이다 — 승인 전에 전략·함정 서술을 다듬어라 (특히 triggers).",
        "",
    ]
    _ = cid_seed
    return name, "\n".join(body)


def _cand_id(signal: str) -> str:
    return "evo-" + hashlib.sha1(signal.encode()).hexdigest()[:8]


_POLISH_SYS = (
    "스킬 초안 편집기. 입력은 에이전트 세션의 실측 증거로 만든 SKILL.md 초안이다. "
    "같은 SKILL.md 형식으로만 다시 써서 출력한다 (설명·코드펜스 금지, --- frontmatter 로 시작). "
    "규칙: (1) 증거에 없는 사실을 지어내지 않는다 — 전략·함정 서술을 일반화 가능한 원칙 문장으로 "
    "다듬는 것만 허용. (2) frontmatter 의 name/agent/origin/created/evidence 는 그대로 보존. "
    "(3) triggers 는 재발 상황을 잡을 실질 키워드로 개선 가능. (4) description 은 한 문장. "
    "(5) 환경 의존 실패·도구에 대한 부정 주장은 쓰지 않는다."
)


def polish(root: str, cid: str) -> tuple[bool, str]:
    """LLM 증류 (opt-in) — pending 초안을 원칙 수준 서술로 다듬는다. 실패 = 초안 유지 (fail-open).

    닫힌 과업이다: LLM 은 초안 '재작성'만 한다 — 스킬 가치 판단(승인)은 여전히 사용자 몫이고,
    산출물은 pending 에 머무른다 (LLM open-ended 판단 금지, CUS-251)."""
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
        return False, "LLM 이 보존 필드(name)를 바꿈 — 결정론 초안 유지 (satisficing backstop)"
    p = _evo_dir(root, PENDING, cid, SKILL_FILE)
    orig = f"{p}.orig"
    if not os.path.exists(orig):  # 결정론 초안 백업 — latch 때문에 재생성 불가, 내용 열화 시 복구선
        open(orig, "w", encoding="utf-8").write(draft)
    tmp = f"{p}.{os.getpid()}.tmp"
    open(tmp, "w", encoding="utf-8").write(raw[start:].rstrip() + "\n")
    os.replace(tmp, p)
    return True, f"증류 완료 — {cid} 초안이 다듬어졌다 (여전히 pending, 승인 필요. 원본: SKILL.md.orig)"


def _stage_candidate(root: str, seen: dict, signal: str, name: str, skill_md: str, meta_extra: dict) -> dict:
    """후보 1건을 pending 에 스테이징 + seen latch. 반환 = 후보 메타 (채굴원 공용)."""
    cid = _cand_id(signal)
    d = _evo_dir(root, PENDING, cid)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, SKILL_FILE), "w", encoding="utf-8").write(skill_md)
    meta = {
        "id": cid,
        "name": name,
        "signal": signal,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **meta_extra,
    }
    json.dump(meta, open(os.path.join(d, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
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


def nudge_line(root: str) -> str | None:
    """미채굴 신호 넛지 한 줄 — 신호 집합이 변했을 때만 (latch, 제안 피로 방지).

    CC 모드 Stop 훅(memory-activate)이 소비한다 — 네이티브 루프는 quest close 시점에
    unmined_signals 를 직접 넛지하므로(heimdall/trinity) 이 latch 를 쓰지 않는다.
    같은 신호 집합으로는 두 번 말하지 않는다 — 매 턴 반복 넛지는 거부 피로를 만든다."""
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
    state_dir = os.path.join(root, ".asgard", "state")
    state_path = os.path.join(state_dir, "evolve-nudge.json")
    try:
        if json.load(open(state_path, encoding="utf-8")).get("digest") == digest:
            return None
    except Exception:
        pass
    try:
        os.makedirs(state_dir, exist_ok=True)
        tmp = f"{state_path}.{os.getpid()}.tmp"
        json.dump(
            {"digest": digest, "count": len(signals), "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            open(tmp, "w", encoding="utf-8"),
        )
        os.replace(tmp, state_path)
    except OSError:
        return None  # latch 를 기록할 수 없으면 침묵 — 반복 넛지가 침묵보다 나쁘다
    return f"진화 후보 신호 {len(signals)}건 — asgard evolve scan 으로 채굴 후 검토·승인 (hard-won 교훈)"


def pending_list(root: str) -> list[dict]:
    d = _evo_dir(root, PENDING)
    if not os.path.isdir(d):
        return []
    out = []
    for cid in sorted(os.listdir(d)):
        try:
            out.append(json.load(open(os.path.join(d, cid, "meta.json"), encoding="utf-8")))
        except Exception:
            continue
    return out


def show(root: str, cid: str) -> str | None:
    p = _evo_dir(root, PENDING, cid, SKILL_FILE)
    try:
        return open(p, encoding="utf-8").read()
    except OSError:
        return None


def approve(root: str, cid: str) -> tuple[bool, str]:
    """승인 — dry-run 검증 통과 시 learned 스킬 뱅크로 설치. (성공, 메시지) 반환.

    이곳이 pending → 활성의 유일한 관문이다 (자동 활성화 경로 없음, CUS-251 헌법)."""
    text = show(root, cid)
    if text is None:
        return False, f"후보 없음: {cid} (asgard evolve list 로 확인)"
    parsed = parse_skill_md(text)
    if not parsed:
        return False, "frontmatter 불량 — name/triggers 필수. pending SKILL.md 를 고친 뒤 재시도."
    meta, _body = parsed
    name = str(meta["name"])
    if "재발-트리거-직접-기입" in meta["triggers"]:
        return False, "triggers 가 placeholder 그대로다 — 실제 재발 키워드로 바꾼 뒤 재시도."
    if name in learned_skills(root):
        return False, f"이름 충돌: learned 스킬 '{name}' 이 이미 있다."
    if name in _bundled_names():
        return False, f"이름 충돌: 번들 스킬 '{name}' 과 겹친다."
    dst = os.path.join(root, ".asgard", "skills", name)
    os.makedirs(dst, exist_ok=True)
    tmp = os.path.join(dst, f".{SKILL_FILE}.tmp")
    open(tmp, "w", encoding="utf-8").write(text)
    os.replace(tmp, os.path.join(dst, SKILL_FILE))
    approval = approval_receipt(
        root,
        name,
        text,
        create_key=True,
        approved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        candidate_id=cid,
    )
    approval_tmp = os.path.join(dst, f".{APPROVAL_FILE}.tmp")
    open(approval_tmp, "w", encoding="utf-8").write(json.dumps(approval, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(approval_tmp, os.path.join(dst, APPROVAL_FILE))
    src = _evo_dir(root, PENDING, cid)
    try:
        cmeta = json.load(open(os.path.join(src, "meta.json"), encoding="utf-8"))
    except Exception:
        cmeta = {"id": cid, "signal": cid}
    seen = _load_seen(root)
    seen[str(cmeta.get("signal", cid))] = {
        "status": "approved",
        "id": cid,
        "name": name,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save_seen(root, seen)
    shutil.rmtree(src, ignore_errors=True)
    return True, f"설치됨: .asgard/skills/{name}/ — 다음 디스패치부터 자동 라우팅 (재시작 불요)"


def reject(root: str, cid: str, reason: str = "") -> tuple[bool, str]:
    """거부 — latch 기록 (동일 신호 재제안 금지) + 후보는 rejected/ 로 보존 (감사 가능)."""
    src = _evo_dir(root, PENDING, cid)
    if not os.path.isdir(src):
        return False, f"후보 없음: {cid}"
    try:
        cmeta = json.load(open(os.path.join(src, "meta.json"), encoding="utf-8"))
    except Exception:
        cmeta = {"signal": cid}
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


def archive_skill(root: str, name: str) -> tuple[bool, str]:
    """보관 전이 — 삭제 없는 비활성화 (라우팅 스캔이 .archive 를 건너뛴다). 복원 = 되돌리기."""
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
        return False, f"활성 스킬 '{name}' 이 이미 있다 — 먼저 archive 하거나 이름을 정리하라."
    if name in _bundled_names():
        return False, f"이름 충돌: 번들 스킬 '{name}' 과 겹친다 (아카이브 중 번들이 추가됨)."
    shutil.move(os.path.join(adir, snaps[-1]), dst)
    return True, f"복원됨: .asgard/skills/{name}/ — 다음 디스패치부터 다시 라우팅 (최신 스냅샷 {snaps[-1]})"


def _bundled_names() -> frozenset[str]:
    """번들 스킬 이름 — 충돌 방지용 (lazy import — 상수 본문이 크다)."""
    try:
        from .templates.eitri import EITRI_SKILLS
        from .templates.freyja import FREYJA_SKILLS
        from .templates.lagom import LAGOM_SKILLS
        from .templates.mimir import MIMIR_SKILLS
        from .templates.thor import THOR_SKILLS
        from .templates.worker import WORKER_SKILLS

        return frozenset(
            n for n, _ in [*FREYJA_SKILLS, *THOR_SKILLS, *EITRI_SKILLS, *MIMIR_SKILLS, *WORKER_SKILLS, *LAGOM_SKILLS]
        )
    except Exception:
        return frozenset()
