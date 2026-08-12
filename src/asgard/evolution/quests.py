"""퀘스트 로그(.asgard/quest/*.jsonl) 읽기 — 한 퀘스트를 hard-won 신호 하나로 줄인다."""

from __future__ import annotations

import json
import re

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

    조건: 최종 verdict PASS + 도중 실패 존재. 실패는 판정이 낸 FAIL·ESCALATE 와 failure-tracker
    가 적은 `event="fail"` 둘 다 센다. 금지 시그니처면 제외."""
    if not events:
        return None
    verdicts = [e for e in events if e.get("verdict") in ("PASS", "FAIL", "ESCALATE")]
    if not verdicts or verdicts[-1]["verdict"] != "PASS":
        return None
    fails = [e for e in verdicts if e["verdict"] in ("FAIL", "ESCALATE")]
    # 판정이 낸 실패만 세면 워커가 스스로 뚫고 나온 실패가 통째로 안 보인다. failure-tracker 는
    # 같은 도구·같은 오류 종류가 3회 반복될 때 `event="fail"` 을 이 로그에 적는데(Canon 9),
    # 그 이벤트의 verdict 는 NA 라 위 목록에 안 들어온다. 그래서 "워커가 세 번 막히고 고친 뒤
    # 첫 판정에 통과한" 퀘스트는 — 교훈이 가장 구체적인 바로 그 모양인데 — 후보를 한 건도 안
    # 낸다. 도구 실패 서명도 실패 증거로 같이 센다.
    #
    # 세는 범위는 **마지막 PASS 앞**이다. 통과한 뒤에 적힌 도구 실패는 이 퀘스트가 이겨 낸
    # 실패가 아니라 그 다음에 벌어진 일이라, 세면 "무엇을 뚫고 통과했는가"가 아닌 카드가 뜬다.
    # 금지 필터도 여기서 먼저 건다: 도구 오류는 환경 사정(미설치·권한·네트워크)이 섞이는
    # 자리라 거르지 않으면 그날의 사정이 카드가 된다.
    last_pass_i = max(i for i, e in enumerate(events) if e.get("verdict") == "PASS")
    tool_fails = [
        e
        for e in events[:last_pass_i]
        if e.get("event") == "fail" and e.get("failure_sig") and not _FORBIDDEN_SIG.search(str(e["failure_sig"]))
    ]
    if not fails and not tool_fails:
        return None  # 순탄한 PASS = 교훈 없음
    sig = next((str(e.get("failure_sig") or "") for e in reversed(fails) if e.get("failure_sig")), "")
    if not sig:
        sig = next((str(e["failure_sig"]) for e in reversed(tool_fails)), "")
    if sig and _FORBIDDEN_SIG.search(sig):
        return None
    final = verdicts[-1]
    pass_cmds = [c for c in (final.get("commands") or []) if isinstance(c, dict) and c.get("exit_code") == 0]
    subtasks = [str(e.get("subtask") or "") for e in events if e.get("subtask")]
    return {
        "quest_id": str(events[0].get("quest_id") or ""),
        "signal": sig or f"quest:{events[0].get('quest_id', '')}",
        "failure_sig": sig,
        "fail_count": len(fails) + len(tool_fails),
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
            for e in [*fails, *tool_fails]
            if e.get("failure_sig") and not _FORBIDDEN_SIG.search(str(e["failure_sig"]))
        ][:4],
    }
