"""인터랙티브 온보딩 — 세션 안 provider 연결·로그인 흐름.

키 없이 start 진입 → provider 선택 → 키 입력(getpass, 에코 없음) → ~/.asgard/credentials.json
저장(chmod 600, config 와 분리). env var 는 여전히 우선(export 한 사용자 무회귀). 비-TTY 에선
온보딩 불가 — 호출부가 처방으로 폴백한다.
"""

from __future__ import annotations

import getpass
import sys

from .. import theme, ui
from ..i18n import t
from ..providers import (
    PROVIDERS,
    ResolvedProvider,
    normalize_model_id,
    project_section,
    provider_models,
    resolve,
    save_config_section,
    save_credential,
)


def can_prompt() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _pick_model(rp: ResolvedProvider) -> str | None:
    """연결 catalog에서 모델 선택. catalog 실패 시 curated 목록, 언제나 수동 ID 입력을 허용."""
    fallback_reasons: list[str] = []
    models = provider_models(rp, on_fallback=fallback_reasons.append)
    if fallback_reasons:
        sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t('model_catalog_fallback')}\n")
    account_catalog = rp.profile.api_mode == "codex_responses" and not fallback_reasons
    if rp.model and rp.model not in models and not account_catalog:
        models.insert(0, rp.model)
    models = list(dict.fromkeys(models))
    query = ""
    while True:
        matches = [m for m in models if query.lower() in m.lower()]
        visible = matches[:40]
        sys.stdout.write(f"\n  {ui.bold(t('pick_model'))}\n")
        for i, model_id in enumerate(visible, 1):
            mark = " *" if model_id == rp.model else ""
            sys.stdout.write(f"    {ui.paint(theme.ansi(theme.PRIMARY), str(i))} {model_id}{ui.dim(mark)}\n")
        if len(matches) > len(visible):
            sys.stdout.write(f"    {ui.dim(f'… {len(matches) - len(visible)} more — use s to search')}\n")
        sys.stdout.write(f"    {ui.dim('s search · m manual model ID · q cancel')}\n")
        default = next((str(i) for i, model_id in enumerate(visible, 1) if model_id == rp.model), "1")
        try:
            choice = input("  " + t("number") + f" [{default}]: ").strip() or default
        except EOFError, KeyboardInterrupt:
            return None
        if choice.lower() == "q":
            return None
        if choice.lower() == "m":
            try:
                manual = normalize_model_id(input("  " + t("model_id_prompt") + ": "))
            except EOFError, KeyboardInterrupt:
                return None
            if not manual:
                sys.stdout.write(f"  {t('invalid_model_id')}\n")
                return None
            if account_catalog and manual not in models:
                sys.stdout.write(f"  {t('invalid_model_id')}\n")
                continue
            return manual
        if choice.lower() == "s":
            try:
                query = input("  search: ").strip()
            except EOFError, KeyboardInterrupt:
                return None
            continue
        try:
            index = int(choice)
            if index < 1:
                raise IndexError
            return visible[index - 1]
        except ValueError, IndexError:
            sys.stdout.write(f"  {t('cancelled')}\n")
            return None


def _provider_values(root: str, rp: ResolvedProvider) -> dict:
    """같은 provider의 옵션만 승계한다. 타 provider endpoint/key env가 새 credential에 섞이면 안 된다."""
    values = project_section(root, "provider")
    if values.get("name") != rp.profile.name:
        values = {}
    values.update({"name": rp.profile.name, "model": rp.model})
    if rp.profile.name not in {"nvidia", "openai"} and rp.base_url and rp.base_url != rp.profile.base_url:
        values["base_url"] = rp.base_url
    else:
        values.pop("base_url", None)
    return values


def select_model(root: str, rp: ResolvedProvider, *, persist: bool = True) -> ResolvedProvider | None:
    """현재 provider의 모델을 선택하고 project provider 설정에 저장한다."""
    model = _pick_model(rp)
    if not model:
        return None
    return select_model_id(root, rp, model, persist=persist)


def select_model_id(root: str, rp: ResolvedProvider, model: str, *, persist: bool = True) -> ResolvedProvider | None:
    """검증된 model ID를 적용한다. 모델 선택 경로(REPL /model·온보딩)의 공통 저장 지점."""
    model = normalize_model_id(model)
    if not model:
        return None
    if not persist:
        return resolve(root, provider=rp.profile.name, model=model)
    selected = resolve(root, provider=rp.profile.name, model=model)
    if selected.profile.name not in {"nvidia", "openai"}:
        selected.base_url = rp.base_url
    values = _provider_values(root, selected)
    save_config_section(root, "provider", values)
    return resolve(root, provider=rp.profile.name)


def onboard(root: str, preselect: str | None = None) -> ResolvedProvider | None:
    """provider 선택 + 키 입력 → 저장 → 재해석된 ResolvedProvider. 취소면 None."""
    names = list(PROVIDERS)
    if preselect in PROVIDERS:
        name = preselect
    else:
        sys.stdout.write(f"\n  {ui.bold(t('pick_provider'))}\n")
        for i, n in enumerate(names, 1):
            p = PROVIDERS[n]
            sys.stdout.write(
                f"    {ui.paint(theme.ansi(theme.PRIMARY), str(i))} {p.display} {ui.dim('· ' + (p.default_model or t('needs_base_url')))}\n"
            )
        try:
            sel = input("  " + t("number") + " [1]: ").strip() or "1"
            name = names[int(sel) - 1]
        except ValueError, IndexError, EOFError, KeyboardInterrupt:
            sys.stdout.write(f"  {t('cancelled')}\n")
            return None

    p = PROVIDERS[name]
    base_url, model = "", ""
    has_model_picker = bool(p.fallback_models) or p.api_mode == "openai_compat"
    if p.api_mode == "codex_responses":
        from .. import openai_codex

        def notify(message: str) -> None:
            sys.stdout.write(f"  {message}\n")

        try:
            tokens = openai_codex.device_login(notify)
            openai_codex.save_tokens(tokens)
        except openai_codex.OAuthError as exc:
            sys.stdout.write(f"  ChatGPT login failed: {exc}\n")
            return None
        sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {ui.dim('ChatGPT login saved for Asgard')}\n")
    if p.api_mode == "openai_compat" and not p.base_url:
        base_url = input(f"  base_url [{p.base_url or 'https://...'}]: ").strip()
    if not p.default_model and not has_model_picker:
        model = input("  " + t("model_id_prompt") + ": ").strip()

    key = ""
    if not p.key_optional:  # 로컬 provider(ollama 등)는 키 불요 — 입력 생략
        try:
            key = getpass.getpass("  " + t("api_key_prompt", p=p.display) + ": ").strip()
        except EOFError, KeyboardInterrupt:
            sys.stdout.write(f"  {t('cancelled')}\n")
            return None
        if not key:
            sys.stdout.write(f"  {t('no_key')}\n")
            return None

    if key or base_url:
        save_credential(name, key, base_url=base_url)
        sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {ui.dim(t('saved_cred'))}\n")
    current = resolve(root, provider=name, model=model or None)
    if has_model_picker:
        selected = select_model(root, current)
        if selected is not None:
            return selected
        return None
    values = _provider_values(root, current)
    save_config_section(root, "provider", values)
    return resolve(root, provider=name)
