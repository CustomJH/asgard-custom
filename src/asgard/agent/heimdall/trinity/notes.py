"""턴에 얹는 글 — 배차 메모, 기억 갈무리, 의도 블록, 궤적 요약."""

from __future__ import annotations

from .... import ui
from ._shared import _RunState


class _NotesMixin(_RunState):
    """턴에 얹는 글 — 배차 메모, 기억 갈무리, 의도 블록, 궤적 요약.

    `TrinityRun` 가 상속한다 — 혼자서는 아무것도 아니다."""

    def _orchestration_note(self) -> str:
        """최종 보고에 붙는 오케스트레이션 줄 — 어떤 모양으로 돌았고 무엇이 오갔는가.

        아무 일도 없었으면 빈 문자열이다. 형상이 single 이고 질문도 없었던 퀘스트에 "오케스트
        레이션: single" 한 줄을 붙이면 그 줄은 매번 나오는 소음이 된다.

        Returns:
            앞에 줄바꿈이 붙은 보고 조각, 또는 실을 것이 없으면 빈 문자열.
        """
        lines = []
        shape = getattr(self.bifrost, "shape", "")
        if shape in ("graph", "squad"):
            # 감독 고리가 이미 거둔 보고와 아직 우편함에 남은 보고를 함께 센다. 한쪽만 보면
            # 수가 어긋난다 — 확인 처리된 묶음은 `drain` 이 다시 안 주고, 답 못 한 질문이 남은
            # 묶음은 다시 준다. 그래서 합치되 메시지 id 로 거른다.
            by_id = {str(m["id"]): m for m in self.unit_reports}
            by_id.update({str(m["id"]): m for m in self.bifrost.drain(None) if m.get("type") == "worker_done"})
            reports = list(by_id.values())
            tally = ""
            if reports:
                ok = sum(1 for m in reports if m.get("outcome") == "succeeded")
                tally = f" · 단위 보고 {len(reports)}건(성공 {ok})"
            lines.append(f"  {ui.dim('│ ⠶ 오케스트레이션: ' + shape + tally)}")
        for question, answer in self.coordinator_answers[:4]:
            lines.append(f"  {ui.dim('│ ⠶ 워커 질문: ' + question.splitlines()[0][:90])}")
            lines.append(f"  {ui.dim('│   답: ' + answer.splitlines()[0][:90])}")
        unanswered = self.bifrost.blocked_on()
        if unanswered:
            lines.append(f"  {ui.dim('│ ⠶ 답 못 한 워커 질문 ' + str(len(unanswered)) + '건')}")
        return ("\n" + "\n".join(lines)) if lines else ""

    def _tend_memory(self) -> None:
        """위그드라실 손질 신호 — 노른·패턴·2차 진화·프로젝트 mental model.

        외부 클라이언트는 Stop 훅(memory-activate)이 같은 네 패스를 띄운다. 네이티브 루프에만
        없으면 같은 사용자의 같은 기억이 **어느 호스트로 들어왔느냐에 따라 다른 속도로 자란다** —
        개인 메모리가 호스트에 무관해야 한다는 원칙(policy.CLIENT_MODES)과 어긋나는 자리였다.

        위 자가발전 넛지와 결이 다른 이유: 저쪽은 에이전트의 **능력**을 바꾸는 일이라 언제나
        사람 손이고, 이쪽은 advisory 지식의 손질이라 동의 경계를 등급이 쥔다 (`norn_auto`·
        `pattern_auto`, 기본 safe). 판정도 스폰도 각 모듈의 wake 단일 출처가 한다.

        훅과 달리 subprocess를 거치지 않는다 — 여기는 이미 파이썬 프로세스이고, due 판정은
        파일 두 개를 읽을 뿐이라 인터프리터를 새로 세울 값이 아니다. 침묵이 정상이다."""
        hd = self._hd
        for line in (
            self._norn_line(),
            self._pattern_line(),
            self._project_evolve_line(),
            self._project_learning_line(),
        ):
            if line:
                hd.on_text(f"  {ui.dim('│ ⠶ ' + line)}\n")

    def _norn_line(self) -> str | None:
        try:
            from ....memory.norn import wake

            return wake(self._hd.root)
        except Exception:
            return None  # 손질 신호 불능이 퀘스트 종료를 막지 않는다 (fail-open)

    def _pattern_line(self) -> str | None:
        try:
            from ....memory.pattern import wake

            return wake(self._hd.root)
        except Exception:
            return None

    def _project_evolve_line(self) -> str | None:
        try:
            from ....project_memory.evolve import wake

            return wake(self._hd.root)
        except Exception:
            return None

    def _project_learning_line(self) -> str | None:
        try:
            from ....project_memory.automation import wake

            return wake(self._hd.root)
        except Exception:
            return None

    def _intent_block(self) -> str:
        """사전 등록된 의도 — 무엇이 **의도된 선택**인지 판정자에게 알린다.

        판정자가 diff만 보면 사용자가 일부러 고른 것과 실수를 구별할 방법이 없어, 의도된 결정을
        결함으로 올리는 헛FAIL이 난다. 의도는 Worker의 자기서사가 아니다 — 사용자의 요청 원문과
        착수 전에 고정된 criteria(`가정:` 포함)만 담는다. 증거를 대체하지 않는다는 문장을 함께
        실어야 이 블록이 검증 면제로 오독되지 않는다."""
        assumptions = [c for c in map(str, self.cls.get("criteria") or []) if c.strip().startswith("가정:")]
        block = (
            "\n<intent>\nWhat Odin set out to accomplish, in their own words:\n"
            f"{self.request[:1500]}\n"
            "Decisions fixed before the work started (criteria): "
            f"{'; '.join(map(str, self.cls.get('criteria') or []))[:1200]}\n"
        )
        if assumptions:
            block += "Assumptions recorded in place of an unanswered decision: " + "; ".join(assumptions)[:600] + "\n"
        return (
            block + "</intent>\n"
            "Everything in that block was chosen on purpose. A change that follows it is not a defect for"
            " following it — but the block is intent, never evidence: it can never stand in for a"
            " verification command, and it is not the Worker's account of what it did.\n"
        )

    def _trajectory_note(self) -> str:
        """판정자에게 넘길 **하네스가 관측한 워커 실행 기록** — 워커의 말이 아니라 사실이다.

        판정자는 지금까지 요청·기준·바뀐 파일 목록·공개 표면만 받았다. 즉 **결과물만 보고
        무슨 일이 있었는지는 못 봤다.** 그런데 판정 품질을 가장 크게 움직이는 축이 바로 그
        입력량이다 — 하네스를 스스로 다시 쓰게 한 실험이 같은 모델로 76.4% 대 58% 를 낸 기제가
        "매 단계 실행 로그를 통째로 읽힌다"였다 (Cloud Codes, *Loop vs Graph Engineering*,
        영상 uM8pWgO12Bk; 그쪽 상한은 단계당 1,000만 토큰이고 종전 방법들은 2.6만 근처였다).
        같은 방향으로 값이 가장 큰 한 걸음이 이것이다.

        **독립성은 안 깎인다.** 여기 담기는 것은 하네스가 직접 적은 `cmd`·`exit_code`·차단
        여부뿐이고, 워커의 요약·자신감·"확인했습니다"는 한 글자도 안 들어간다. 판정자 계약의
        "Worker commentary is not input" 은 그대로다 — 오히려 워커가 **돌렸다고 말한 것과
        실제로 돈 것**을 대조할 수 있게 된다.

        마지막 verify 이후의 work 이벤트만, 30줄까지. 잘린 수는 숨기지 않는다."""
        hd = self._hd
        try:
            from ....hooks.quest_log import load_events

            events = load_events(hd.root, self.qid)
        except Exception:
            return ""
        recent: list[dict] = []
        for event in events:
            if event.get("event") == "verify":
                recent = []  # 판정이 지나갔다 — 그 뒤가 이번 턴의 궤적이다
            elif event.get("event") == "work":
                recent.append(event)
        rows: list[str] = []
        for event in recent:
            for command in event.get("commands") or []:
                if not isinstance(command, dict):
                    continue
                cmd = str(command.get("cmd") or "").strip()
                if not cmd:
                    continue
                if command.get("blocked"):
                    rows.append(f"  blocked  {cmd[:140]}")
                else:
                    rows.append(f"  exit {str(command.get('exit_code')):<4} {cmd[:140]}")
        if not rows:
            return ""
        shown, dropped = rows[:30], max(0, len(rows) - 30)
        tail = f"\n  … {dropped} more not shown\n" if dropped else "\n"
        return (
            "\nHarness-observed Worker execution record since the last verdict — this is what the harness"
            " itself watched run, not the Worker's account of it. Read it against the diff: a command the"
            " Worker never ran cannot support a claim, a command that exited non-zero and was never re-run is"
            " an unresolved failure, and a blocked command never executed at all.\n" + "\n".join(shown) + tail
        )
