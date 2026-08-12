"""탐색 발견 저장 넛지 — 응답에 인용된 실존 경로만 증류해 승인 게이트로 안내한다."""

from __future__ import annotations

import os
import re

from ..policy import autosave_enabled, inject_enabled, scan_threats

DISTILL_MAX_PATHS = 3  # 넛지당 경로 상한 — 위치 지식의 최소 형태만, 목록 폭주 방지


def distill_nudge(request: str, response: str, root: str) -> str:
    """탐색 발견 저장 넛지 (0-LLM) — 응답에 인용된 '실존 파일 경로'만 증류해 기존 ingest
    승인 게이트로 안내한다. 저장은 ask-before-save 그대로 — 여기는 안내문뿐이다.

    응답 유래 자유 텍스트는 명령에 넣지 않는다: 디스크 실존 + root 격리 검증을 통과한
    경로 토큰만 후보가 된다 (모델 응답을 명령 제안으로 렌더링하는 표면의 인젝션 차단).
    숏컷 벤치(26-07-16) 근거 — 위치 지식이 recall 이득(토큰 -67%)의 최대 원천."""
    try:
        # 킬스위치는 여기서 라이브로 본다 — 호출측 플래그는 세션 생성 시점 캐시라
        # 세션 도중 ASGARD_MEMORY_INJECT=off를 반영하지 못한다.
        if not inject_enabled():
            return ""
        req = re.sub(r"\s+", " ", (request or "")).strip().replace('"', "'")
        if not req or not response or scan_threats(req):
            return ""
        real_root = os.path.realpath(root)
        paths: list[str] = []
        for tok in re.findall(r"[\w][\w./\-]*\.[A-Za-z0-9_]+", response):
            p = tok.strip(".")
            if "/" not in p or os.path.isabs(p) or p.startswith((".asgard/", ".git/")):
                continue
            full = os.path.realpath(os.path.join(real_root, p))
            if os.path.commonpath([real_root, full]) != real_root:
                continue  # 경로 순회 시도 — 후보 자격 없음
            if p not in paths and os.path.isfile(full):
                paths.append(p)
            if len(paths) >= DISTILL_MAX_PATHS:
                break
        if not paths:
            return ""
        fact = f"{req[:80]} → {', '.join(paths)}"
        # 안내문의 괄호는 장식이 아니라 계약이다 — 자동저장이 켜진 기계에서 "승인 전엔 저장되지
        # 않음"이라고 적으면, 그 명령을 친 사람은 자기가 뭘 했는지 모른 채 저장하게 된다.
        gate = "자동저장 켜짐 — 실행하면 바로 저장됩니다" if autosave_enabled() else "승인 전엔 저장되지 않음"
        return f'⠶ 탐색 발견 저장 후보 ({gate}):\n  asgard memory ingest "{fact}" --kind reference'
    except Exception:
        return ""  # fail-open — 넛지는 실행을 인질로 잡지 않는다
