"""Provider 계층 (CUS-141) — 모델 연결의 선언적 추상화.

hermes-agent ProviderProfile 패턴 계승: 프로파일은 provider 의 사실만 선언하고
(이름·env·엔드포인트·기본 모델), 클라이언트 구성·스트리밍은 소유하지 않는다 — 그건
에이전트 루프(CUS-137) 몫. 설정 해석도 여기서: 프로젝트 → 글로벌 → 기본값.

API 키는 env var *이름*만 다룬다 — 설정 파일에 평문 저장 금지 (Canon 4). 키 값을
읽는 것도 루프 몫이고, 이 모듈은 존재 여부만 확인한다.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderProfile:
    """선언적 프로파일 — provider 의 사실만. 클라이언트/스트리밍 소유 금지."""

    name: str
    display: str
    api_mode: str                     # "anthropic" | "openai_compat"
    env_vars: tuple[str, ...]         # API 키 후보 env var (첫 매치 승리)
    default_model: str
    base_url: str = ""                # openai_compat 필수, anthropic 은 SDK 기본
    signup_hint: str = ""             # 키 없을 때 처방 한 줄


PROVIDERS: dict[str, ProviderProfile] = {
    "anthropic": ProviderProfile(
        name="anthropic",
        display="Anthropic (Claude)",
        api_mode="anthropic",
        env_vars=("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
        default_model="claude-opus-4-8",
        signup_hint="https://platform.claude.com 에서 키 발급 후 export ANTHROPIC_API_KEY=...",
    ),
    # 제네릭 OpenAI-호환 — OpenAI/OpenRouter/Ollama류. base_url 은 config 로 지정.
    "openai_compat": ProviderProfile(
        name="openai_compat",
        display="OpenAI-compatible",
        api_mode="openai_compat",
        env_vars=("OPENAI_API_KEY",),
        default_model="",  # compat 은 모델 기본값 없음 — config 필수
        signup_hint="config 에 base_url·model 지정 + api_key_env 의 env var export",
    ),
}


@dataclass
class ResolvedProvider:
    """config 해석 결과 — 루프가 받는 최종 연결 명세."""

    profile: ProviderProfile
    model: str
    base_url: str = ""
    api_key_env: str = ""             # 실제로 키를 찾은(또는 찾아야 할) env var 이름
    source: str = "default"           # default | ~/.asgard/config.toml | .asgard/config.toml | flag
    missing: list[str] = field(default_factory=list)  # 사람이 읽는 미충족 항목


def _read_toml(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {"_error": path}  # 깨진 config 는 조용히 무시하지 않고 표시


def resolve(root: str | None = None, provider: str | None = None,
            model: str | None = None) -> ResolvedProvider:
    """provider 연결 해석 — 우선순위: 플래그 > 프로젝트 config > 글로벌 config > 기본값."""
    root = root or os.getcwd()
    conf: dict = {}
    source = "default"
    for path, label in ((os.path.join(os.path.expanduser("~"), ".asgard", "config.toml"), "~/.asgard/config.toml"),
                        (os.path.join(root, ".asgard", "config.toml"), ".asgard/config.toml")):
        loaded = _read_toml(path).get("provider") or {}
        if loaded:
            conf.update(loaded)      # 프로젝트가 글로벌을 키 단위로 덮는다
            source = label

    name = provider or conf.get("name") or "anthropic"
    if provider:
        source = "flag"
        if conf.get("name") and conf["name"] != provider:
            # config 의 model/base_url/api_key_env 는 그 config 의 provider 전용 —
            # 플래그로 provider 를 바꾸면 타 provider 설정이 새면 안 된다.
            conf = {}
    profile = PROVIDERS.get(name)
    if profile is None:
        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="", source=source)
        rp.missing.append(f"unknown provider '{name}' — 지원: {', '.join(PROVIDERS)}")
        return rp

    rp = ResolvedProvider(
        profile=profile,
        model=model or conf.get("model") or profile.default_model,
        base_url=conf.get("base_url") or profile.base_url,
        source=source,
    )

    # API 키: config 의 api_key_env(이름) 우선, 없으면 프로파일 후보 순회
    candidates = ([conf["api_key_env"]] if conf.get("api_key_env") else []) + list(profile.env_vars)
    rp.api_key_env = next((v for v in candidates if os.environ.get(v)), "")
    if not rp.api_key_env:
        rp.missing.append(f"API 키 env 미설정 ({' 또는 '.join(candidates)}) — {profile.signup_hint}")
    if not rp.model:
        rp.missing.append("model 미지정 — .asgard/config.toml [provider] model=... 또는 --model")
    if profile.api_mode == "openai_compat" and not rp.base_url:
        rp.missing.append("base_url 미지정 — openai_compat 은 [provider] base_url=... 필수")
    return rp
