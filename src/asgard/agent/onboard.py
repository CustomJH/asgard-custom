"""인터랙티브 온보딩 (CUS-145) — opencode /connect · claude-code 로그인 관행.

키 없이 start 진입 → provider 선택 → 키 입력(getpass, 에코 없음) → ~/.asgard/credentials.json
저장(chmod 600, config 와 분리). env var 는 여전히 우선(export 한 사용자 무회귀). 비-TTY 에선
온보딩 불가 — 호출부가 처방으로 폴백한다.
"""

from __future__ import annotations

import getpass
import sys

from .. import ui
from ..i18n import t
from ..providers import PROVIDERS, ResolvedProvider, resolve, save_credential


def can_prompt() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def onboard(root: str, preselect: str | None = None) -> ResolvedProvider | None:
    """provider 선택 + 키 입력 → 저장 → 재해석된 ResolvedProvider. 취소면 None."""
    names = list(PROVIDERS)
    if preselect in PROVIDERS:
        name = preselect
    else:
        sys.stdout.write(f"\n  {ui.bold(t('pick_provider'))}\n")
        for i, n in enumerate(names, 1):
            p = PROVIDERS[n]
            sys.stdout.write(f"    {ui.paint('38;5;80', str(i))} {p.display} {ui.dim('· ' + (p.default_model or t('needs_base_url')))}\n")
        try:
            sel = input("  " + t("number") + " [1]: ").strip() or "1"
            name = names[int(sel) - 1]
        except (ValueError, IndexError, EOFError, KeyboardInterrupt):
            sys.stdout.write(f'  {t("cancelled")}\n')
            return None

    p = PROVIDERS[name]
    base_url, model = "", ""
    if p.api_mode == "openai_compat" and not p.base_url:
        base_url = input(f"  base_url [{p.base_url or 'https://...'}]: ").strip()
    if not p.default_model:
        model = input("  " + t("model_id_prompt") + ": ").strip()

    try:
        key = getpass.getpass('  ' + t('api_key_prompt', p=p.display) + ': ').strip()
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write(f'  {t("cancelled")}\n')
        return None
    if not key:
        sys.stdout.write(f'  {t("no_key")}\n')
        return None

    save_credential(name, key, base_url=base_url, model=model)
    sys.stdout.write(f"  {ui.paint('32', '✔')} {ui.dim(t('saved_cred'))}\n")
    return resolve(root, provider=name)
