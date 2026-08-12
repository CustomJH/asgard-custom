"""memory 커맨드 — 자동 저장. 턴 동기화·게이트 상태·기계 승인."""

import collections
import contextlib
import json as _json
import os
import sys
from collections.abc import Callable

from ... import errors, ui
from ...memory_bridge import (
    GATE_OFF,
    GATE_ON,
    GATE_UNAPPROVED,
    auto_retain_turns_state,
    autosave_state,
    backend_target,
    find_config,
    is_backend_trusted,
)
from ...project_memory import propose_completion, retain_turn
from ._core import _guard

_TRANSCRIPT_TAIL = 400  # 기록 꼬리에서 볼 줄 수 — 정정을 부른 응답은 바로 앞 턴이다


def _auto_retain_skip_reason(gate: str, cfg: dict) -> str:
    """턴 원문을 안 보낸 이유 — 이 문자열이 사람이 받는 유일한 설명이다.

    "미승인"과 "미신뢰"를 가르는 이유는 다음 손짓이 다르기 때문이다: 앞쪽은 이 기계에서 승인
    한 번이면 되고, 뒤쪽은 backend 연결부터 다시 봐야 한다. 게이트는 둘 다 GATE_UNAPPROVED로
    묶으므로(허가는 신뢰된 target에만 붙는다) 여기서 한 번 더 갈라 준다."""
    if gate == GATE_OFF:
        return "automatic raw-turn retain is disabled"
    if not is_backend_trusted(cfg):
        return "project memory backend is not trusted on this machine"
    return (
        "automatic raw-turn retain is requested by this repository but not approved on this machine; "
        "run: asgard memory autosave approve --tier project"
    )


def _completion_updates(root: str, cfg: dict, payload: dict, mode: str) -> dict:
    """검증 완료 기록 제안과 파생 학습 wake를 같은 lifecycle 결과로 묶는다."""
    output: dict[str, object] = {}
    if cfg.get("auto_propose_completion", True) and payload.get("verified"):
        proposal = propose_completion(
            root,
            cfg,
            session_id=str(payload.get("session_id") or mode),
            request=str(payload.get("user_text") or ""),
            response=str(payload.get("assistant_text") or ""),
            changed_files=list(payload.get("changed_files") or []),
            evidence=list(payload.get("evidence") or []),
            verified=True,
        )
        if proposal.status == "proposed":
            output["proposal"] = {
                "approval_id": proposal.approval_id,
                "record_id": proposal.record_id,
                "preview": proposal.preview,
            }
    # 실제 원격 작업은 분리 프로세스가 맡고, 연결·신뢰·주기 판정 실패는 현재 host turn에
    # 영향을 주지 않는다.
    with contextlib.suppress(Exception):
        from ...project_memory.automation import wake

        automation = wake(root)
        if automation:
            output["automation"] = automation
    return output


def _stage_correction(payload: dict) -> None:
    """사용자 정정 신호 채굴 (제2 채굴원) — 개인/진화 스코프라 프로젝트 메모리 연결과 무관하게
    항상 시도한다. 탐지 실패·중복·오염 = 조용히 넘어간다 (턴을 막지 않는다).

    뿌리는 cwd 가 아니라 git toplevel 이다. 읽는 쪽(`memory tick` → evolution.mine)이 toplevel 을
    쓰므로, 여기서 cwd 를 쓰면 저장소 하위에서 연 세션의 정정이 아무도 안 읽는
    `<하위>/.asgard/evolution/corrections.jsonl` 에 쌓인다 — 쓰는 자리와 읽는 자리가 갈리면
    채굴원이 조용히 죽는다 (같은 이유로 backends.run_tick 이 먼저 고친 자리)."""
    with contextlib.suppress(Exception):
        from ...evolution import correction_signal, record_correction
        from ..evolve import _root as _git_toplevel

        user_text = str(payload.get("user_text") or "")
        # 기록을 읽는 것은 정정으로 판정된 뒤다 — 판정은 정규식 하나이고 기록은 메가바이트다.
        before = _assistant_before(str(payload.get("transcript_path") or "")) if correction_signal(user_text) else ""
        record_correction(
            _git_toplevel(),
            user_text,
            str(payload.get("assistant_text") or ""),
            assistant_before=before,
        )


