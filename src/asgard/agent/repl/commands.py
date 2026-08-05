"""슬래시 명령 — /trinity·/bridge·/manual·/lagom 과 그 되묻기 화면."""

from __future__ import annotations

import sys

from ... import ui
from ...i18n import t
from ..quest_bridge import ql
from .catalog import _COMMAND_HELP, _help_items
from .chrome import _O, banner
from .editline import _PT_CTX


class _Reconfigure(Exception):
    """provider set / trinity 배치 변경 — 세션(Heimdall) 재생성 신호."""

    def __init__(self, rp, msg: str | None = None):
        self.rp, self.msg = rp, msg


def _trinity_models(root: str) -> None:
    """/trinity models — 호스트별 역할 모델 현황."""
    from ...commands.role import role_model_state

    for host, roles in role_model_state(root).items():
        sys.stdout.write(f"  {ui.bold(host)}\n")
        for role, selected in roles.items():
            if host == "native":
                value = f"{selected['provider']}:{selected['model']}"
            else:
                value = str(selected["model"])
                if selected.get("effort"):
                    value += f" · effort={selected['effort']}"
            sys.stdout.write(f"    {ui.paint(_O, role.ljust(12))} {value}\n")


def _trinity_model(args: list[str], root: str, rp) -> None:
    """/trinity model — 역할별 모델 지정·초기화. 인자가 없으면 대화형으로 고른다."""
    values = args[1:] or _prompt_role_model(root, rp)
    if not values:
        return
    _apply_role_model(values, root, rp)


