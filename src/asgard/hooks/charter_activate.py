#!/usr/bin/env python3
# Asgard charter-activate — 프로젝트 북극성(Charter) 주입 (모드 B: Claude Code/Codex/Cursor).
#
# 네이티브 Heimdall 은 charter.py note() 를 프롬프트에 직접 주입하지만, 모드 B 는 서브에이전트가
# AGENTS.md 를 읽는 구조라 닿지 않는다 — lagom/memory 와 동일하게 훅으로 보상한다. 동작:
#   agent_type 없음 (SessionStart/UserPromptSubmit) → through_line 만 stdout 주입 (설계①, 메인 스레드)
#   agent_type 있음 (SubagentStart) → 역할별 JSON additionalContext:
#     asgard-thinker  → through_line + coherence(criteria 환원 지시)  협업②
#     asgard-verifier → through_line + coherence(반례 렌즈, 게이트 대체 아님 명시)  판단③
#     그 외(worker/딜리버리) → through_line 만 — coherence 를 게이트 강제 criteria 로 흘리지 않는다
# 렌더 문구는 asgard/charter.py note() 와 **동일 유지 (단일 출처 원칙)** — 훅은 무임포트라 재구현한다.
# fail-open: charter 부재·파손·훅 오류는 전부 무개입 통과 (exit 0) — 세션을 막지 않는다.
import json
import os
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass


COHERENCE_CAP = 8  # 프롬프트 팽창 방지 — charter.py _coherence_block 과 동일


def load_charter(root):
    """charter.py load_charter 와 동일 유지 — {through_line, coherence:[...]} 또는 None."""
    try:
        with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        raw = cfg.get("charter") if isinstance(cfg, dict) else None
    except Exception:
        return None
    if isinstance(raw, str):
        raw = {"through_line": raw}
    if not isinstance(raw, dict):
        return None
    through = str(raw.get("through_line") or "").strip()
    coherence = [str(c).strip() for c in (raw.get("coherence") or []) if str(c).strip()]
    if not through and not coherence:
        return None
    return {"through_line": through, "coherence": coherence}


def _coherence_block(items):
    return "\n".join("  · %s" % c for c in items[:COHERENCE_CAP])


def render(ch, section):
    """charter.py note() 와 동일 유지 (단일 출처 원칙)."""
    through, coherence = ch["through_line"], ch["coherence"]
    if section == "identity":
        if not through:
            return ""
        return (
            "## 프로젝트 북극성 (Charter)\n관통 원칙: %s\n"
            "이 원칙과 모순되는 방향은 택하지 않는다 — 충돌하면 표면화한다." % through
        )
    if section == "thinker":
        parts = ["## 프로젝트 북극성 (Charter)"]
        if through:
            parts.append("관통 원칙: %s" % through)
        if coherence:
            parts.append(
                "일관성 기준 — 이 과업에 걸리는 항목은 **배정 단위 criteria 로 환원**하라 "
                "(추상어 금지, 검증 명령으로):\n" + _coherence_block(coherence)
            )
        return "\n".join(parts)
    if section == "verifier":
        parts = ["## 프로젝트 북극성 (Charter) — 반례 렌즈"]
        if through:
            parts.append("관통 원칙: %s" % through)
        if coherence:
            parts.append("일관성 기준:\n" + _coherence_block(coherence))
        parts.append(
            "이 원칙을 **명백히** 위반하는 변경은 재현 가능한 고확신 반례로 FAIL 한다. "
            "단 Charter 는 criteria 를 대체하지 않고 판정 기준(증거·criteria·diff-hash)은 그대로다 — "
            "저확신 '결이 다르다'는 FAIL 사유가 아니다."
        )
        return "\n".join(parts)
    return ""


def section_for(agent):
    if agent == "asgard-thinker":
        return "thinker"
    if agent == "asgard-verifier":
        return "verifier"
    if agent == "asgard-worker":
        return ""  # 네이티브 패리티 — Worker 는 worker.md+lagom 만 (charter 무주입, Fugu 격리)
    return "identity"  # 메인·딜리버리(freyja/thor/eitri/loki) — through_line 만 (네이티브 delivery_identity 대응)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        ch = load_charter(root)
        if not ch:
            sys.exit(0)  # charter 미설정 — 무개입 (토큰 회귀 없음)
        agent = str(data.get("agent_type") or "")
        body = render(ch, section_for(agent))
        if not body:
            sys.exit(0)
        if agent:  # SubagentStart — JSON additionalContext (lagom-subagent 스키마)
            sys.stdout.write(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SubagentStart",
                            "additionalContext": "[charter]\n\n%s" % body,
                        }
                    },
                    ensure_ascii=False,
                )
            )
        else:  # SessionStart/UserPromptSubmit — 평문 stdout (lagom-activate 스키마)
            sys.stdout.write("[charter]\n\n%s" % body)
    except Exception:
        pass  # fail-open — 어떤 실패도 세션을 막지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
