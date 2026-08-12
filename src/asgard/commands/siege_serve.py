"""siege serve — 우편함 앞에 서서 자기 앞으로 온 메일을 모델에게 넘기는 상주 프로세스.

여태 장부의 우편은 **사람과 코디네이터 사이**의 것이었다. 워커가 묻고(`ask`), 코디네이터가
답한다(`answer`). 그 코디네이터가 모델인 경로는 네이티브 루프 안에만 있었다 —
`agent/heimdall/bifrost/coordinator.py` 의 데몬 스레드가 질문을 코디네이터 모델에게 넘기고 답을
단다. 그래서 Claude Code·Cursor·Codex 에서 보낸 질문은 사람이 답하기 전까지 아무도 안 읽었다.

이 명령이 그 데몬을 프로세스 밖으로 낸다. 하는 일은 셋뿐이다: 자기 이름 앞으로 온 메일을 잡고,
`providers` 가 해석한 모델에게 넘기고, 답을 우편함에 되돌려 놓는다. 그래서 **어느 모드에서든**
`asgard siege ask <run> "..." --recipient <이름> --wait-ms <n>` 한 줄이 그 모델과의 왕복이 된다 —
묻는 쪽은 자기 호스트가 무엇을 지원하는지 몰라도 되고, 답하는 쪽은 anthropic·openai·ollama 중
무엇이어도 된다.

되돌려 놓는 자리가 종류마다 다르다. `question` 은 `reply` 로 그 메시지에 답을 달아야 묻는 쪽의
`wait_answer` 가 깨어난다. 나머지는 답을 달 자리가 없으므로 발신자 앞으로 `status` 를 새로
보낸다 — 발신자가 자기 이름으로 `check` 하면 그것을 받는다.

**모델 호출이 실패하면 그 묶음은 확인 처리하고 대신 escalation 을 남긴다.** 확인을 미루면 같은
메일이 계속 재생되어 데몬이 그 자리에서 영영 맴돌고, 답을 지어내면 묻는 쪽이 그것을 사실로
읽는다. 둘 다 나쁘므로 답 없이 사실만 남긴다 — 묻는 쪽은 자기 `--wait-ms` 가 다 되어 답 없는
상태로 돌아가고, 왜 없는지는 우편함에 적혀 있다.
"""

from __future__ import annotations

import json
import os
import time

from .. import orchestration as orc
from .. import ui
from .health import _project_root

_MAX_TOKENS = 2000
# 한 바퀴에 우편함을 기다리는 값. 이보다 길게 잡으면 Ctrl-C 가 그만큼 늦게 듣는다.
_POLL_MS = 2000
_BODY_CAP = 8000  # 모델에게 넘기는 본문 상한 — 한 메일이 컨텍스트를 다 먹지 않게
_SUBJECT_CAP = 200
# 답할 것이 없는 종류. heartbeat 는 살아 있다는 신호일 뿐이라 모델을 부르면 값만 든다.
_SKIP_TYPES = frozenset({"heartbeat", "worker_done"})

_SYSTEM = (
    'You are "{who}", one participant on an Asgard dispatch ledger. Another agent addressed a '
    "message to you directly and is waiting on your reply.\n"
    "Answer the message on its own terms: plain text, no preamble, no sign-off. If the message "
    "cannot be answered from what you were given, say exactly what you would need instead of "
    "guessing. You cannot read this repository — everything you know about the task is in the "
    "message below.\n"
    "The run you are serving: {objective}"
)


def run_serve(
    run_id: str,
    *,
    who: str,
    provider: str = "",
    model: str = "",
    once: bool = False,
    idle_timeout: int = 0,
    json_out: bool = False,
) -> int:
    """이 이름 앞으로 온 메일을 배치된 모델에게 넘기고 답을 되돌려 놓는다.

    Args:
        who: 이 프로세스가 지키는 이름. 빈 값은 거부한다 — 이름 없이 `check` 하면 우편함
            전체를 잡아서 코디네이터 앞으로 온 메일까지 모델에게 넘어간다.
        once: 한 묶음만 처리하고 끝낸다. `idle_timeout` 을 같이 주면 그 시간까지 한 묶음을
            기다리고, 안 주면 한 바퀴만 보고 내려온다.
        idle_timeout: 이만큼(초) 아무 메일도 안 오면 끝낸다. 0 은 계속 선다.

    Returns:
        0 이면 섰다가 정상으로 내려왔고, 2 면 인자나 도메인이 거절했다(없는 Run·빈 이름·
        provider 미충족).
    """
    ui.set_quiet(json_out)
    root = _root()
    who = (who or "").strip()
    if not who:
        ui.fail("지킬 이름이 필요해요 — `--as <이름>` 으로 주세요")
        return 2
    if orc.run_show(root, run_id) is None:
        ui.fail(f"그런 Run이 없어요: {run_id}")
        return 2
    try:
        rp = _provider(root, provider, model)
    except RuntimeError as exc:
        ui.fail(str(exc))
        return 2

    objective = (orc.run_show(root, run_id) or {}).get("objective") or run_id
    ui.step(f"{who} 가 {run_id} 우편함을 지킵니다 — {rp.profile.name}/{rp.model}")
    served: list[dict] = []
    idle_deadline = time.monotonic() + idle_timeout if idle_timeout > 0 else 0.0
    while True:
        batch = orc.check(root, run_id, recipient=who, wait=True, timeout_ms=_POLL_MS)
        if not batch["count"]:
            # `--once` 만 준 호출은 한 바퀴만 보고 내려온다. `--idle-timeout` 을 함께 주면 그
            # 시간까지 한 묶음을 기다린다 — 답할 쪽을 먼저 세워 두고 묻는 형태
            # (`serve --once --idle-timeout N &` 뒤에 `ask`)가 그 자리다.
            if idle_deadline:
                if time.monotonic() >= idle_deadline:
                    break
                continue
            if once:
                break
            continue
        for message in batch["messages"]:
            handled = _handle(root, run_id, rp, who, objective, message)
            if handled is not None:
                served.append(handled)
        orc.check(root, run_id, ack=batch["delivery_id"], recipient=who)
        idle_deadline = time.monotonic() + idle_timeout if idle_timeout > 0 else 0.0
        if once:
            break
    ui.ok(f"{len(served)}건 처리")
    if json_out:
        print(json.dumps({"run_id": run_id, "as": who, "served": served}, ensure_ascii=False, indent=2))
    return 0