def _prompt_role_model(root: str, rp) -> list[str] | None:
    """인자 없는 /trinity model — 대화형으로 (host, role, model)을 고른다.

    None은 "고르지 못했다"이고 이유는 셋이다 — 프롬프트 불가·사용자 취소·native 위임.
    셋 다 호출부가 할 일이 없다는 점에서 같아서 한 값으로 합쳤다."""
    from ...commands.role import MODEL_HOSTS, role_model_state
    from ...templates.agent_models import AGENT_MODEL_DEFAULTS
    from ..onboard import can_prompt

    if not can_prompt():
        sys.stdout.write(f"  {ui.dim(t('trinity_model_usage'))}\n")
        return None
    from ...picker import Option, available, pick

    try:
        if available():  # 인터랙티브 패널 — host→role→model 연계 창 (번호 입력은 폴백)
            picked = pick(t("pick_host"), [Option(n, n) for n in MODEL_HOSTS])
            if picked is None:
                raise EOFError
            host = picked
            if host == "native":
                _cmd_trinity("/trinity set", root, rp)
                return None
            state = role_model_state(root)[host]
            roles = tuple(AGENT_MODEL_DEFAULTS[host])
            picked = pick(t("pick_role"), [Option(n, n, detail=str(state[n]["model"])) for n in roles])
            if picked is None:
                raise EOFError
            role = picked
            current = str(state[role]["model"])
            recommended = AGENT_MODEL_DEFAULTS[host][role]["model"]
            models = list(
                dict.fromkeys([current, recommended, *(item["model"] for item in AGENT_MODEL_DEFAULTS[host].values())])
            )
            mopts = [Option("", t("model_override_clear"))]
            for model_id in models:
                tags = []
                if model_id == current:
                    tags.append(t("current_tag"))
                if model_id == recommended:
                    tags.append(t("recommended_tag"))
                mopts.append(Option(model_id, model_id, detail=", ".join(tags), current=model_id == current))
            sel = pick(t("pick_model"), mopts, default=models.index(current) + 1, manual_hint=t("picker_manual_model"))
            if sel is None:
                raise EOFError
            values = ["reset", host, role] if sel == "" else [host, role, sel]
        else:
            sys.stdout.write(f"\n  {ui.bold(t('pick_host'))}\n")
            for i, name in enumerate(MODEL_HOSTS, 1):
                sys.stdout.write(f"    {ui.paint(_O, str(i))} {name}\n")
            choice = input("  " + t("number") + " [1]: ").strip() or "1"
            if choice.lower() == "q":
                raise EOFError
            host = MODEL_HOSTS[int(choice) - 1]
            if host == "native":
                _cmd_trinity("/trinity set", root, rp)
                return None

            state = role_model_state(root)[host]
            roles = tuple(AGENT_MODEL_DEFAULTS[host])
            sys.stdout.write(f"\n  {ui.bold(t('pick_role'))}\n")
            for i, name in enumerate(roles, 1):
                sys.stdout.write(f"    {ui.paint(_O, str(i))} {name} {ui.dim('· ' + state[name]['model'])}\n")
            choice = input("  " + t("number") + " [1]: ").strip() or "1"
            if choice.lower() == "q":
                raise EOFError
            role = roles[int(choice) - 1]

            current = str(state[role]["model"])
            recommended = AGENT_MODEL_DEFAULTS[host][role]["model"]
            models = list(
                dict.fromkeys([current, recommended, *(item["model"] for item in AGENT_MODEL_DEFAULTS[host].values())])
            )
            sys.stdout.write(f"\n  {ui.bold(t('pick_model'))}\n")
            sys.stdout.write(f"    {ui.paint(_O, '0')} {t('model_override_clear')}\n")
            for i, model_id in enumerate(models, 1):
                tags = []
                if model_id == current:
                    tags.append(t("current_tag"))
                if model_id == recommended:
                    tags.append(t("recommended_tag"))
                suffix = ui.dim(" · " + ", ".join(tags)) if tags else ""
                sys.stdout.write(f"    {ui.paint(_O, str(i))} {model_id}{suffix}\n")
            sys.stdout.write(f"    {ui.dim('m ' + t('model_id_prompt') + ' · q cancel')}\n")
            default = str(models.index(current) + 1)
            choice = input("  " + t("number") + f" [{default}]: ").strip() or default
            if choice.lower() == "q":
                raise EOFError
            if choice == "0":
                values = ["reset", host, role]
            elif choice.lower() == "m":
                values = [host, role, input("  " + t("model_id_prompt") + ": ").strip()]
            else:
                values = [host, role, models[int(choice) - 1]]
    except ValueError, IndexError, EOFError, KeyboardInterrupt:
        sys.stdout.write(f"  {t('cancelled')}\n")
        return None
    return values


def _apply_role_model(values: list[str], root: str, rp) -> None:
    """확정된 인자로 역할 모델을 저장하거나 초기화한다."""
    from ...commands.role import configure_role_model

    reset = values[:1] == ["reset"]
    if reset:
        values = values[1:]
    if len(values) < 2 or (not reset and len(values) < 3) or len(values) > (2 if reset else 4):
        sys.stdout.write(f"  {ui.dim(t('trinity_model_usage'))}\n")
        return
    host, role = values[:2]
    model = None if reset else values[2]
    extra = None if reset or len(values) < 4 else values[3]
    try:
        result = configure_role_model(
            root,
            host,
            role,
            model=model,
            effort=extra if host != "native" else None,
            provider=extra if host == "native" else None,
            reset=reset,
        )
    except ValueError as exc:
        sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {exc}\n")
        return
    effective = result["effective"]
    value = f"{effective.get('provider')}:" if host == "native" else ""
    value += str(effective["model"])
    if effective.get("effort"):
        value += f" · effort={effective['effort']}"
    msg = t("trinity_model_reset" if reset else "trinity_model_saved", host=host, role=role, value=value)
    if host == "native":
        raise _Reconfigure(rp, msg)
    sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {msg}\n")
    return