def _assistant_before(path: str) -> str:
    """정정 발화 **직전**의 어시스턴트 응답 — 정정을 부른 그 답.

    훅이 넘기는 짝은 (정정 발화, 그 정정에 **답한** 응답)이라, 저장된 응답은 잘못한 답이 아니라
    이미 고쳐진 답이다. 그것을 증거로 들면 카드가 수정 결과를 실수로 지목한다.

    기록 꼬리만 본다 — 정정을 부른 응답은 바로 앞 턴이고, 앞부터 읽으면 긴 세션에서 파일 전체를
    사게 된다. 못 읽으면 빈 문자열이고, 그때는 카드가 이 항목 없이 뜬다 (채굴이 턴을 막지 않는다)."""
    rows = _transcript_tail(path)
    # 마지막 사용자 발화가 정정이다 — 그 앞의 어시스턴트 응답을 되짚는다.
    last_user = next((i for i in range(len(rows) - 1, -1, -1) if rows[i][0] == "user"), None)
    if last_user is None:
        return ""
    return next((text for role, text in reversed(rows[:last_user]) if role == "assistant"), "")


def _transcript_tail(path: str) -> list[tuple[str, str]]:
    """기록 꼬리의 (역할, 글) 목록 — 못 읽으면 빈 목록."""
    if not path:
        return []
    rows: list[tuple[str, str]] = []
    with contextlib.suppress(OSError):
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = list(collections.deque(handle, maxlen=_TRANSCRIPT_TAIL))
        rows = [pair for pair in (_transcript_row(line) for line in lines) if pair]
    return rows


def _transcript_row(line: str) -> tuple[str, str] | None:
    """기록 한 줄 → (역할, 글). 찢어진 줄이나 글 없는 줄은 None."""
    # 객체가 아닌 JSON 한 줄(`[1,2]`·`"hi"`·`42`)은 `.get` 에서 AttributeError 를 낸다 —
    # ValueError 만 잡으면 그 줄 하나가 정정 채굴 전체를 조용히 끊는다.
    with contextlib.suppress(ValueError, AttributeError):
        row = _json.loads(line)
        message = row.get("message") if isinstance(row.get("message"), dict) else row
        role = str(message.get("role") or row.get("role") or row.get("type") or "")
        text = _plain_text(message.get("content"))
        if role in ("user", "assistant") and text:
            return role, text
    return None