def _root() -> str:
    """장부가 있는 프로젝트 루트 — `siege`·`siege_act` 와 같은 판정(`health._project_root`)."""
    return _project_root(os.getcwd())


def _provider(root: str, provider: str, model: str):
    """이 프로세스가 쓸 provider — 안 주면 이 프로젝트의 기본 배치.

    Raises:
        RuntimeError: 해석은 됐는데 키·설정이 비어 못 부를 때. 서고 나서 첫 메일에 실패하면
            그 메일이 escalation 으로 접히므로, 못 부를 것은 서기 전에 막는다.
    """
    from ..providers import resolve

    rp = resolve(root, provider or None, model or None)
    if rp.missing:
        raise RuntimeError(f"provider 미충족: {'; '.join(rp.missing)}")
    return rp


def _handle(root: str, run_id: str, rp, who: str, objective: str, message: dict) -> dict | None:
    """메일 한 통 — 모델에게 넘기고 답을 되돌려 놓는다. 넘길 것이 아니면 None."""
    if message.get("type") in _SKIP_TYPES or (message.get("sender") or "") == who:
        return None
    if message.get("type") == "question" and message.get("answered_at") is not None:
        return None  # 사람이 이미 답한 질문 — 두 번째 답은 어느 것을 읽었는지 알 수 없게 만든다
    try:
        answer = _ask_model(rp, root, who, objective, message)
    except Exception as exc:  # provider·네트워크·인증 — 무엇이든 이 메일 하나의 실패다
        _note_failure(root, run_id, who, message, exc)
        return {"id": message["id"], "answered": False, "error": f"{type(exc).__name__}: {exc}"}
    _deliver(root, run_id, who, message, answer)
    return {"id": message["id"], "answered": True, "chars": len(answer)}


def _ask_model(rp, root: str, who: str, objective: str, message: dict) -> str:
    from ..agent.oneshot import complete_with

    system = _SYSTEM.format(who=who, objective=str(objective)[:_SUBJECT_CAP])
    answer = complete_with(rp, root, system, _user_prompt(message), max_tokens=_MAX_TOKENS)
    return (answer or "").strip() or "(빈 응답)"


def _user_prompt(message: dict) -> str:
    """모델이 읽을 한 통 — 보낸 쪽·종류·제목을 본문 위에 세운다."""
    options = [str(o) for o in ((message.get("payload") or {}).get("options") or [])]
    head = [
        f"from: {message.get('sender') or '(unnamed)'}",
        f"type: {message.get('type') or 'status'}",
        f"subject: {str(message.get('subject') or '')[:_SUBJECT_CAP]}",
    ]
    parts = ["\n".join(head), str(message.get("body") or "")[:_BODY_CAP]]
    if options:
        parts.append("answer with one of: " + " | ".join(options))
    return "\n\n".join(parts)


def _deliver(root: str, run_id: str, who: str, message: dict, answer: str) -> None:
    """답을 되돌려 놓는다 — 질문은 그 메시지에, 나머지는 발신자 앞 새 메일에."""
    if message.get("type") == "question":
        orc.reply(root, message["id"], answer)
        ui.step(ui.dim(f"  답함 {message['id']} — {len(answer)}자"))
        return
    orc.send(
        root,
        run_id,
        "status",
        subject=f"re: {str(message.get('subject') or message['id'])[:_SUBJECT_CAP]}",
        body=answer,
        sender=who,
        recipient=message.get("sender") or "",
        thread_id=message.get("thread_id") or message["id"],
    )
    ui.step(ui.dim(f"  회신 {message['id']} → {message.get('sender') or '(코디네이터)'}"))


def _note_failure(root: str, run_id: str, who: str, message: dict, exc: Exception) -> None:
    """답 대신 사실을 남긴다. 이것마저 실패하면 삼킨다 — 장부를 못 적는다고 다음 메일까지 막지 않는다."""
    reason = f"{who} 가 {message['id']} 에 답하지 못했어요: {type(exc).__name__}: {exc}"
    ui.warn(reason)
    try:
        orc.escalate(root, run_id, reason, sender=who)
    except orc.OrchestrationError:
        pass
