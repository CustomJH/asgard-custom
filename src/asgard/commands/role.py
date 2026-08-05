"""role — Trinity 역할 브릿지 CLI (claude-code / codex / cursor → 배치 provider 위임).

호스트 도구가 자기 내부 모델 대신 `[trinity.<role>]` 배치 provider로 역할 턴을 실행할 때
부른다 (asgard-provider 스킬이 안내). 퀘스트 로그 기록은 CLI가 수행 — 프로토콜 준수가 모델 순응이
아니라 코드 경로다 (네이티브 루프와 같은 원칙, heimdall.py 참조). 게이트 판정은 그대로
verifier-gate 몫. `[bridge]` 게이트 판단은 호스트 몫 — 이 CLI는 사실(list)과 실행(run)만.
"""

import json
import os
import sys
from typing import Any, Callable

from .. import errors, ui
from ..providers import (
    PROVIDERS,
    TRINITY_EXTRA_ROLES,
    TRINITY_ROLES,
    ResolvedProvider,
    bridge_flags,
    normalize_model_id,
    project_section,
    resolve,
    resolve_trinity,
    save_config_section,
)

MODEL_HOSTS = ("native", "claude-code", "cursor", "codex")


def _native_roles() -> tuple[str, ...]:
    from ..templates.roles import delivery_agents

    return TRINITY_ROLES + TRINITY_EXTRA_ROLES + tuple(delivery_agents())


def role_model_state(root: str) -> dict[str, dict[str, dict[str, Any]]]:
    """Return the effective role models for every runtime host."""
    from ..templates.agent_models import AGENT_MODEL_DEFAULTS, agent_model

    default = resolve(root)
    native = resolve_trinity(root, default, _native_roles())
    return {
        "native": {
            role: {
                "provider": rp.profile.name,
                "model": rp.model,
                "placed": rp is not default,
                "missing": rp.missing,
            }
            for role, rp in native.items()
        },
        **{
            host: {role: agent_model(root, host, role) for role in defaults}
            for host, defaults in AGENT_MODEL_DEFAULTS.items()
        },
    }


def _sync_host(root: str, host: str) -> dict[str, int] | None:
    folder = {"claude-code": ".claude", "cursor": ".cursor", "codex": ".codex"}[host]
    if not os.path.isdir(os.path.join(root, folder)):
        return None
    from .sync import sync_project

    return sync_project(
        root,
        cc=host == "claude-code",
        cursor=host == "cursor",
        codex=host == "codex",
    )


def configure_role_model(
    root: str,
    host: str,
    role: str,
    *,
    model: str | None = None,
    effort: str | None = None,
    provider: str | None = None,
    reset: bool = False,
) -> dict:
    """Persist one project-level role model override and refresh its host scaffold."""
    from ..templates.agent_models import AGENT_MODEL_DEFAULTS

    if host not in MODEL_HOSTS:
        raise ValueError(f"host는 {'/'.join(MODEL_HOSTS)} 중 하나예요")
    valid_roles = _native_roles() if host == "native" else tuple(AGENT_MODEL_DEFAULTS[host])
    if role not in valid_roles:
        raise ValueError(f"{host} role은 {'/'.join(valid_roles)} 중 하나예요")
    if model:
        model = normalize_model_id(model)
        if not model:
            raise ValueError("쓸 수 있는 model ID가 필요해요")
    if provider and provider not in PROVIDERS:
        raise ValueError(f"provider는 {'/'.join(PROVIDERS)} 중 하나예요")

    section = f"trinity.{role}" if host == "native" else f"agent_models.{host}.{role}"
    if reset:
        if model or effort or provider:
            raise ValueError("--reset은 model/--effort/--provider와 같이 쓸 수 없어요")
        path = save_config_section(root, section, None)
    else:
        values = project_section(root, section)
        if host == "native":
            if effort:
                raise ValueError("native는 --effort 대신 provider/model 배치를 써요")
            if not (model or provider):
                raise ValueError("native 설정에는 model 또는 --provider가 필요해요")
            if model:
                values["model"] = model
            if provider:
                values["provider"] = provider
        else:
            if provider:
                raise ValueError("--provider는 native에서만 쓸 수 있어요")
            if host == "cursor" and effort:
                raise ValueError("Cursor effort는 model slug에 넣어서 설정해요")
            if not (model or effort):
                raise ValueError("hosted 설정에는 model 또는 --effort가 필요해요")
            if model:
                values["model"] = model
            if effort:
                values["effort"] = effort
        path = save_config_section(root, section, values)

    synced = None if host == "native" else _sync_host(root, host)
    return {
        "host": host,
        "role": role,
        "reset": reset,
        "effective": role_model_state(root)[host][role],
        "settings": path,
        "synced": synced,
    }