def _cmd_trinity(cmd: str, root: str, rp) -> None:
    """/trinity — 역할 배치와 Dual Thinker 세션·프로젝트 모드."""
    from ...providers import PROVIDERS, resolve_trinity, save_config_section

    args = cmd.split()[1:]
    if args[:1] == ["models"]:
        _trinity_models(root)
        return

    if args[:1] == ["model"]:
        _trinity_model(args, root, rp)
        return

    if args[:1] == ["dual"]:
        hd = _PT_CTX.get("heimdall")
        if hd is None:
            sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t('connect_needed')}\n")
            return
        if len(args) == 1:
            state = "on" if hd.dual_mode else "off"
            a, b = hd.dual_thinker_labels()
            sys.stdout.write(f"  {ui.paint(_O, 'dual'.ljust(9))} {state} {ui.dim(f'· {a} ⊕ {b}')}\n")
            return
        persistent = args[1:2] == ["default"]
        mode_arg = args[2] if persistent and len(args) == 3 else (args[1] if len(args) == 2 else "")
        if mode_arg not in ("on", "off"):
            sys.stdout.write(f"  {ui.dim(t('trinity_dual_usage'))}\n")
            return
        if mode_arg == "on":
            a, b = hd.dual_thinker_labels()
            if a == b:
                sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t('trinity_dual_same', model=a)}\n")
                return
        hd.dual_mode = mode_arg == "on"
        if persistent:
            save_config_section(root, "trinity.mode", {"dual": hd.dual_mode})
        key = "trinity_dual_persisted" if persistent else "trinity_dual_set"
        sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {t(key, mode=mode_arg)}\n")
        return

    if args[:1] == ["set"]:
        from ...picker import Option, available, pick
        from ..onboard import can_prompt

        if not can_prompt():
            return
        roles = ("thinker", "thinker_alt", "worker", "verifier")
        names = list(PROVIDERS)
        try:
            if available():  # 인터랙티브 패널 — 역할→provider 연계 창 (번호 입력은 폴백)
                picked_role = pick(t("pick_role"), [Option(r, r) for r in roles], default=1)
                if picked_role is None:
                    sys.stdout.write(f"  {t('cancelled')}\n")
                    return
                role = picked_role
                popts = [Option("", t("placement_clear"))] + [
                    Option(n, PROVIDERS[n].display, detail=PROVIDERS[n].default_model or t("needs_base_url"))
                    for n in names
                ]
                sel = pick(t("pick_provider"), popts)
                if sel is None:
                    sys.stdout.write(f"  {t('cancelled')}\n")
                    return
                if not sel:
                    save_config_section(root, f"trinity.{role}", None)
                    raise _Reconfigure(rp, t("placement_cleared"))
                name = sel
            else:
                sys.stdout.write(f"\n  {ui.bold(t('pick_role'))}\n")
                for i, r in enumerate(roles, 1):
                    sys.stdout.write(f"    {ui.paint(_O, str(i))} {r}\n")
                role = roles[int(input("  " + t("number") + " [2]: ").strip() or "2") - 1]
                sys.stdout.write(f"\n  {ui.bold(t('pick_provider'))}\n")
                sys.stdout.write(f"    {ui.paint(_O, '0')} {t('placement_clear')}\n")
                for i, n in enumerate(names, 1):
                    p = PROVIDERS[n]
                    sys.stdout.write(
                        f"    {ui.paint(_O, str(i))} {p.display} {ui.dim('· ' + (p.default_model or t('needs_base_url')))}\n"
                    )
                idx = int(input("  " + t("number") + " [0]: ").strip() or "0")
                if idx == 0:
                    save_config_section(root, f"trinity.{role}", None)
                    raise _Reconfigure(rp, t("placement_cleared"))
                name = names[idx - 1]
            p = PROVIDERS[name]
            vals: dict = {"provider": name}
            if p.fallback_models or p.api_mode == "openai_compat":
                from ...providers import resolve
                from ..onboard import _pick_model

                selected = _pick_model(resolve(root, provider=name))
                if not selected:
                    sys.stdout.write(f"  {t('cancelled')}\n")
                    return
                model = selected
            else:
                model = input(f"  model [{p.default_model or '?'}]: ").strip() or p.default_model
            if model:
                vals["model"] = model
            if p.api_mode == "openai_compat" and not p.base_url:
                bu = input("  base_url: ").strip()
                if bu:
                    vals["base_url"] = bu
        except ValueError, IndexError, EOFError, KeyboardInterrupt:
            sys.stdout.write(f"  {t('cancelled')}\n")
            return
        save_config_section(root, f"trinity.{role}", vals)
        raise _Reconfigure(rp, t("placement_saved"))

    roles = ("thinker", "thinker_alt", "worker", "verifier")
    for role, r in resolve_trinity(root, rp, roles).items():
        warn = f"  {ui.paint(ui._WARN, '⚠ ' + '; '.join(r.missing))}" if r.missing else ""
        tag = f" {ui.dim(t('default_tag'))}" if r is rp else ""
        sys.stdout.write(f"  {ui.paint(_O, role.ljust(9))} {r.profile.name}:{r.model}{tag}{warn}\n")
    sys.stdout.write(f"  {ui.dim(t('trinity_hint'))}\n")


