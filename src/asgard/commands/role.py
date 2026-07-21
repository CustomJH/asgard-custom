"""role — Trinity 역할 브릿지 CLI (claude-code / codex / cursor → 배치 provider 위임).

호스트 도구가 자기 내부 모델 대신 `[trinity.<role>]` 배치 provider 로 역할 턴을 실행할 때
부른다 (asgard-provider 스킬이 안내). 퀘스트 로그 기록은 CLI 가 수행 — 프로토콜 준수가 모델 순응이
아니라 코드 경로다 (네이티브 루프와 같은 원칙, heimdall.py 참조). 게이트 판정은 그대로
verifier-gate 몫. `[bridge]` 게이트 판단은 호스트 몫 — 이 CLI 는 사실(list)과 실행(run)만.
"""

import json
import os
import sys
from typing import Any, Callable

from ..providers import (
    PROVIDERS,
    TRINITY_EXTRA_ROLES,
    TRINITY_ROLES,
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
        raise ValueError(f"host 은 {'/'.join(MODEL_HOSTS)} 중 하나")
    valid_roles = _native_roles() if host == "native" else tuple(AGENT_MODEL_DEFAULTS[host])
    if role not in valid_roles:
        raise ValueError(f"{host} role 은 {'/'.join(valid_roles)} 중 하나")
    if model:
        model = normalize_model_id(model)
        if not model:
            raise ValueError("유효한 model ID 필요")
    if provider and provider not in PROVIDERS:
        raise ValueError(f"provider 은 {'/'.join(PROVIDERS)} 중 하나")

    section = f"trinity.{role}" if host == "native" else f"agent_models.{host}.{role}"
    if reset:
        if model or effort or provider:
            raise ValueError("--reset 은 model/--effort/--provider 와 함께 사용할 수 없음")
        path = save_config_section(root, section, None)
    else:
        values = project_section(root, section)
        if host == "native":
            if effort:
                raise ValueError("native 는 --effort 대신 provider/model 배치를 사용")
            if not (model or provider):
                raise ValueError("native 설정에는 model 또는 --provider 필요")
            if model:
                values["model"] = model
            if provider:
                values["provider"] = provider
        else:
            if provider:
                raise ValueError("--provider 는 native 에서만 사용 가능")
            if host == "cursor" and effort:
                raise ValueError("Cursor effort 는 model slug에 포함해 설정")
            if not (model or effort):
                raise ValueError("hosted 설정에는 model 또는 --effort 필요")
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


def run_role_model(
    host: str | None = None,
    role: str | None = None,
    model: str | None = None,
    *,
    effort: str | None = None,
    provider: str | None = None,
    reset: bool = False,
) -> int:
    root = os.getcwd()
    if not any((host, role, model, effort, provider, reset)):
        print(json.dumps(role_model_state(root), ensure_ascii=False, indent=2))
        return 0
    if not host or not role:
        print(json.dumps({"error": "host 와 role 이 필요"}, ensure_ascii=False), file=sys.stderr)
        return 2
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
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def run_role_list() -> int:
    root = os.getcwd()
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
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def run_role_run(role: str, task: str) -> int:
    from ..agent.heimdall import VERDICT_TOOL, _record_writes, _role_prompt
    from ..agent.session import AgentSession, make_client, ql

    root = os.getcwd()
    if role not in TRINITY_ROLES:
        print(json.dumps({"error": f"role 은 {'/'.join(TRINITY_ROLES)} 중 하나"}), file=sys.stderr)
        return 2
    sid = os.environ.get("CLAUDE_SESSION_ID") or "bridge"
    try:
        state = json.loads(ql(root, "state", session=sid).stdout or "{}")
    except Exception:
        state = {}
    if not state.get("quest_id"):
        print(json.dumps({"error": "활성 quest 없음 — 호스트가 먼저 quest-log open 을 실행해야 한다"}), file=sys.stderr)
        return 1

    default = resolve(root)
    rrp = resolve_trinity(root, default)[role]
    if rrp.missing:
        print(json.dumps({"error": f"[trinity.{role}] 미충족: " + "; ".join(rrp.missing)}), file=sys.stderr)
        return 1

    criteria = state.get("criteria") or []
    level = "full" if state.get("full_required") else "micro"  # gate 와 동일 기준 (결정론 도출)
    extra: list[dict] | None = None
    handlers: dict[str, Callable[[dict], str]] | None = None
    if role == "verifier":
        changed = ", ".join((state.get("changed_files") or [])[:20]) or "(없음)"
        prompt = (
            f"검증하라. 요청: {task}\ncriteria: {criteria}\nrequired level: {level}\n"
            f"하니스 관측 변경 파일: {changed} (diff_lines={state.get('diff_lines', '?')}) — "
            "`git diff` / 파일 열람 / 실행으로 직접 확인하라.\n"
            "Worker 해설은 입력이 아니다 — diff 와 명령 실행으로만 판정. 판정은 반드시 verdict 툴로 제출."
        )

        def _ack(_i: dict) -> str:
            return "판정 접수"

        extra = [VERDICT_TOOL]
        handlers = {"verdict": _ack}
    else:
        prompt = f"과업: {task}"

    def _out(s: str) -> None:
        sys.stdout.write(s)
        sys.stdout.flush()

    sess = AgentSession(
        make_client(rrp),
        rrp,
        root,
        _role_prompt(f"asgard-{role}.md"),
        extra_tools=extra,
        tool_handlers=handlers,
        on_text=_out,
        role=role,
        readonly=role != "worker",
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
        _record_writes(root, sid, r.writes)  # write-sentinel 미러 — sid 가 호스트 세션과 일치할 때 증거가 된다
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
    print("\n" + json.dumps(result, ensure_ascii=False))
    return 0