def reset_role_models(root: str, host: str) -> dict:
    """Remove every project role-model override for one runtime host."""
    if host not in MODEL_HOSTS:
        raise ValueError(f"host는 {'/'.join(MODEL_HOSTS)} 중 하나예요")
    if host == "native":
        values = project_section(root, "trinity")
        for role in _native_roles():
            values.pop(role, None)
        path = save_config_section(root, "trinity", values)
        synced = None
    else:
        path = save_config_section(root, f"agent_models.{host}", None)
        synced = _sync_host(root, host)
    return {
        "host": host,
        "reset": True,
        "effective": role_model_state(root)[host],
        "settings": path,
        "synced": synced,
    }


def run_role_model(
    host: str | None = None,
    role: str | None = None,
    model: str | None = None,
    *,
    effort: str | None = None,
    provider: str | None = None,
    reset: bool = False,
    json_out: bool = False,
) -> int:
    root = os.getcwd()
    errors.set_json_surface(json_out)
    if not any((host, role, model, effort, provider, reset)):
        state = role_model_state(root)
        if json_out:
            _emit(state)
        else:
            _print_models(state)
        return 0
    if not host or not role:
        raise errors.InvalidInput(
            "host와 role이 필요해요",
            remedy=f"asgard role model <{'|'.join(MODEL_HOSTS)}> <role> [model]",
            detail={"host": host or "", "role": role or ""},
        )
    try:
        out = configure_role_model(
            root,
            host,
            role,
            model=model,
            effort=effort,
            provider=provider,
            reset=reset,
        )
    except ValueError as exc:
        raise errors.InvalidInput(
            str(exc),
            remedy="`asgard role list`로 지금 무엇이 어디에 놓여 있는지 보세요",
            detail={"host": host, "role": role},
        ) from exc
    if json_out:
        _emit(out)
    else:
        effective = out["effective"] if isinstance(out["effective"], dict) else {}
        ui.ok(f"{host} · {role} → {effective.get('model') or '?'}")
        ui.step(f"설정 파일: {out['settings']}")
    return 0


def _print_models(state: dict[str, dict[str, dict[str, Any]]]) -> None:
    """호스트별 역할 모델 — 사람이 읽는 얼굴."""
    for host, roles in state.items():
        print(ui.bold(host))
        for role, row in roles.items():
            model = str(row.get("model") or "?")
            extra = " ".join(
                part
                for part in (
                    str(row.get("provider") or ""),
                    "placed" if row.get("placed") else "",
                    "missing" if row.get("missing") else "",
                )
                if part
            )
            print(f"  {role.ljust(12)} {model}  {ui.dim(extra)}")