def _cmd_bridge(cmd: str, root: str) -> None:
    """/bridge — 도구별 CLI 브릿지 플래그 표시/토글 ([bridge], 기본 전부 off)."""
    from ...providers import BRIDGE_TOOLS, bridge_flags, project_section, save_config_section

    args = cmd.split()[1:]
    if len(args) == 2 and args[0] in BRIDGE_TOOLS and args[1] in ("on", "off"):
        cur = project_section(root, "bridge")
        cur[args[0]] = args[1] == "on"
        save_config_section(root, "bridge", cur)
        sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {t('bridge_set', tool=args[0], v=args[1])}\n")
        return
    for tool, on in bridge_flags(root).items():
        mark = ui.paint(ui._OK, "on") if on else ui.dim("off")
        sys.stdout.write(f"  {ui.paint(_O, tool.ljust(12))} {mark}\n")
    sys.stdout.write(f"  {ui.dim(t('bridge_usage'))}\n")


def _cmd_manual(cmd: str, root: str) -> None:
    """/manual — 내가 쓴 프로젝트 규칙이 뭐가 들어갔는지. '/manual show'는 모델이 받는 원문.

    네이티브는 세션 생성 시 1회 렌더라(KV 캐시·재현성)이 화면은 **디스크 현재값**을 읽는다 —
    편집 직후 여기서 보이는 것과 이번 세션 프롬프트가 다를 수 있어서, 그 사실을 같이 말한다."""
    import os

    from ...manual import MANUAL_NAMES, enabled, home, load_manual, max_chars, note

    if cmd.split()[1:2] == ["show"]:
        text = note(root, "identity").strip()
        sys.stdout.write(("\n".join("  " + line for line in text.splitlines()) if text else f"  {ui.dim('—')}") + "\n")
        return
    if not enabled(root):
        sys.stdout.write(f"  {ui.paint(_O, 'manual'.ljust(9))} {ui.dim(t('manual_off'))}\n")
        return
    loaded = load_manual(root)
    if not loaded:
        user = os.environ.get("HOME") or os.path.expanduser("~")
        common = home().replace(user, "~", 1) + "/" + MANUAL_NAMES[0]
        sys.stdout.write(f"  {ui.paint(_O, 'manual'.ljust(9))} {ui.dim(t('manual_none'))}\n")
        sys.stdout.write(f"  {' ' * 9} {ui.dim(common + ' (공통) · ' + MANUAL_NAMES[0] + ' (이 프로젝트)')}\n")
        return
    sys.stdout.write(
        f"  {ui.paint(_O, 'manual'.ljust(9))} {loaded['chars']} / {max_chars(root)} chars"
        f" {ui.dim('(공통 ' + str(len(loaded['common'])) + ' + 프로젝트 ' + str(len(loaded['project'])) + ')')}\n"
    )
    for src in loaded["sources"]:
        sys.stdout.write(f"  {' ' * 9} {ui.dim(src)}\n")
    if loaded["shadowed"]:
        sys.stdout.write(f"  {' ' * 9} {ui.paint(ui._WARN, '⚠')} shadowed: {ui.dim(', '.join(loaded['shadowed']))}\n")
    sys.stdout.write(f"  {' ' * 9} {ui.dim(t('manual_frozen'))}\n")


