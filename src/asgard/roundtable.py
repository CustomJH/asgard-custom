"""원탁 — 모델 여럿을 좌석에 앉히고 회차를 거듭해 한 안건을 토론시킨다.

이 모듈이 있는 이유는 배차 장부가 못 하던 한 가지 때문이다. 장부의 우편함은 **한 번의 왕복**을
잘 하지만, 토론은 왕복이 아니라 회차다 — 각자 입장을 내고, 남의 입장을 읽고, 유지할지 바꿀지
말한다. 호스트(Claude Code·Cursor·Codex)의 서브에이전트로는 이것을 못 한다. 서브에이전트는
자기 턴이 끝나면 사라지고, 다음 회차에 다시 부르면 앞 회차를 모르는 다른 존재가 온다.

그래서 좌석을 프로세스가 아니라 **대화 기록**으로 정의한다. 좌석 하나는 이름·배역·뒷단
셋이고, 그 좌석이 지금까지 한 말은 이 프로세스의 리스트와 장부의 실(thread) 양쪽에 남는다.
회차마다 그 기록을 프롬프트에 다시 넣으므로 좌석은 안 꺼진 것처럼 행동한다 — 자기가 무엇을
주장했는지 알고, 남이 그것을 어떻게 반박했는지 읽고 답한다.

뒷단은 둘이다. API 좌석(`providers` 가 해석하는 모델)은 파일을 못 읽으므로 아는 것이 안건
본문뿐이고, CLI 좌석(`cc`·`codex`·`cursor`)은 이 저장소 안에서 읽기 전용으로 돌아 논의 대상
파일을 직접 연다. CLI 좌석은 자기 세션을 이어받아 자기 기억을 스스로 갖는다 — 그쪽에는 앞
회차를 다시 안 넣는다(`Seat.remembers_itself`). 어느 쪽이든 어느 파일을 말하는지는 모르므로
안건에 근거를 같이 넣어라.

CLI 좌석이 옵트인(`--auto-cli`)인 이유는 값이 아니라 동의다. 그 좌석은 저장소를 읽고 읽은
것이 그 벤더로 나가므로, CLI 가 깔려 있다는 사실이 보낸다는 결정을 대신할 수 없다.

합의는 세지 않고 **읽는다**. 교차 회차의 답에 `STANCE: MAINTAIN|MODIFY|WITHDRAW` 한 줄을
요구하고 그 줄만 집계한다. 자유 서술에서 찬반을 추론하면 없는 합의가 생기므로, 줄이 없으면
없다고 적는다.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import orchestration as orc

# 배역표 — ref 원탁의 좌석 이름을 그대로 옮겼다. 값은 좌석 프롬프트에 실리는 관점 지시다.
ROLES: dict[str, str] = {
    "researcher": (
        "You are the RESEARCHER. Lay out the viable approaches, say what current practice does, "
        "and name the one you recommend with the reason."
    ),
    "critic": (
        "You are the CRITIC. Judge the proposal against how this kind of system is usually built. "
        "Name the failure modes and edge cases you can see, and give a verdict."
    ),
    "challenger": (
        "You are the CHALLENGER. Attack the assumptions the proposal rests on. Say which one is "
        "most likely to be wrong and what the worst case costs. Be adversarial but concrete."
    ),
    "verifier": (
        "You are the VERIFIER. Produce the cases that would break this — boundaries, concurrency, "
        "error paths — and the checks that would catch each one."
    ),
    "advocate": (
        "You are the ADVOCATE. Argue that the proposal is workable: the path to build it, the "
        "order of the work, and the objections you expect with your answer to each."
    ),
    "strategist": (
        "You are the STRATEGIST. Judge this on the long horizon — what it commits us to, what it "
        "closes off, and whether it is worth doing now rather than later."
    ),
}

# 좌석을 안 주면 앉히는 셋. ref 의 Standard 원탁(사회자 + 연구원 + 비평가)에 도전자를 더한
# 구성이다 — 사회자는 이 명령을 부른 쪽이므로 좌석에 안 센다.
DEFAULT_SEATS: tuple[str, ...] = ("researcher", "critic", "challenger")

STANCES: tuple[str, ...] = ("MAINTAIN", "MODIFY", "WITHDRAW")

_MAX_TOKENS = 1600
# CLI 좌석 한 턴의 상한. 로컬 에이전트는 도구를 쓰며 답하므로 API 한 번보다 오래 걸리지만,
# 그 값에 회차 전체가 묶인다 — 좌석은 나란히 부르므로 한 회차는 가장 느린 좌석만큼 걸린다.
# 26-08-14 실측: codex 좌석이 벤치 안건 하나에 96.6초. 상한이 900초이던 동안에는 막힌 좌석
# 하나가 원탁 한 판을 15분 세웠고, 그 판은 좌석 셋이 아니라 둘로 돈 것이었다.
_CLI_TIMEOUT_S = 300.0
_BODY_CAP = 6000  # 남의 입장을 넣을 때 하나당 상한
_OWN_CAP = 4000  # 자기 앞 회차 하나당 상한
_MAX_ROUNDS = 5  # 회차 상한. 넘게 돌면 같은 말이 값만 쓴다


@dataclass
class Seat:
    """좌석 하나 — 이름, 배역, 모델, 그리고 이 좌석이 지금까지 한 말."""

    name: str
    role: str
    provider: str = ""
    model: str = ""
    turns: list[dict] = field(default_factory=list)  # {"round": n, "text": ...}
    thread_id: str = ""
    failed: str = ""  # 마지막 실패 사유. 비어 있으면 아직 실패한 적 없다
    session_id: str = ""  # CLI 좌석이 이어받는 그 CLI 의 세션. API 좌석은 늘 빈 값이다

    @property
    def instruction(self) -> str:
        return ROLES.get(self.role, f"You are the {self.role.upper()} at this table.")

    @property
    def is_cli(self) -> bool:
        """이 좌석이 로컬 에이전트 CLI 인가 — provider 자리에 peer 이름이 왔는가."""
        from .agent.runtime import PEER_KINDS

        return self.provider in PEER_KINDS

    @property
    def remembers_itself(self) -> bool:
        """자기 앞 회차를 프롬프트로 다시 안 줘도 되는 좌석 — CLI 세션을 이어받는 중일 때.

        API 좌석은 호출마다 백지라 우리가 기억을 만들어 준다. CLI 좌석은 자기 세션에 그
        대화가 남아 있으므로, 같은 것을 또 주면 같은 말을 두 번 읽힌다.
        """
        return bool(self.session_id)


def parse_seats(specs: list[str]) -> list[Seat]:
    """`name[:provider[:model]]` 목록을 좌석으로 — 이름이 배역이 아니면 배역은 이름 그대로.

    `critic`, `critic:openai`, `critic:openai:gpt-5.6`, `tyr=critic:ollama` 넷을 받는다.
    `=` 앞은 좌석 이름, 뒤는 배역이다 — 같은 배역에 둘을 앉힐 때 이름이 겹치지 않게 한다.

    Raises:
        ValueError: 이름이 비었거나 같은 이름이 둘일 때. 이름은 실(thread)의 열쇠라, 겹치면
            두 좌석의 기억이 한 대화로 섞인다.
    """
    seats: list[Seat] = []
    seen: set[str] = set()
    for spec in specs:
        head, _, tail = str(spec).strip().partition(":")
        name, _, role = head.partition("=")
        name = name.strip()
        role = (role or name).strip().lower()
        if not name:
            raise ValueError(f"좌석 이름이 비었어요: {spec!r}")
        if name in seen:
            raise ValueError(f"좌석 이름이 겹쳐요: {name}")
        seen.add(name)
        provider, _, model = tail.partition(":")
        seats.append(Seat(name=name, role=role, provider=provider.strip(), model=model.strip()))
    return seats


def auto_seats(roles: tuple[str, ...] = DEFAULT_SEATS, *, available: list[str] | None = None) -> list[Seat]:
    """이 기계에 실제로 있는 것으로 좌석을 채운다 — 좌석을 안 지정했을 때의 기본 배정.

    후보는 PATH 에 있는 에이전트 CLI 전부에 이 프로젝트의 기본 모델(빈 provider) 하나를 더한
    것이고, 배역 순서대로 하나씩 돌아가며 배정한다. 그래서 CLI 가 셋이면 세 좌석이 서로 다른
    벤더를 받고, 하나도 없으면 전원이 기본 모델을 받는다. 벤더를 흩는 것이 이 배정의 목적이다
    — 같은 모델 둘은 서로 동의하므로 두 번 물어도 한 번 물은 값만 난다.

    Args:
        available: 후보 CLI 를 직접 준다. 안 주면 PATH 를 조회한다 (시험이 여기로 고정한다).
    """
    from .agent.runtime import peers_present

    pool = list(available if available is not None else peers_present())
    pool.append("")  # 기본 모델 — CLI 가 모자랄 때 나머지 좌석이 앉는 자리
    return [Seat(name=role, role=role, provider=pool[i % len(pool)]) for i, role in enumerate(roles)]


def _position_prompt(agenda: str, seat: Seat) -> str:
    return (
        f"{seat.instruction}\n\n"
        f"AGENDA\n{agenda}\n\n"
        "Give your position on its own terms. No preamble, no sign-off. If the agenda does not "
        "carry enough to decide, say exactly what you would need. Under 400 words."
    )


def _cross_prompt(agenda: str, seat: Seat, others: list[tuple[str, str]], round_no: int) -> str:
    heard = "\n\n".join(f"[{who} said]\n{text[:_BODY_CAP]}" for who, text in others)
    mine = (
        ""
        if seat.remembers_itself
        else "\n\n".join(f"[you said, round {turn['round']}]\n{turn['text'][:_OWN_CAP]}" for turn in seat.turns)
    )
    return (
        f"{seat.instruction}\n\n"
        f"AGENDA\n{agenda}\n\n"
        f"{mine}\n\n"
        f"What the other seats argued:\n\n{heard}\n\n"
        f"Round {round_no}: answer them. Where they are right, say so and change your position; "
        "where they are wrong, say why with something specific. Do not repeat what you already "
        "said. End with exactly one line:\n"
        "STANCE: MAINTAIN | MODIFY | WITHDRAW"
    )


def read_stance(text: str) -> str:
    """답의 `STANCE:` 줄만 읽는다 — 없으면 빈 문자열.

    자유 서술에서 찬반을 추론하지 않는 것이 요지다. 추론하면 좌석이 안 한 말이 집계에 들어가고,
    그 집계를 읽는 사람은 그것을 좌석의 입장으로 읽는다.
    """
    for line in reversed(str(text or "").splitlines()):
        stripped = line.strip().lstrip("*_# ").upper()
        if not stripped.startswith("STANCE"):
            continue
        _, _, value = stripped.partition(":")
        for stance in STANCES:
            if stance in value:
                return stance
    return ""


def _default_complete(root: str, *, cli_timeout_s: float = _CLI_TIMEOUT_S):
    """좌석 하나를 부르는 함수를 만든다 — 좌석 종류에 따라 두 갈래다.

    provider 자리에 peer 이름(`cc`·`codex`·`cursor`)이 오면 그 CLI 를 한 턴 띄우고, 돌려받은
    세션 id 를 좌석에 남긴다. 다음 회차는 그 세션을 이어받으므로 CLI 좌석은 자기 대화를 자기가
    기억한다. 그 밖의 값은 `providers` 가 해석하는 모델이고, 해석 결과는 좌석마다 한 번만 든다.
    """
    from typing import cast

    from .agent.oneshot import complete_with
    from .agent.runtime import CliPeerRuntime, PeerKind, PeerSpec
    from .providers import ResolvedProvider, resolve

    cache: dict[tuple[str, str], ResolvedProvider] = {}
    peer = CliPeerRuntime(root, timeout_s=cli_timeout_s)

    def complete(seat: Seat, system: str, user: str) -> str:
        if seat.is_cli:
            # `is_cli` 가 PEER_KINDS 안에 있음을 이미 확인했다 — 형식만 좁힌다.
            kind = cast(PeerKind, seat.provider)
            # CLI 는 system·user 를 가르는 자리가 없다 — 한 프롬프트로 합쳐 보낸다.
            turn = peer.turn(PeerSpec(kind, model=seat.model), f"{system}\n\n{user}", seat.session_id)
            seat.session_id = turn.session_id
            return turn.text
        key = (seat.provider, seat.model)
        if key not in cache:
            rp = resolve(root, seat.provider or None, seat.model or None)
            if rp.missing:
                raise RuntimeError(f"provider 미충족: {'; '.join(rp.missing)}")
            cache[key] = rp
        return complete_with(cache[key], root, system, user, max_tokens=_MAX_TOKENS)

    return complete


def _speak(seat: Seat, complete, agenda: str, prompt: str, round_no: int) -> dict:
    """좌석 하나를 부르고 그 말을 좌석에 남긴다. 실패는 그 좌석 하나의 실패다."""
    system = f'You are "{seat.name}" at a round table on one agenda. {seat.instruction}'
    try:
        text = str(complete(seat, system, prompt) or "").strip()
    except Exception as exc:  # provider·네트워크·인증 — 어느 것이든 이 좌석의 이 회차만 죽는다
        seat.failed = f"{type(exc).__name__}: {exc}"
        return {"seat": seat.name, "round": round_no, "ok": False, "error": seat.failed, "text": ""}
    if not text:
        seat.failed = "빈 응답"
        return {"seat": seat.name, "round": round_no, "ok": False, "error": seat.failed, "text": ""}
    seat.turns.append({"round": round_no, "text": text})
    return {"seat": seat.name, "round": round_no, "ok": True, "error": "", "text": text}


def _record(root: str, run_id: str, seat: Seat, turn: dict) -> None:
    """전사를 장부에 남긴다 — 실패해도 토론은 계속한다 (기록은 토론의 조건이 아니다)."""
    if not run_id:
        return
    try:
        orc.send(
            root,
            run_id,
            "status",
            subject=f"round {turn['round']} — {seat.name}",
            body=turn.get("text") or turn.get("error") or "",
            sender=seat.name,
            thread_id=seat.thread_id,
        )
    except Exception:
        pass


def _round_one(pool, root: str, run_id: str, agenda: str, seats: list[Seat], complete) -> list[dict]:
    """1회차 — 좌석마다 안건만 보고 답한다. 남이 무엇을 말했는지는 아직 아무도 모른다."""
    done = list(pool.map(lambda s: _speak(s, complete, agenda, _position_prompt(agenda, s), 1), seats))
    for turn, seat in zip(done, seats, strict=True):
        _record(root, run_id, seat, turn)
    return done


def _cross_round(pool, root: str, run_id: str, agenda: str, seats: list[Seat], complete, round_no: int) -> list[dict]:
    """교차 회차 — 말한 좌석이 서로의 최신 입장을 읽고 답한다.

    말한 좌석이 둘 미만이면 빈 목록이다. 상대가 없는 반박은 같은 좌석에게 같은 안건을 다시
    묻는 것이고, 그 답은 값만 쓴다.
    """
    speaking = [seat for seat in seats if seat.turns]
    if len(speaking) < 2:
        return []
    latest = {seat.name: seat.turns[-1]["text"] for seat in speaking}
    prompts = [
        _cross_prompt(agenda, seat, [(n, t) for n, t in latest.items() if n != seat.name and t], round_no)
        for seat in speaking
    ]
    done = list(
        pool.map(
            lambda pair: _speak(pair[0], complete, agenda, pair[1], round_no),
            zip(speaking, prompts, strict=True),
        )
    )
    for turn, seat in zip(done, speaking, strict=True):
        _record(root, run_id, seat, turn)
    return done


def convene(
    root: str,
    agenda: str,
    seats: list[Seat],
    *,
    rounds: int = 2,
    run_id: str = "",
    complete=None,
    workers: int = 4,
) -> dict:
    """원탁을 연다 — 독립 입장 한 회차, 그 뒤 교차 회차 `rounds - 1` 번.

    Args:
        seats: 앉힐 좌석. 빈 목록은 거절한다 — 좌석 없는 원탁은 사회자 혼자다.
        rounds: 총 회차. 1이면 입장만 받고 교차 토론은 안 한다.
        run_id: 전사를 남길 장부 Run. 빈 값이면 기록 없이 돈다.
        complete: `(seat, system, user) -> str`. 시험이 여기로 가짜 좌석을 넣는다.
        workers: 한 회차에 동시에 부르는 좌석 수. 좌석은 서로를 안 기다린다.

    Returns:
        `{"agenda", "rounds", "seats": [...], "turns": [...], "stances": {...}, "failed": [...],
        "secs": <벽시계 소요>}`. `secs` 는 좌석이 나란히 도는 시간이라 회차별 가장 느린 좌석의
        합에 가깝지 발언 하나하나의 합이 아니다 — 부른 쪽이 값을 보고 좌석 수를 정하는 축이다.

    Raises:
        ValueError: 좌석이 없거나 회차가 1 미만일 때.
    """
    if not seats:
        raise ValueError("좌석이 없어요 — `--seat <이름>` 으로 최소 하나는 앉혀 주세요")
    if rounds < 1:
        raise ValueError("회차는 1 이상이어야 해요")
    rounds = min(rounds, _MAX_ROUNDS)
    complete = complete or _default_complete(root)
    stamp = str(int(time.time()))
    for seat in seats:
        seat.thread_id = seat.thread_id or f"rt_{stamp}_{seat.name}"

    turns: list[dict] = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(seats)))) as pool:
        turns.extend(_round_one(pool, root, run_id, agenda, seats, complete))
        for round_no in range(2, rounds + 1):
            done = _cross_round(pool, root, run_id, agenda, seats, complete, round_no)
            if not done:
                break  # 말한 좌석이 하나뿐이면 반박할 상대가 없다
            turns.extend(done)

    stances = {turn["seat"]: read_stance(turn["text"]) for turn in turns if turn["ok"] and turn["round"] > 1}
    return {
        "agenda": agenda,
        "rounds": rounds,
        "run_id": run_id,
        "seats": [{"name": s.name, "role": s.role, "provider": s.provider, "model": s.model} for s in seats],
        "turns": turns,
        "stances": stances,
        "failed": [{"seat": s.name, "reason": s.failed} for s in seats if s.failed],
        "secs": round(time.monotonic() - started, 1),
    }
