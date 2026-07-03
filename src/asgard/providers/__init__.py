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
    extra_body: dict = field(default_factory=dict)  # provider 고유 요청 필드 (nvidia reasoning 등)
    key_optional: bool = False        # 로컬 서버(ollama 등) — 키 없어도 연결 (SDK 엔 더미 전달)
    context_window: int = 0           # 대략적 컨텍스트 한도 (status line % 용). 0 = 미상 → % 생략


PROVIDERS: dict[str, ProviderProfile] = {
    "anthropic": ProviderProfile(
        name="anthropic",
        display="Anthropic (Claude)",
        api_mode="anthropic",
        env_vars=("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
        default_model="claude-opus-4-8",
        signup_hint="https://platform.claude.com 에서 키 발급 후 export ANTHROPIC_API_KEY=...",
        context_window=200_000,
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
    # Ollama — 로컬 서버 (openai_compat 엔드포인트). 키 불요, 모델은 ollama pull 로 준비.
    "ollama": ProviderProfile(
        name="ollama",
        display="Ollama (local)",
        api_mode="openai_compat",
        env_vars=("OLLAMA_API_KEY",),  # 원격 ollama 등 특수 환경용 — 보통 불요
        base_url="http://localhost:11434/v1",
        default_model="gemma4:12b-mlx",
        signup_hint="ollama serve 실행 + ollama pull gemma4:12b-mlx (API 키 불요)",
        key_optional=True,
        context_window=128_000,
    ),
    # NVIDIA NIM — openai_compat 특수화. reasoning 파라미터는 extra_body 로 (enable_thinking·reasoning_budget).
    "nvidia": ProviderProfile(
        name="nvidia",
        display="NVIDIA NIM",
        api_mode="openai_compat",
        env_vars=("NVIDIA_API_KEY",),
        base_url="https://integrate.api.nvidia.com/v1",
        default_model="nvidia/nemotron-3-ultra-550b-a55b",
        signup_hint="build.nvidia.com 에서 nvapi- 키 발급 후 export NVIDIA_API_KEY=...",
        extra_body={"chat_template_kwargs": {"enable_thinking": True}, "reasoning_budget": 16384},
    ),
}


@dataclass
class ResolvedProvider:
    """config 해석 결과 — 루프가 받는 최종 연결 명세."""

    profile: ProviderProfile
    model: str
    base_url: str = ""
    api_key_env: str = ""             # 키를 찾은 env var 이름 (env 소스일 때). 표시용.
    api_key: str = ""                 # 실제 키 값 (env 또는 credentials.json). repr 마스킹.
    key_source: str = ""              # "" | env:<VAR> | credentials.json
    source: str = "default"           # default | ~/.asgard/config.toml | .asgard/config.toml | flag
    missing: list[str] = field(default_factory=list)  # 사람이 읽는 미충족 항목

    def __repr__(self) -> str:  # 키 값이 로그·트레이스에 새지 않게 마스킹 (Canon 4)
        k = f"***{self.api_key[-4:]}" if self.api_key else ""
        return (f"ResolvedProvider(name={self.profile.name!r}, model={self.model!r}, "
                f"key_source={self.key_source!r}, api_key={k!r}, missing={self.missing!r})")


CRED_PATH = os.path.join(os.path.expanduser("~"), ".asgard", "credentials.json")


def load_credentials() -> dict:
    """~/.asgard/credentials.json — provider별 {"api_key": ...}. config 와 분리된 키 격리 저장소."""
    import json
    try:
        with open(CRED_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_credential(provider: str, api_key: str, base_url: str = "", model: str = "") -> None:
    """키를 credentials.json 에 저장 — chmod 600, config.toml 에는 절대 안 넣는다 (Canon 4)."""
    import json
    creds = load_credentials()
    entry = {"api_key": api_key}
    if base_url:
        entry["base_url"] = base_url
    if model:
        entry["model"] = model
    creds[provider] = entry
    os.makedirs(os.path.dirname(CRED_PATH), exist_ok=True)
    fd = os.open(CRED_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(creds, f, indent=2)
    os.chmod(CRED_PATH, 0o600)  # 기존 파일이었어도 강제


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

    cred = load_credentials().get(name, {})
    rp = ResolvedProvider(
        profile=profile,
        model=model or conf.get("model") or cred.get("model") or profile.default_model,
        base_url=conf.get("base_url") or cred.get("base_url") or profile.base_url,
        source=source,
    )

    # API 키 해석 — env var(프로파일 후보) 우선, 없으면 credentials.json. env 는 export 한 사용자를
    # 존중(무회귀), 파일은 온보딩으로 저장한 것. 둘 다 없으면 온보딩 대상(missing).
    candidates = ([conf["api_key_env"]] if conf.get("api_key_env") else []) + list(profile.env_vars)
    env_var = next((v for v in candidates if os.environ.get(v)), "")
    if env_var:
        rp.api_key, rp.api_key_env, rp.key_source = os.environ[env_var], env_var, f"env:{env_var}"
    elif cred.get("api_key"):
        rp.api_key, rp.key_source = cred["api_key"], "credentials.json"
    elif profile.key_optional:
        rp.api_key, rp.key_source = "ollama", "local (keyless)"  # openai SDK 는 빈 키 거부 — 더미
    else:
        rp.missing.append(f"API 키 없음 ({name}) — asgard start 에서 입력하거나 {' / '.join(candidates)} export")
    if not rp.model:
        rp.missing.append("model 미지정 — 온보딩에서 입력하거나 --model")
    if profile.api_mode == "openai_compat" and not rp.base_url:
        rp.missing.append("base_url 미지정 — openai_compat 은 온보딩에서 입력하거나 [provider] base_url")
    return rp