def _cmd_lagom(cmd: str, root: str, rp) -> None:
    """/lagom — 모드 표시. '/lagom <mode>' 세션 전환, '/lagom default <mode>' 영속.
    전환은 _Reconfigure로 Heimdall을 재생성한다 — 역할 프롬프트의 lagom 렌더가 새 모드로 갱신."""
    from ...lagom import MODES, clear_state, current_mode, normalize, read_state, write_state

    args = cmd.split()[1:]
    if not args:
        cur, st = current_mode(root), read_state(root)
        tag = t("lagom_session") if st else t("lagom_default")
        sys.stdout.write(f"  {ui.paint(_O, 'lagom'.ljust(9))} {cur} {ui.dim('(' + tag + ')')}\n")
        for line in t("lagom_what").split("\n"):  # 라곰이 뭔지 — 한 번에 이해되게
            sys.stdout.write(f"  {' ' * 9} {ui.dim(line)}\n")
        for m in MODES:  # off·lite·full 각 모드가 뭘 하는지, 현재 모드는 표식
            mark = ui.paint(ui._OK, "▸") if m == cur else " "
            name = ui.paint(_O, m.ljust(6)) if m == cur else ui.dim(m.ljust(6))
            sys.stdout.write(f"  {mark} {name} {ui.dim(t('lagom_mode_' + m))}\n")
        sys.stdout.write(f"  {ui.dim(t('lagom_usage'))}\n")
        return
    if args[0] == "stats":  # 로컬 집계만, 무텔레메트리. honest numbers: 합산 지출이지 output 단독 아님
        hd = _PT_CTX.get("heimdall")
        cur = current_mode(root)
        tok = f"{hd.total_tokens / 1000:.1f}k" if hd and hd.total_tokens else "0"
        sys.stdout.write(
            f"  {ui.paint(_O, 'lagom'.ljust(9))} {cur} {ui.dim('· ' + t('lagom_stats_tokens', tok=tok))}\n"
        )
        sys.stdout.write(f"  {ui.dim(t('lagom_stats_note'))}\n")
        return
    is_default = args[0] == "default"
    mode = normalize(args[1] if is_default and len(args) > 1 else args[0])
    if mode is None:
        sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t('lagom_usage')}\n")
        return
    if is_default:
        from ...providers import save_config_section

        save_config_section(root, "lagom", {"mode": mode})
        clear_state(root)  # 상태파일 제거 → 새 기본값이 즉시 유효 (세션 오버라이드 해소)
        raise _Reconfigure(rp, t("lagom_persisted", mode=mode))
    write_state(root, mode)
    raise _Reconfigure(rp, t("lagom_set", mode=mode))


