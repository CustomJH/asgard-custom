"""provider → SDK 클라이언트 한 자리. SDK 임포트는 전부 호출 시점이라 미설치 provider가 세션을 못 막는다."""

from __future__ import annotations

from ...providers import ResolvedProvider


def make_client(rp: ResolvedProvider):
    """provider → SDK 클라이언트. 키는 resolve()가 env 또는 credentials.json에서 찾아둔 값(rp.api_key)."""
    if rp.profile.api_mode == "anthropic":
        import anthropic

        # rp.api_key 있으면 그것(env 또는 credentials.json), 없으면 SDK 기본 해석(프로파일 등)에 위임
        return anthropic.Anthropic(api_key=rp.api_key) if rp.api_key else anthropic.Anthropic()
    if rp.profile.api_mode == "codex_responses":
        from ...openai_codex import make_client as make_codex_client

        return make_codex_client()
    if rp.profile.api_mode in {"openai_compat", "openai_responses"}:
        from openai import OpenAI

        if not rp.api_key:
            raise RuntimeError(f"API 키 없음 ({rp.profile.name}) — asgard start 온보딩에서 입력하세요")
        return OpenAI(base_url=rp.base_url or None, api_key=rp.api_key)
    if rp.profile.api_mode == "claude_cli":
        from ..claude_native import make_native_client

        return make_native_client()  # 마커 — 실제 스폰·인증은 Agent SDK/CLI가 해석

    raise NotImplementedError(f"api_mode '{rp.profile.api_mode}' 미지원")
