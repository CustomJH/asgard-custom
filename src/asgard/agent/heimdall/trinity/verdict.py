"""판정 턴 — 결정론 베이스라인, 미시 형상 게이트, 문체 게이트, 그리고 LLM 판정자."""

from __future__ import annotations

import json
import os

from .... import theme, ui
from ....hooks.quest_log import EMPTY as _EMPTY_DIFF
from ....hooks.quest_log import inspection_evidence as _inspection_evidence
from ....hooks.quest_log import trivial_evidence as _trivial_evidence
from ...quest_bridge import gate, ql
from ..classify import _gate_repair, _gate_sig
from ..roles import (
    LAGOM_VERIFIER_NOTE,
    role_prompt,
    work_shape_note,
)
from ..toolspec import VERDICT_TOOL
from ._shared import (
    _CRAFT_MAX_BLOCKS,
    _classified_findings,
    _craft_blocking,
    _runner_identity,
    _RunState,
)


class _VerdictMixin(_RunState):
    """판정 턴 — 결정론 베이스라인, 미시 형상 게이트, 문체 게이트, 그리고 LLM 판정자.

    `TrinityRun` 가 상속한다 — 혼자서는 아무것도 아니다."""

    def _baseline_red_fails(self) -> list[str]:
        """마지막 verify 이벤트의 베이스라인 red 실패 줄 — 예산 소진 Odin 보고에 원인을 실어
        준다 (fail-open: 로그 부재·파싱 실패는 빈 목록, 보고 자체는 계속)."""
        fails: list[str] = []
        try:
            path = os.path.join(self._hd.root, ".asgard", "quest", f"{self.qid}.jsonl")
            with open(path, encoding="utf-8") as f:
                for ln in f:
                    e = json.loads(ln)
                    bl = e.get("baseline") or {}
                    if e.get("event") == "verify" and bl.get("state") == "red":
                        fails = [str(x) for r in bl.get("results") or [] for x in (r.get("fails") or [])]
        except Exception:
            return []
        return fails

    def _baseline_turn(self) -> str | None:
        """게이트-우선 판정 턴 — LLM 토큰 0, 하네스가 프로젝트 체크로 판정 기록."""
        hd = self._hd
        p = ql(hd.root, "verify-baseline", session=self.sid)
        try:
            bj = json.loads(p.stdout or "{}")
        except Exception:
            bj = {}
        if p.returncode != 0 or not bj.get("verdict"):
            self.pending = ("VERIFIER", "Baseline verdict unavailable — falling back to LLM Verifier")
            return None
        _v = bj["verdict"]  # 판정층(⑤) — 의미색: PASS 녹·FAIL 적
        _mk, _cl = ("✔", theme.SUCCESS) if _v == "PASS" else ("✘", theme.DANGER)
        _src = str(bj.get("baseline") or "무변경 관측")  # baseline null = 무변경 트리 관측 판정
        hd.on_text(
            f"  {ui.paint(theme.ansi(_cl), _mk)} {ui.dim('베이스라인 ' + _src + ' → ')}{ui.paint(theme.ansi(_cl), _v)}\n"
        )
        if bj["verdict"] == "FAIL":
            self.saw_red = True
            failing = ", ".join(map(str, bj.get("failing") or [])) or "(see quest log baseline.results)"
            fails = "; ".join(str(f) for f in (bj.get("fails") or [])[:3])  # 정형 실패 줄 — 수리 턴이 이유를 본다
            why = f"Harness baseline check failed: {failing}" + (f" — {fails}" if fails else "")
            self.last_fail = {"sig": "baseline-red", "why": why}
            self.fail_history.append(f"baseline-red: {failing[:200]}")
        return None

    def _craft_blocked(self) -> bool:
        """미시 형상(craft) + 백엔드 정확성(thor gate) 래칫 — 수리 턴이 필요하면 True.

        모드 B는 craft-gate 훅이 SubagentStop에서 같은 두 판정기를 부른다. 네이티브엔 그
        이벤트가 없어 완료 후보 턴이 같은 자리를 맡는다 — 같은 규율, 다른 배선. 판정 대상은
        퀘스트에 귀속된 변경뿐이고, 물려받은 부채는 판정기가 자체 래칫으로 통과시킨다.

        상한 2회는 훅과 같은 이유다: 막기만 하는 게이트는 작업을 인질로 잡는다. 3번째는 경고와
        함께 통과시키되 판정 사실은 화면에 남긴다 (조용한 통과 금지)."""
        hd = self._hd
        paths = self._quest_paths()
        blocking = _craft_blocking(hd.root, paths) if paths else []
        if not blocking:
            return False
        detail = "; ".join(
            f"[{f.get('gate')}/{f.get('rule')}] {f.get('path')}:{f.get('line')} — {f.get('detail')}"
            for f in blocking[:6]
        )
        if self.craft_blocks >= _CRAFT_MAX_BLOCKS:
            hd.on_text(
                f"  {ui.paint(ui._WARN, '!')} "
                f"{ui.dim(f'craft: {len(blocking)}건 미수리 통과 (상한 {_CRAFT_MAX_BLOCKS}회) — {detail[:200]}')}\n"
            )
            return False
        self.craft_blocks += 1
        return self._fail_and_repair(
            "craft-shape",
            detail,
            "asgard craft --json / asgard thor gate --json",
            "harness",
            f"This change made {len(blocking)} thing(s) worse than they were at HEAD — fix them, "
            "or state with evidence why the shape is right. Re-check with `asgard craft` and `asgard thor gate`.",
        )

    def _style_blocked(self) -> bool:
        """문체 불변식 — 위반이면 수리 턴을 예약하고 True.

        문체는 프롬프트 권고가 아니라 완료 불변식이다. Verifier 자체에는 문체 프롬프트를
        주입하지 않되, 하네스가 변경 문서의 추가행을 결정론 검사한다. 두 축을 함께 건다:
        Lagom = 근거 없는 효용 주장, Bragi = 언어 불문 기계 문체 흔적.

        조언(advisory) 항목만 남은 문서는 막지 않는다 — 검사기가 판정할 수 없는 신호로
        수리 턴을 강제하면 지울 수 없는 것을 지우라는 지시가 되어 퀘스트만 태운다."""
        hd = self._hd
        if not (hd.lagom or hd.bragi):
            return False
        try:
            from ....lagom import blocking, changed_prose_violations, style_violations

            checks = [style_violations] if hd.lagom else []
            if hd.bragi:
                from ....bragi import violations as voice_violations

                checks.append(voice_violations)
            style_failures = blocking(changed_prose_violations(hd.root, self._quest_paths(), self.request, checks))
        except Exception:
            return False  # 검사기 장애는 기존 Verifier+게이트 경로를 막지 않는다
        if not style_failures:
            return False
        return self._fail_and_repair(
            "lagom-style",
            "; ".join(style_failures[:8]),
            "lagom-style-check --changed-prose",
            "verifier",
            "Lagom style invariant violated — rewrite the changed docs",
        )

    def _done_turn(self) -> str | None:
        """완료 후보 턴 — 문체·형상 불변식 → 게이트 → close → 최종 보고."""
        hd = self._hd
        # 두 불변식 모두 수리 턴을 예약하고 이번 턴을 끝낸다 (모드 B의 Stop·SubagentStop 게이트와
        # 같은 규율 — 네이티브엔 그 이벤트가 없어 완료 후보 턴이 그 자리를 맡는다).
        if self._style_blocked() or self._craft_blocked():
            return None
        blocked, reason = gate(hd.root, self.sid)
        if blocked:  # 전이/게이트 판정 불일치 — 사유별 수리 턴 강제 (무수리 재시도 금지)
            self.gate_blocks += 1
            sig = _gate_sig(reason)
            self.gate_sigs[sig] = self.gate_sigs.get(sig, 0) + 1
            hd.on_text(f"  {ui.paint(ui._WARN, '!')} {ui.dim(f'gate({sig}): {reason[:200]}')}\n")
            if sig == "baseline-red":
                self.saw_red = True
            if self.gate_sigs[sig] >= 2:  # 동일 사유 재차단 = 수리 불가 — fail-open 위장 대신 정직 보고
                hd._escalate(self.sid)
                hd._record_outcome(self.tc, "gate-escalate", self.saw_red)
                return (
                    f"⚠ 오딘이 정해 주셔야 해요 — 게이트가 같은 사유({sig})로 {self.gate_sigs[sig]}번 막았고, 수리도 안 됐어요. "
                    f"퀘스트 로그: .asgard/quest/{self.qid}.jsonl"
                )
            self.pending = _gate_repair(sig)
            if sig == "baseline-red":  # 실패 체크 상세를 수리 턴에 주입 (retry 컨텍스트 경로 재사용)
                self.last_fail = {"sig": sig, "why": reason[:500]}
            return None
        closed = ql(hd.root, "close", session=self.sid)
        if closed.returncode != 0:
            hd._record_outcome(self.tc, "close-rejected", self.saw_red)
            detail = (closed.stderr or closed.stdout or "close rejected").strip()[:300]
            return (
                "⚠ 완료 게이트가 close를 거부했어요 — 승인 상태를 기록하지 못했어요. "
                f"{detail} 퀘스트 로그: .asgard/quest/{self.qid}.jsonl"
            )
        hd._record_outcome(self.tc, "pass", self.saw_red)
        try:  # 자가발전 (CUS-253) — 방금 닫힌 퀘스트가 hard-won(FAIL→PASS)이면 초안으로 증류한다.
            # 채굴은 늘 하고, 설치는 자율 등급이 정한다 (evolution.autonomy — 기본 safe 는 퀘스트
            # 로그 채굴분만 설치한다). 등급이 무엇이든 되돌아오는 자리에 머문다: 설치 안 된 것은
            # pending 초안이고, 설치된 것은 `evolve archive` 한 줄로 물러난다.
            # 여기가 호스트 모드의 `memory tick` 과 같은 등급을 써야 하는 이유는 하나다 — 어느
            # 문으로 들어왔느냐에 따라 배우는 속도가 달라지면 안 된다.
            from ....evolution import autoapprove, autoscan, unmined_signals

            mined = autoscan(hd.root)
            installed = autoapprove(hd.root, mined)
            if installed:
                names = ", ".join(str(row.get("name") or row.get("id") or "?") for row in installed[:3])
                hd.on_text(
                    f"  {ui.dim('│ ⠶ 학습 스킬 ' + str(len(installed)) + '건 설치 — ' + names)}\n"
                    f"  {ui.dim('│   다음 배차부터 쓰인다 · 물리기: asgard evolve archive <이름>')}\n"
                )
            elif mined:
                names = ", ".join(str(row.get("name") or row.get("id") or "?") for row in mined[:3])
                hd.on_text(
                    f"  {ui.dim('│ ⠶ hard-won 교훈 ' + str(len(mined)) + '건 증류 — ' + names)}\n"
                    f"  {ui.dim('│   검토·승인: asgard evolve list (미승인 = 미적용)')}\n"
                )
            elif unmined_signals(hd.root, self.qid):
                hd.on_text(f"  {ui.dim('│ ⠶ hard-won 교훈 감지 — asgard evolve scan으로 스킬 후보 증류 가능')}\n")
        except Exception:
            pass
        self._tend_memory()
        return hd._final_report(self.qid, self.sid, self.gate_blocks) + self._orchestration_note()

    def _verifier_turn(self) -> str | None:
        """판정 턴 — read-only 세션 + verdict 툴 강제, 하니스 관측 증거만 기록."""
        hd = self._hd
        # 퀘스트 로그 관측 diff 컨텍스트 — 검증자가 "diff 없음"으로 헛FAIL 하지 않게 물리 관측을
        # 손에 쥐여준다 (판정은 여전히 직접 명령 실행으로).
        st = {}
        try:
            st = json.loads(ql(hd.root, "state", session=self.sid).stdout or "{}")
        except Exception:
            pass
        changed = ", ".join((st.get("changed_files") or [])[:20]) or "(none)"

        charter_v = hd._charter_note(hd.root, "verifier")  # 반례 렌즈 (판단③) — 게이트 대체 아님
        manual_v = hd._manual_note(hd.root, "verifier")  # 명시 규칙 위반 = 반례, 역시 criteria 대체 아님
        verifier_paths = tuple(str(path) for path in (st.get("changed_files") or []) if str(path))
        # 판정 시점이 변경 형상을 아는 유일한 자리다 — 요청이 아키텍처를 말하지 않아도 관측된
        # 형상이 구조적이면 아키텍처 검증 팩을 배정한다 (verifier.md의 "assigned" 조건 충족).
        shape_note_v = work_shape_note(
            hd.root, self.request, self.cls, agent="verifier", loader="cli", changed=verifier_paths or None
        )
        # 공개 표면 대조 — verifier.md는 "바뀐 공개 심볼의 호출부를 전수 대조"하라고 요구하지만
        # 그 목록 만들기가 모델의 손 grep에 맡겨져 있었다 (심볼 하나 빠뜨리면 그대로 통과).
        # 퀘스트 기준 커밋 대비 시그니처 변화와 호출부 후보를 기계가 먼저 낸다 — grep 면제가
        # 아니라 하한이다. fail-open: 기준이 없거나 계산이 실패하면 빈 문자열 (종전 동작).
        surface_note = ""
        try:
            from ....surface import note as _surface_note

            base = str(st.get("base_ref") or "").strip()
            if base and base != "NONE":
                surface_note = _surface_note(hd.root, base)
        except Exception:
            surface_note = ""

        def mk_verifier(m=self.model, rl="verifier", ch=charter_v, rp=None, paths=verifier_paths, mn=manual_v):
            session = hd._session(
                role_prompt("asgard-verifier.md") + ch + mn + (LAGOM_VERIFIER_NOTE if hd.lagom else ""),
                extra_tools=[VERDICT_TOOL],
                handlers={"verdict": lambda i: "Verdict received"},
                role=rl,
                model=m,
                readonly=True,  # 읽기전용을 도구로 강제 — 프롬프트 순응에 안 기댄다
                rp_override=rp,
            )
            session.readonly_paths = paths
            return session

        fb = (lambda mv=mk_verifier: mv(m=None, rl="verifier", rp=hd.rp)) if self.rrp is not hd.rp else None
        baseline_note = (
            "\nWhen the harness records a PASS, it runs the project baseline check (test suite) directly and"
            " records it as evidence — do not rerun the full suite. Only inspect the changed files and confirm"
            " scope (matching tests/smoke/grep for those files). Suite red is caught by the harness.\n"
            if st.get("checks_available")
            else "\n"
        )
        r = hd._run_turn(
            mk_verifier,
            f"Verify. Request: {self.request}\ncriteria: {self.cls['criteria']}\n"
            f"required level: {self.level}\n"
            f"Harness-observed changed files: {changed} (diff_lines={st.get('diff_lines', '?')}) — "
            f"confirm directly with `git diff` / file inspection / execution.\n"
            "Scope the verdict to the harness-observed files above — other diffs in the working tree may be"
            " uncommitted work owned by another session: treat them as reference notes, not a FAIL reason. Do"
            " not invent new criteria — observations outside the criteria above are reference notes only in"
            " the report.\n"
            + baseline_note
            + "This session has a read-only Bash guard — allowed: observation (including `sed`/`awk` without"
            " in-place writes), git reads, verification runners (pytest/ruff/ty, including via `uv run`),"
            " `python -m pytest|compileall|py_compile`, `python -c '<write-free smoke test>'`, and — for a"
            " JS/TS repository — `node --check <file>`, `node [--test] <scripts under tests/>`,"
            " `npm|pnpm|yarn test|lint|check` (`node -e` stays blocked, so put the smoke in the repo's tests/"
            " tree). Allowed commands may be chained with `|`, `&&`, `||`, `;` — each segment is judged on its"
            " own — and `2>/dev/null`, `2>&1`, `< /dev/null` are fine. File writes, redirection to a file,"
            " heredocs, and $VAR are blocked — don't burn the turn retrying variants of a blocked command;"
            " switch to an allowed lane immediately.\n"
            "This workspace is an isolated clone without a .venv — prefer `python -m pytest -x -q` for tests;"
            " `uv run` can fail for environment reasons, so if it fails, switch to `python -m` instead of"
            " retrying (passing the same target with a different runner counts as resolving the earlier"
            " failure).\n"
            "Worker commentary is not input — judge only by diff and command execution. The verdict must be"
            " submitted via the verdict tool.\n"
            "If the FAIL is a flaw in the approach itself, submit structural=true (triggers a replan).\n"
            + self._intent_block()
            + shape_note_v
            + surface_note
            + self._trajectory_note()
            + "\nClassify every defect you raise in the verdict's `findings`: `auto-fix` for mechanical,"
            " low-risk defects a retry turn resolves on its own judgment; `ask-user` for a finding that"
            " contradicts what Odin explicitly asked for above or that changes user-visible product"
            " behaviour — that decision is Odin's, not a retry's, and it stops the loop; `no-op` for an"
            " observation that needs nothing. A finding you cannot classify is `ask-user` (fail closed)."
            " Do not reach for `ask-user` to avoid a judgment the criteria already settle.",
            fb,
        )
        # 마지막 verdict 호출이 최종 판정 (다중 호출 시 정정 인정)
        v = next((c["input"] for c in reversed(r.tool_calls) if c["name"] == "verdict"), None)
        submitted = (v or {}).get("verdict")  # Verifier가 실제 제출한 판정 — 하네스 무효화 표시용
        observed = [c for c in r.commands if isinstance(c, dict)]  # 하니스 관측 — 위조 불가
        # 하네스 관측 무변경 퀘스트 — '변경 없음' 주장에는 트리 관측(git status/diff)이 곧 검증.
        # state 로드 실패(st={})는 미상이므로 종전 엄격 경로 유지 (fail-closed).
        no_change = st.get("diff_hash") == _EMPTY_DIFF
        final_exit_by_command: dict[str, object] = {}
        for command in observed:
            cmd = str(command.get("cmd") or "").strip()
            # 가드 차단(blocked) 호출은 실행된 적이 없다 — 미해소 실패 집합에서 제외 (커널 경로 패리티)
            if cmd and not _trivial_evidence(cmd) and not command.get("blocked"):
                # 200자 초과 명령은 절단본 대신 해시가 신원 (절단 충돌 방지 우선). 그 외는 러너
                # 래퍼를 벗긴 신원 — 환경 사정으로 러너를 갈아탄 동일 대상 성공은 실패 해소다.
                identity = str(command.get("command_hash") or _runner_identity(cmd))
                final_exit_by_command[identity] = command.get("exit_code")

        def _absence_probe(identity: str, exit_code) -> bool:
            # grep/rg 매치 0건은 exit 1 — '패턴 부재' 확인의 성공이지 검증 실패가 아니다.
            # 이걸 미해소 실패로 세면 정당한 PASS가 뒤집혀 Worker 재시도+재검증 2턴이 공짜로
            # 낭비된다 (26-07-23 감사). 부재 확인 외의 exit 1 (파일 없음 grep 등)도 exit 1이라
            # 구분 불가 — 관측 명령이므로 실패로 물어야 할 근거도 없다 (fail-open).
            head = identity.split(" ", 1)[0] if identity else ""
            if head in {"grep", "egrep", "fgrep", "rg"} or identity.startswith("git grep"):
                return exit_code == 1
            return False

        unresolved = [
            cmd
            for cmd, exit_code in final_exit_by_command.items()
            if exit_code != 0 and not _absence_probe(cmd, exit_code)
        ]
        if not v:
            v = {
                "verdict": "FAIL",
                "criteria": self.cls["criteria"],
                "failure_sig": "no-verdict-submitted",
                "why": "verdict tool was not submitted",
            }
        elif v.get("verdict") not in {"PASS", "FAIL", "ESCALATE"}:
            v = {
                "verdict": "FAIL",
                "criteria": self.cls["criteria"],
                "failure_sig": "invalid-verdict-submitted",
                "why": "verdict value must be one of PASS|FAIL|ESCALATE",
            }
        elif (
            v.get("verdict") == "PASS"
            and not st.get("checks_available")
            and not any(c.get("exit_code") == 0 and not _trivial_evidence(c.get("cmd", "")) for c in observed)
            and not (
                no_change and any(c.get("exit_code") == 0 and _inspection_evidence(c.get("cmd", "")) for c in observed)
            )
        ):
            # 증거 없는 PASS 무효 — verifier가 명령을 실제 실행하지 않았거나 true/echo 류
            # 무조건-성공 명령뿐이다 (Goodhart). 단 무변경 퀘스트의 관측 명령은 증거로 인정 —
            # 아니면 no-op이 영구 FAIL 교착 (26-07-21 "안녕" 실측: PASS 5연속 무효화 → 예산 소진).
            # checks_available 이면 무효화하지 않는다 — PASS 기록 시 하네스가 베이스라인을 직접
            # 실행해 결정론 증거를 붙인다 (pass_evidence의 baseline-green 경로): Verifier에게
            # 같은 스위트 재실행을 강요하면 사이클당 동일 테스트 2~3중 실행이 된다 (26-07-23 감사).
            # red 면 완료 퍼널이 baseline-red로 거부하므로 게이트 무결성은 유지된다.
            v = {
                "verdict": "FAIL",
                "criteria": v.get("criteria") or self.cls["criteria"],
                "failure_sig": "no-verification-evidence",
                "why": "PASS was claimed with no harness-observed successful command — "
                "the verification commands must actually be run",
            }
        elif v.get("verdict") == "PASS" and unresolved:
            v = {
                "verdict": "FAIL",
                "criteria": v.get("criteria") or self.cls["criteria"],
                "failure_sig": "unresolved-verification-failure",
                "why": "Unresolved verification failure before PASS: " + "; ".join(unresolved[:3]),
            }
        if submitted == "PASS" and v.get("verdict") == "FAIL":
            # 하네스가 Verifier 판정을 뒤집었다 — 표시 없이는 사용자가 "PASS 스트림 직후
            # FAIL(경미) 재시도"라는 모순된 화면을 본다 (판정층 정직성).
            hd.on_text(f"  {ui.dim('│ ⚠ 하네스가 Verifier PASS 무효화 — ' + str(v.get('why') or '')[:140])}\n")
        if v.get("failure_sig"):
            # 자유 기술 sig의 표기 흔들림을 슬러그로 정규화 — 3-strike 동종 판정 키 안정화
            from ....failures import normalize_sig

            v["failure_sig"] = normalize_sig(str(v["failure_sig"]))
        findings = _classified_findings(v)
        ask_user = [f for f in findings if f["action"] == "ask-user"]
        # 증거는 하니스 관측 명령만 기록 — 모델 자가보고 commands는 버린다
        ev = {
            "role": "verifier",
            "event": "verify",
            "criteria": v.get("criteria") or self.cls["criteria"],
            "commands": observed[-20:],
            "model": self.used_model,
        }
        if findings:
            ev["findings"] = findings[:20]
        if v.get("failure_sig"):
            ev["failure_sig"] = v["failure_sig"]
        self.structural = bool(v.get("structural")) and v.get("verdict") == "FAIL"
        if v.get("verdict") == "FAIL":
            self.last_fail = {
                "sig": v.get("failure_sig"),
                "why": v.get("why", ""),
                "criteria": v.get("criteria") or [],
                "commands": observed[-5:],
            }
            self.fail_history.append(
                f"{v.get('failure_sig') or 'unknown'}: {(v.get('why') or '')[:200]}"
                + (" [structural]" if self.structural else "")
            )
        else:
            self.last_fail = None
        appended = ql(
            hd.root,
            "append",
            "--verdict",
            str(v["verdict"]),
            "--level",
            self.level,
            session=self.sid,
            stdin=json.dumps(ev),
        )
        if appended.returncode != 0:
            hd._record_outcome(self.tc, "verify-append-rejected", self.saw_red)
            detail = (appended.stderr or appended.stdout or "verifier append rejected").strip()[:300]
            return f"⚠ Verifier 판정을 기록하지 못했어요 — {detail} 퀘스트는 ACTIVE로 둘게요."
        if ask_user:
            lines = "\n".join(f"  · [{f['id']}] {f.get('file') or '—'} — {f['description'][:220]}" for f in ask_user)
            if v["verdict"] == "FAIL":
                # 판단이 사람 몫인 결함을 재시도에 맡기면 Worker가 Odin의 명시 지시를 추측으로
                # 뒤집는다 — 기계 수리와 판단을 가르는 것이 이 분류의 전부다. 판정은 이미 기록됐다.
                hd._escalate(self.sid)
                hd._record_outcome(self.tc, "findings-escalate", self.saw_red)
                return (
                    f"⚠ 오딘이 정해 주셔야 해요 — 판정이 오딘의 지시와 부딪히는 결함 {len(ask_user)}건에 걸렸어요 "
                    f"(재시도로 대신 정할 수 없어요).\n{lines}\n"
                    f"퀘스트 로그: .asgard/quest/{self.qid}.jsonl"
                )
            # PASS는 criteria↔증거 매핑이 계약이므로 뒤집지 않는다 — 다만 판단이 사람 몫인 관측을
            # 조용히 닫으면 "자동 해소"가 된다: 판정은 그대로 두고 화면에 올려 Odin이 보게 한다.
            hd.on_text(
                f"  {ui.paint(ui._WARN, '!')} {ui.dim('Odin 판단 대기 관측 ' + str(len(ask_user)) + '건')}\n{lines}\n"
            )
        return None