def run_role_list(json_out: bool = False) -> int:
    """브릿지·역할 배치·호스트 모델을 한 화면에.

    여태 이 명령은 플래그와 무관하게 JSON만 냈고 도움말이 그 사실을 "(JSON)"으로 광고했다.
    같은 저장소의 다른 `list`(skills·plugins·ticket)는 전부 사람 표면이 기본이고 JSON은
    플래그 뒤에 있다 — 도움말을 고치는 대신 이 명령을 그 규칙에 맞췄다."""
    root = os.getcwd()
    errors.set_json_surface(json_out)
    default = resolve(root)
    models = role_model_state(root)
    out = {
        "bridge": bridge_flags(root),
        "roles": {
            r: {"provider": rp.profile.name, "model": rp.model, "placed": rp is not default, "missing": rp.missing}
            for r, rp in resolve_trinity(root, default).items()
        },
        "agent_models": {host: roles for host, roles in models.items() if host != "native"},
    }
    if json_out:
        _emit(out)
        return 0
    opened = [host for host, on in out["bridge"].items() if on]
    print(ui.bold("bridge") + "  " + (", ".join(opened) if opened else ui.dim("열린 브릿지 없음")))
    print(ui.bold("roles"))
    for role, row in out["roles"].items():
        flags = " ".join(
            part for part in ("placed" if row["placed"] else "", "missing" if row["missing"] else "") if part
        )
        print(f"  {role.ljust(12)} {row['provider']}  {row['model']}  {ui.dim(flags)}")
    for host, roles in out["agent_models"].items():
        print(ui.bold(host))
        for role, row in roles.items():
            print(f"  {role.ljust(12)} {row.get('model', '?')}")
    return 0


def _emit(payload: dict) -> None:
    """`--json` 산출물 — stdout은 이 한 덩어리만 받는다."""
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _bridge_preconditions(root: str, role: str, sid: str) -> dict:
    """인자와 퀘스트 상태를 확인하고 그 상태를 돌려준다 — 아니면 왜 못 여는지를 던진다.

    두 실패는 종료 코드가 같지만(2) `code`가 갈린다. 모르는 역할은 인자가 틀린 것이고, quest
    없음은 순서가 어긋난 것이다. 호스트가 그 둘에 다르게 반응해야 하기 때문이다 — 하나는
    명령을 고쳐 다시 부르고, 하나는 같은 명령을 quest를 연 뒤 그대로 부른다."""
    from ..agent.quest_bridge import ql

    if role not in TRINITY_ROLES:
        raise errors.InvalidInput(
            f"role은 {'/'.join(TRINITY_ROLES)} 중 하나예요",
            remedy=f'asgard role run <{"|".join(TRINITY_ROLES)}> "<과업>"',
            detail={"role": role, "valid": list(TRINITY_ROLES)},
        )
    try:
        state = json.loads(ql(root, "state", session=sid).stdout or "{}")
    except Exception:
        state = {}
    if not state.get("quest_id"):
        raise errors.Conflict(
            "열린 quest가 없어요",
            remedy="호스트가 quest-log open을 먼저 돌려야 해요 (asgard-provider 스킬의 순서)",
            detail={"session": sid, "role": role},
        )
    return state


def _placed_provider(root: str, role: str) -> tuple[ResolvedProvider, ResolvedProvider]:
    """이 역할이 놓인 자리 — 미충족이면 무엇이 비었는지까지 들고 막는다."""
    default = resolve(root)
    rrp = resolve_trinity(root, default)[role]
    if rrp.missing:
        raise errors.PreflightFailed(
            f"[trinity.{role}] 미충족: " + "; ".join(rrp.missing),
            remedy=f"`asgard role model native {role} <model>`로 배치하거나 위에 적힌 항목을 채우세요",
            detail={"role": role, "missing": list(rrp.missing)},
        )
    return default, rrp


def _turn_inputs(
    role: str, task: str, state: dict, criteria: list, level: str
) -> tuple[str, list[dict] | None, dict[str, Callable[[dict], str]] | None]:
    """이 역할 턴의 프롬프트와 추가 툴 — verifier만 다르다.

    verifier에게 Worker 해설을 입력으로 주지 않는 것이 요점이다: 판정은 diff와 명령 실행으로만
    선다. 그래서 판정 제출도 자유 서술이 아니라 verdict 툴 한 곳을 지난다."""
    from ..agent.heimdall import VERDICT_TOOL

    if role != "verifier":
        return f"과업: {task}", None, None

    changed = ", ".join((state.get("changed_files") or [])[:20]) or "(없음)"
    prompt = (
        f"검증하라. 요청: {task}\ncriteria: {criteria}\nrequired level: {level}\n"
        f"하니스 관측 변경 파일: {changed} (diff_lines={state.get('diff_lines', '?')}) — "
        "`git diff` / 파일 열람 / 실행으로 직접 확인하라.\n"
        "Worker 해설은 입력이 아니다 — diff와 명령 실행으로만 판정. 판정은 반드시 verdict 툴로 제출."
    )

    def _ack(_i: dict) -> str:
        return "판정 접수"

    return prompt, [VERDICT_TOOL], {"verdict": _ack}