def _plain_text(content: object) -> str:
    """기록의 content(문자열 또는 블록 목록)에서 사람이 읽는 글만 이어 붙인다."""
    if isinstance(content, str):
        return content.strip()
    parts = [
        str(block.get("text") or "")
        for block in (content if isinstance(content, list) else [])
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return " ".join(part for part in parts if part).strip()


def run_sync_turn(mode: str) -> int:
    """hook 전용 JSON stdin 표면 — 자동 turn retain과 완료 proposal을 한 lifecycle 호출로 처리."""
    try:
        raw = sys.stdin.read(200_001)
        if len(raw) > 200_000:
            raise ValueError("turn payload too large")
        payload = _json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("turn payload must be a JSON object")
        _stage_correction(payload)
        # 개인 에피소드 레인 적재 — 네이티브 루프의 `_persist_turn`이 하는 일을 외부
        # 클라이언트는 여기서 한다. 프로젝트 메모리 연결 **앞**에 두는 것이 핵심이다:
        # 개인 대화 원문은 팀 뱅크와 무관하고, 아래 early-return 뒤에 두면 프로젝트가
        # 안 붙은 저장소에서는 에피소드가 영영 안 쌓인다 (26-07-28 실측 결함).
        # 원문은 credential 편집(turn_store._redact) 후 0600 로컬 파일에만 남는다.
        with contextlib.suppress(Exception):
            from ...agent.turn_store import append_turn

            append_turn(
                os.getcwd(),
                str(payload.get("user_text") or ""),
                str(payload.get("assistant_text") or ""),
                quest_id=str(payload.get("quest_id") or "") or None,
                session_id=str(payload.get("session_id") or mode),
            )
        found = find_config(os.getcwd())
        if not found:
            print(_json.dumps({"status": "skipped", "reason": "project memory not connected"}))
            return 0
        root, cfg = found
        output: dict[str, object]
        # 참/거짓으로 읽으면 세 상태 중 둘이 한 칸에 뭉친다: 리포가 요청하지 않은 것과 리포가
        # 요청했는데 이 기계가 승인하지 않은 것이 똑같이 "꺼짐"으로 보이고, 뒤쪽 사람은 자기가
        # 무엇을 해야 하는지 어디서도 못 듣는다. 판정은 게이트 함수 하나가 한다.
        gate = auto_retain_turns_state(cfg)
        if gate == GATE_ON:
            result = retain_turn(
                root,
                cfg,
                session_id=str(payload.get("session_id") or mode),
                turn_id=str(payload.get("turn_id") or "turn"),
                user_text=str(payload.get("user_text") or ""),
                assistant_text=str(payload.get("assistant_text") or ""),
                mode=mode,
            )
            output = {
                "status": result.status,
                "document_id": result.document_id,
                "reason": result.reason,
            }
        else:
            output = {
                "status": "skipped",
                "document_id": "",
                "reason": _auto_retain_skip_reason(gate, cfg),
            }
        output.update(_completion_updates(root, cfg, payload, mode))
        print(_json.dumps(output, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(_json.dumps({"status": "failed", "reason": type(exc).__name__}))
        return 0  # lifecycle 메모리 장애가 host turn을 막으면 안 된다


_AUTOSAVE_TIERS = ("personal", "project", "both")
_AUTOSAVE_STATES = ("on", "off", "approve", "revoke")


def _project_gates() -> tuple[tuple[str, str, str, Callable[[dict], str]], ...]:
    """2차에서 이 기계의 승인을 요구하는 손잡이들 — (이름, grant, 설명, 게이트 판정기).

    표로 두는 이유는 승인 화면이 "리포가 무엇을 요청했는가"를 **빠짐없이** 말해야 하기
    때문이다: 손잡이가 늘면 여기 한 줄만 붙어도 상태 표시·승인·철회가 함께 따라온다.
    grant 이름을 늦게 부르는 것은 정본이 memory_bridge라서다 — 여기서 베끼지 않는다."""
    from ...memory_bridge import GRANT_AUTO_RETAIN_TURNS, GRANT_AUTOSAVE

    return (
        (
            "autosave",
            GRANT_AUTOSAVE,
            "에이전트가 정제한 record 한 건을 승인 없이 정본·팀 뱅크에 써요",
            autosave_state,
        ),
        (
            "auto_retain_turns",
            GRANT_AUTO_RETAIN_TURNS,
            "사람이 쓴 대화 턴 원문을 통째로 팀 뱅크에 보내요",
            auto_retain_turns_state,
        ),
    )


def _autosave_state() -> tuple[bool, dict[str, str] | None]:
    """(1차 켜짐, 2차 게이트 상태들) — 2차는 프로젝트 메모리 미연결이면 None (끈 것과 다르다).

    2차를 참/거짓이 아니라 상태 이름으로 돌려주는 이유: "리포가 요청했는데 이 기계가 미승인"이
    참/거짓 한 칸에서는 그냥 off로 보인다. 그 사람은 커밋된 설정을 보고 켜졌다고 믿는다."""
    from ...memory import autosave_enabled as personal_on

    found = find_config(os.getcwd())
    if not found:
        return personal_on(), None
    cfg = found[1]
    return personal_on(), {name: judge(cfg) for name, _grant, _why, judge in _project_gates()}


def _gate_label(state: str) -> str:
    """게이트 상태의 사람 표기 — 미승인은 다음 손짓까지 같이 말해야 쓸모가 있다."""
    if state == GATE_ON:
        return "on"
    if state == GATE_UNAPPROVED:
        return "리포가 요청함 · 이 기계 미승인 (asgard memory autosave approve --tier project)"
    return "off"


def _approval_target(tier: str) -> dict:
    """이 기계 승인을 얹을 2차 설정 — 못 얹는 세 사유를 여기서 한 번에 거른다.

    셋의 종료 코드가 갈리는 것이 요점이다. 잘못 고른 tier는 부른 쪽이 고치면 풀리니 2고,
    연결·신뢰는 이 기계의 환경이 안 선 것이라 인자를 고쳐도 안 풀리니 1이다."""
    if tier == "personal":
        raise errors.InvalidInput(
            "이 기계 승인은 프로젝트 기억에만 있어요 — 개인 기억은 `on|off`로 바로 켜요",
            remedy="asgard memory autosave on --tier personal",
            detail={"tier": tier},
        )
    found = find_config(os.getcwd())
    if not found:
        raise errors.Unavailable("프로젝트 메모리가 아직 연결 안 됐어요", remedy="asgard memory connect <endpoint>")
    cfg = found[1]
    if not is_backend_trusted(cfg):
        # 허가는 신뢰된 target에만 저장된다 (`trust.machine_grants`) — 여기서 안 세우면 memory_bridge가
        # PermissionError를 던지고, 사람은 "권한 없음"만 듣고 무엇을 해야 하는지는 못 듣는다.
        raise errors.Unavailable(
            "이 기계는 아직 이 backend를 믿지 않아요", remedy="먼저 asgard memory connect <endpoint>"
        )
    return cfg


def _run_machine_approval(state: str, tier: str, yes: bool, json_out: bool) -> int:
    """이 기계의 2차 승인/철회 — 리포 설정은 한 글자도 안 건드린다.

    리포와 기계를 갈라 두는 것이 요점이다. `.asgard/asgard-setting-project.json`은 git으로
    공유되는 파일이라 거기 쓰는 순간 팀 전원의 설정을 고치게 되고, 남의 기계에서 승인하려던
    사람이 남의 저장소를 더럽힌다. 승인은 `~/.asgard`의 trust store에만 저장된다."""
    from ...memory_bridge import grant_machine_approval, revoke_machine_approval

    cfg = _approval_target(tier)
    gates = [(name, grant, why, judge(cfg)) for name, grant, why, judge in _project_gates()]
    if state == "revoke":
        # 철회는 조이는 쪽이라 되묻지 않는다. 전부 거두는 것도 의도다: "무엇을 철회할까요"를
        # 고르게 하면 하나를 놓친 사람이 켜진 줄 모르는 손잡이를 남긴다.
        revoked = [name for name, grant, _why, _gate in gates if revoke_machine_approval(cfg, grant)["changed"]]
        if json_out:
            print(_json.dumps({"revoked": revoked}, ensure_ascii=False))
            return 0
        ui.head("memory autosave · 이 기계의 승인 철회")
        for name in revoked:
            ui.ok(f"철회 · {name}")
        if not revoked:
            ui.step("이 기계에서 승인한 게 없어요")
        ui.step("리포 설정은 그대로예요 — 이 기계에서만 껐어요")
        return 0
    wanted = [row for row in gates if row[3] != GATE_OFF]
    if not wanted:
        ui.step("이 저장소는 자동 저장을 요청하지 않았어요 — 승인할 게 없네요")
        ui.step("리포에 요청을 적으려면: asgard memory autosave on --tier project")
        return 0
    pending = [row for row in wanted if row[3] != GATE_ON]
    ui.head("memory autosave · 이 저장소가 요청하는 것")
    for name, _grant, why, gate in wanted:
        line = f"{name} · {why}"
        (ui.ok if gate == GATE_ON else ui.warn)(f"{line} — {'이미 승인함' if gate == GATE_ON else '미승인'}")
    if not pending:
        ui.ok("이 기계에선 이미 승인돼 있어요")
        return 0
    target = backend_target(cfg)
    ui.step(f"대상 · engine={target['engine']} · project_id={target['project_id']}")
    ui.step("승인하면 이 기계에서만 켜져요 — 팀의 다른 기계는 각자 승인해야 해요")
    if not yes:
        if not sys.stdin.isatty():
            # 물을 수 없는 자리다 — 순서가 어긋난 것이지 우리가 깨진 것이 아니다 (conflict=2,
            # `agent delete`가 같은 상황을 같은 값으로 낸다).
            raise errors.Conflict(
                "대화형이 아닐 땐 --yes 없이는 승인하지 않을게요",
                remedy=f"asgard memory autosave {state} --tier {tier} --yes",
            )
        if input("이 기계에서 승인할까요? [y/N] ").strip().lower() not in ("y", "yes"):
            ui.step("승인하지 않았어요")
            return 0
    granted = [name for name, grant, _why, _gate in pending if grant_machine_approval(cfg, grant)["granted"]]
    if json_out:
        print(_json.dumps({"granted": granted}, ensure_ascii=False))
        return 0
    for name in granted:
        ui.ok(f"승인 · {name}")
    return 0


def _check_autosave_args(state: str | None, tier: str) -> None:
    """받을 수 있는 tier·상태인가 — 철자를 고치면 풀리는 잘못이라 InvalidInput(2)."""
    if tier not in _AUTOSAVE_TIERS:
        raise errors.InvalidInput(
            f"tier는 {' | '.join(_AUTOSAVE_TIERS)} 중 하나여야 해요",
            remedy=f"--tier {_AUTOSAVE_TIERS[0]}",
            detail={"tier": tier},
        )
    if state is not None and state not in _AUTOSAVE_STATES:
        raise errors.InvalidInput(
            f"상태는 {' | '.join(_AUTOSAVE_STATES)} 중 하나여야 해요",
            remedy=f"asgard memory autosave {' | '.join(_AUTOSAVE_STATES)}",
            detail={"state": state},
        )


def run_autosave(state: str | None, tier: str, json_out: bool = False, yes: bool = False) -> int:
    """기억 자동저장 토글 — 승인 왕복을 켜고 끄는 하나뿐인 표면 (1차·2차 각각).

    상태만 묻는 호출(state=None)이 기본이다: 설정은 조용히 바뀌면 안 되고, 조용히 켜져 있어도
    안 된다. 켜 놓고 잊은 자동저장은 "왜 이게 저장돼 있지"의 답을 아무 데서도 못 찾게 만든다.

    `on|off`는 **어디에 적히는가**가 계층마다 다르다: 1차는 이 기계의 글로벌 설정이고, 2차는
    git으로 공유되는 리포 설정이라 켰다고 켜지지 않는다 — 그 위에 `approve|revoke`가 이 기계의
    허가를 얹는다. 명령을 새로 만들지 않고 여기에 얹는 이유는 사람이 찾을 자리가 하나여야
    하기 때문이다: "자동저장이 왜 안 되지"의 답은 언제나 `asgard memory autosave`에 있다."""
    errors.set_json_surface(json_out)

    def _do() -> int:
        _check_autosave_args(state, tier)
        if state in ("approve", "revoke"):
            return _run_machine_approval(state, tier, yes, json_out)
        want = state == "on"
        if state is not None and tier in ("personal", "both"):
            from ...settings import own_global, save_global

            save_global("memory", {**own_global("memory"), "autosave": want})
        if state is not None and tier in ("project", "both"):
            found = find_config(os.getcwd())
            if not found:
                ui.warn("프로젝트 메모리가 연결 안 돼 있어서 그쪽 자동저장은 건너뛸게요 (asgard memory connect)")
            else:
                from ...settings import load_project, save_project

                root = found[0]
                section = dict(load_project(root).get("project_memory") or {})
                save_project(root, "project_memory", {**section, "autosave": want})
        personal, project = _autosave_state()
        save_gate = project.get("autosave", GATE_OFF) if project else GATE_OFF
        turns_gate = project.get("auto_retain_turns", GATE_OFF) if project else GATE_OFF
        if json_out:
            # `project`는 옛 뜻(실제로 켜졌는가)을 그대로 지킨다 — 상태 이름으로 바꾸면 "off"가
            # 참인 문자열이 되어 이 값을 참/거짓으로 읽던 쪽이 조용히 반대로 판정한다.
            # 세 상태는 `_state` 키에 따로 넣는다.
            print(
                _json.dumps(
                    {
                        "personal": personal,
                        "project": None if project is None else save_gate == GATE_ON,
                        "project_state": None if project is None else save_gate,
                        "project_auto_retain_turns": None if project is None else turns_gate,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        ui.head("memory autosave")
        ui.step(f"1차 개인 기억 (memory.autosave)          · {'on' if personal else 'off'}")
        ui.step(
            "2차 프로젝트 기억 (project_memory.autosave) · " + ("미연결" if project is None else _gate_label(save_gate))
        )
        if turns_gate != GATE_OFF:
            # 같은 허가 축에 있는데 이 화면에만 없으면, 켜진 줄 모르는 손잡이가 하나 남는다.
            ui.step("2차 턴 원문 자동 적재 (auto_retain_turns) · " + _gate_label(turns_gate))
        if personal or save_gate == GATE_ON:
            ui.step("자동저장을 켜도 인젝션·credential 검사와 중복 병합은 그대로 거쳐요")
        elif save_gate == GATE_UNAPPROVED:
            ui.step("이 저장소는 요청해 뒀어요 — 이 기계에서 켜려면: asgard memory autosave approve --tier project")
        else:
            ui.step("켜기: asgard memory autosave on [--tier personal|project|both]")
        return 0

    return _guard(_do)
