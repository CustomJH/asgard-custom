"""Charter (프로젝트 북극성) — 프로젝트를 관통하는 through-line 한 줄 + 일관성 기준.

배경: "시작 전 프로젝트를 관통하는 세계관을 한 줄로, 추상 기준을 기계가 읽는 형태로, 그 기준으로
결과 일관성을 판단한다"는 사상의 Trinity 편입. 대부분(협업=criteria 환원, 연결=크로스툴 공유,
확장=priors/map)은 이미 evidence-first 관용구로 존재한다 — 이 모듈이 채우는 **진짜 갭은 하나**:
과업을 넘어 지속되는 프로젝트 관통 원칙(설계①)과 그것을 판단 렌즈로 쓰는 것(판단③).

적합성 경계 (검증됨): Trinity 의 핵심 계약은 "게이트는 증거만 신뢰"다. Charter 는 그 계약을
**대체하지 않는다** — Thinker 에겐 계획 앵커(coherence 를 concrete criteria 로 환원하라),
Verifier 에겐 반례 렌즈(명백 위반은 고확신 반례로만)로 주입될 뿐, 게이트가 강제하는 criteria 를
자동 생성하지 않는다. `lagom:` 마커가 "검증 면제가 아니다"인 것과 같은 프레이밍.

저장: `.asgard/asgard-setting-project.json` 의 `charter` 섹션 (git 추적 → 크로스툴로 따라감).
  {"charter": {"through_line": "한 줄", "coherence": ["체크 가능한 일관성 기준", ...]}}
문자열 단독("한 줄")도 허용 — through_line 만 있는 축약형.
"""

from __future__ import annotations

SECTIONS = ("identity", "thinker", "verifier")


def load_charter(root: str | None = None) -> dict | None:
    """프로젝트 charter 해석 — 정규화된 {through_line, coherence} 또는 None (미설정/공백/파손).

    fail-open: 설정이 없거나 깨졌으면 None — 프롬프트 무변화(토큰 회귀 없음), 루프는 그대로 돈다."""
    try:
        from .settings import load_project

        raw = load_project(root or "").get("charter")
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


def _coherence_block(items: list[str]) -> str:
    return "\n".join(f"  · {c}" for c in items[:8])  # 상한 — 프롬프트 팽창 방지


def note(root: str | None = None, section: str = "identity") -> str:
    """역할별 charter 주입분 — charter 미설정이면 빈 문자열 (프롬프트 무변화).

    identity : through-line 만 — DIRECT·모든 역할에 관통 원칙 제공 (설계①, 캐시 안정 상수).
    thinker  : through-line + coherence → 계획 앵커 + criteria 환원 지시 (협업②).
    verifier : through-line + coherence → 반례 렌즈, 게이트 대체 금지 명시 (판단③, evidence-first 보존)."""
    ch = load_charter(root)
    if not ch:
        return ""
    through, coherence = ch["through_line"], ch["coherence"]
    if section == "identity":
        if not through:
            return ""
        return (
            f"\n\n## Project North Star (Charter)\nThrough-line: {through}\n"
            "Do not choose a direction that contradicts this principle — surface any conflict."
        )
    if section == "thinker":
        parts = ["\n\n## Project North Star (Charter)"]
        if through:
            parts.append(f"Through-line: {through}")
        if coherence:
            parts.append(
                "Coherence criteria — reduce the items this quest touches into **assigned-unit criteria** "
                "(no abstract wording; use verification commands):\n" + _coherence_block(coherence)
            )
        return "\n".join(parts)
    if section == "verifier":
        parts = ["\n\n## Project North Star (Charter) — counterexample lens"]
        if through:
            parts.append(f"Through-line: {through}")
        if coherence:
            parts.append("Coherence criteria:\n" + _coherence_block(coherence))
        parts.append(
            "A change that **clearly** violates this principle FAILs with a reproducible, high-confidence "
            "counterexample. But the Charter does not replace criteria — the verdict basis "
            "(evidence · criteria · diff-hash) stays as-is; a low-confidence 'feels off' is not a FAIL reason."
        )
        return "\n".join(parts)
    return ""