def run_role_run(role: str, task: str, json_out: bool = False) -> int:
    from ..agent.heimdall import record_writes, role_prompt
    from ..agent.quest_bridge import ql
    from ..agent.session import AgentSession, make_client

    root = os.getcwd()
    errors.set_json_surface(json_out)
    sid = os.environ.get("CLAUDE_SESSION_ID") or "bridge"
    state = _bridge_preconditions(root, role, sid)
    default, rrp = _placed_provider(root, role)

    criteria = state.get("criteria") or []
    level = "full" if state.get("full_required") else "micro"  # gate와 동일 기준 (결정론 도출)
    prompt, extra, handlers = _turn_inputs(role, task, state, criteria, level)

    def _out(s: str) -> None:
        # `--json`이면 모델이 흘리는 글은 stderr로 간다 — stdout은 마지막 결과 한 덩어리의
        # 자리다. `asgard run --json`이 이미 같은 계약을 쓴다.
        stream = sys.stderr if json_out else sys.stdout
        stream.write(s)
        stream.flush()

    # 역할 배치(스웜)는 브릿지에도 선다 — 모드가 갈린다고 규율이 갈리면 그건 드리프트다.
    # 호스트(CC·Cursor·Codex)가 이 CLI로 역할 턴을 넘기면 그 턴은 배치된 에이전트의 홈에서
    # 돈다: 자기 1차 기억·자기 스킬·자기 설정.
    from ..swarm import resolve as _agent_for_role

    try:
        placed_agent = _agent_for_role(root, role=role)
    except Exception:
        placed_agent = ""

    sess = AgentSession(
        make_client(rrp),
        rrp,
        root,
        role_prompt(f"asgard-{role}.md"),
        extra_tools=extra,
        tool_handlers=handlers,
        on_text=_out,
        role=role,
        readonly=role != "worker",
        agent=placed_agent or None,
    )
    r = sess.run(prompt)

    result: dict = {
        "role": role,
        "provider": rrp.profile.name,
        "model": rrp.model,
        "placed": rrp is not default,
        "writes": r.writes,
        "verdict": None,
    }
    if role == "thinker":
        ql(root, "append", session=sid, stdin=json.dumps({"role": "thinker", "event": "plan", "criteria": criteria}))
        result["appended"] = "plan"
    elif role == "worker":
        record_writes(root, sid, r.writes)  # write-sentinel 미러 — sid가 호스트 세션과 일치할 때 증거가 된다
        ql(
            root,
            "append",
            session=sid,
            stdin=json.dumps(
                {"role": "worker", "event": "work", "changed_files": r.writes[:50], "commands": r.commands[-20:]}
            ),
        )
        result["appended"] = "work"
    else:
        v = next((c["input"] for c in r.tool_calls if c["name"] == "verdict"), None) or {
            "verdict": "FAIL",
            "criteria": criteria,
            "commands": [],
            "failure_sig": "no-verdict-submitted",
        }
        ev = {
            "role": "verifier",
            "event": "verify",
            "criteria": v.get("criteria") or criteria,
            "commands": v.get("commands") or [],
        }
        if v.get("failure_sig"):
            ev["failure_sig"] = v["failure_sig"]
        ql(root, "append", "--verdict", str(v["verdict"]), "--level", level, session=sid, stdin=json.dumps(ev))
        result["verdict"] = v
        result["appended"] = "verify"
    if json_out:
        _emit(result)
    else:
        print("\n" + json.dumps(result, ensure_ascii=False))
    return 0