def slash(cmd: str, root: str, rp) -> bool:
    """슬래시 커맨드 처리. True = 처리됨(루프 계속), 종료/재설정은 예외로 신호."""
    c = cmd.split()[0]
    if c in ("/exit", "/quit"):
        raise EOFError
    if c == "/skills":
        from ...commands.skills import render_skills
        from ...skill_registry import invocable_skills

        rows = [row for row in invocable_skills(root) if row["invocation"] == "user"]
        if rows:
            rows = [{**row, "name": "/" + row["name"]} for row in rows]
            render_skills(rows, "User skills")
        else:
            sys.stdout.write(f"  {ui.dim('no user-invoked skills')}\n")
    elif c == "/help":
        sys.stdout.write("\n")
        for k, v in _help_items():
            sys.stdout.write(f"  {ui.paint(_O, k.ljust(14))} {ui.dim(v)}\n")
        sys.stdout.write(f"  {ui.paint(_O, '!<cmd>'.ljust(14))} {ui.dim(t('h_bash'))}\n")
        sys.stdout.write(f"  {ui.dim(t('help_footer'))}\n\n")
    elif c == "/lang":
        from ...i18n import save_lang
        from ...i18n import t as _t

        arg = cmd.split()[1:2]
        if arg and save_lang(arg[0], root):
            sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {ui.dim(_t('lang_set', lang=arg[0]))}\n")
        else:
            sys.stdout.write(f"  {ui.dim(_t('lang_usage'))}\n")
    elif c == "/update":
        from ...commands.update import run_update

        run_update(cmd.split()[1:], restart_hint=True)
    elif c == "/clear":
        sys.stdout.write("\033[2J\033[H")
        banner(rp)
    elif c == "/provider":
        if cmd.split()[1:2] == ["set"]:
            from ..onboard import can_prompt, onboard

            if can_prompt():
                new = onboard(root)
                if new is not None:
                    raise _Reconfigure(new)  # repl.run이 세션 재생성
            return True
        if rp.missing:  # 미연결 — 기본 프로파일(Claude)을 연결된 것처럼 보여주지 않는다
            sys.stdout.write(
                f"  {ui.paint(ui._WARN, '⚠')} {t('not_connected')} {ui.dim('· ' + '; '.join(rp.missing))}\n"
            )
            return True
        src = rp.key_source or rp.source
        sys.stdout.write(f"  {ui.paint(_O, rp.profile.display)} {ui.dim('·')} {rp.model} {ui.dim('(' + src + ')')}\n")
    elif c == "/model":
        from ..onboard import can_prompt, select_model

        if can_prompt():
            new = select_model(root, rp)
            if new is not None:
                raise _Reconfigure(new)
        else:
            sys.stdout.write(f"  {ui.paint(_O, rp.profile.display)} {ui.dim('·')} {rp.model}\n")
    elif c == "/trinity":
        _cmd_trinity(cmd, root, rp)
    elif c == "/bridge":
        _cmd_bridge(cmd, root)
    elif c == "/manual":
        _cmd_manual(cmd, root)
    elif c == "/lagom":
        _cmd_lagom(cmd, root, rp)
    elif c == "/quest":
        try:
            out = ql(root, "state").stdout.strip()
            sys.stdout.write(f"  {ui.dim(out or t('no_quest'))}\n")
        except Exception:
            sys.stdout.write(f"  {ui.dim(t('no_quest'))}\n")
    elif c == "/sessions":
        hd = _PT_CTX.get("heimdall")
        if hd is None:
            sys.stdout.write(f"  {ui.dim(t('no_sessions'))}\n")
            return True
        if cmd.split()[1:2] == ["stop"]:
            hd.cancel()
            sys.stdout.write(f"  {ui.paint(ui._WARN, '■')} {t('sessions_stopping')}\n")
            return True
        rows = hd.session_snapshot()
        if not rows:
            sys.stdout.write(f"  {ui.dim(t('no_sessions'))}\n")
            return True
        for row in rows[-12:]:
            mark = "●" if row["state"] == "running" else "○"
            detail = row["status"] or row["state"]
            sys.stdout.write(
                f"  {ui.paint(_O, mark)} {row['id'].ljust(18)} {ui.dim(detail + ' · ' + str(row['elapsed_s']) + 's')}\n"
            )
    else:
        from difflib import get_close_matches

        match = get_close_matches(c, _COMMAND_HELP, n=1, cutoff=0.6)
        key = "unknown_cmd_suggest" if match else "unknown_cmd"
        sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t(key, c=c, suggestion=match[0] if match else '')}\n")
    return True
