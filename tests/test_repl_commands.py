from __future__ import annotations

import os
import re
from types import SimpleNamespace

from asgard import ui
from asgard.agent import repl


def test_command_catalog_drives_help_and_completion() -> None:
    help_commands = {command for command, _ in repl._help_items()}

    assert help_commands == {command for command in repl._COMMAND_HELP if " " not in command}
    assert repl._completer("/lang", 0) == "/lang "
    assert repl._completion_matches("/") == [c for c in repl._COMMAND_HELP if " " not in c]
    assert repl._completer("/lang ", 0) == "/lang en "
    assert repl._completer("/lagom default", 0) == "/lagom default "


def test_unknown_command_suggests_nearest_command(monkeypatch, capsys) -> None:
    monkeypatch.setattr(ui, "_COLOR", False)

    repl.slash("/modle", ".", None)

    assert "/model" in capsys.readouterr().out


def test_sessions_command_observes_and_stops_child_tree(monkeypatch, capsys) -> None:
    monkeypatch.setattr(ui, "_COLOR", False)

    class Heimdall:
        stopped = False

        def session_snapshot(self):
            return [{"id": "worker-1", "state": "running", "status": "$ pytest", "elapsed_s": 1.2}]

        def cancel(self):
            self.stopped = True

    hd = Heimdall()
    repl._PT_CTX["heimdall"] = hd
    repl.slash("/sessions", ".", None)
    repl.slash("/sessions stop", ".", None)

    out = capsys.readouterr().out
    assert "worker-1" in out and "$ pytest" in out
    assert hd.stopped


def test_trinity_dual_mode_is_session_scoped(monkeypatch, capsys) -> None:
    monkeypatch.setattr(ui, "_COLOR", False)

    class Heimdall:
        dual_mode = False

        @staticmethod
        def dual_thinker_labels():
            return "anthropic:architect", "openai:architect"

    hd = Heimdall()
    monkeypatch.setitem(repl._PT_CTX, "heimdall", hd)

    repl.slash("/trinity dual on", ".", None)
    assert hd.dual_mode
    repl.slash("/trinity dual off", ".", None)
    assert not hd.dual_mode
    assert "dual thinker" in capsys.readouterr().out


def test_trinity_dual_mode_rejects_same_model(monkeypatch, capsys) -> None:
    monkeypatch.setattr(ui, "_COLOR", False)

    class Heimdall:
        dual_mode = False

        @staticmethod
        def dual_thinker_labels():
            return "anthropic:same", "anthropic:same"

    hd = Heimdall()
    monkeypatch.setitem(repl._PT_CTX, "heimdall", hd)

    repl.slash("/trinity dual on", ".", None)

    assert not hd.dual_mode
    assert "thinker_alt" in capsys.readouterr().out


def test_trinity_dual_default_is_loaded_by_new_start_session(monkeypatch, tmp_path) -> None:
    class CurrentHeimdall:
        dual_mode = False

        @staticmethod
        def dual_thinker_labels():
            return "anthropic:architect", "openai:architect"

    current = CurrentHeimdall()
    monkeypatch.setitem(repl._PT_CTX, "heimdall", current)
    repl.slash("/trinity dual default on", str(tmp_path), None)

    from asgard.agent import heimdall as heimdall_module

    class FreshHeimdall:
        def __init__(self, *args, **kwargs):
            self.dual_mode = False

    monkeypatch.setattr(heimdall_module, "Heimdall", FreshHeimdall)
    fresh = repl._new_heimdall(str(tmp_path), object(), lambda _: None)

    assert current.dual_mode is True
    assert fresh.dual_mode is True


def test_trinity_model_terminal_command_sets_lists_and_resets(monkeypatch, capsys, tmp_path) -> None:
    from asgard.providers import project_section

    monkeypatch.setattr(ui, "_COLOR", False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    repl.slash("/trinity model cursor worker terminal-model", str(tmp_path), None)
    assert project_section(str(tmp_path), "agent_models.cursor.worker") == {"model": "terminal-model"}

    repl.slash("/trinity models", str(tmp_path), None)
    out = capsys.readouterr().out
    assert "cursor" in out and "worker" in out and "terminal-model" in out

    repl.slash("/trinity model reset cursor worker", str(tmp_path), None)
    assert project_section(str(tmp_path), "agent_models.cursor.worker") == {}
    assert "gpt-5.6-terra-medium" in capsys.readouterr().out


def test_trinity_model_terminal_guides_host_role_and_model(monkeypatch, capsys, tmp_path) -> None:
    from asgard.providers import project_section

    monkeypatch.setattr(ui, "_COLOR", False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr("asgard.agent.onboard.can_prompt", lambda: True)
    answers = iter(["3", "2", "m", "guided-model"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    repl.slash("/trinity model", str(tmp_path), None)

    assert project_section(str(tmp_path), "agent_models.cursor.worker") == {"model": "guided-model"}
    out = capsys.readouterr().out
    assert "claude-code" in out and "cursor" in out and "codex" in out
    assert "worker" in out and "gpt-5.6-terra-medium" in out
    assert "guided-model" in out


def test_trinity_model_terminal_native_change_requests_session_reconfigure(monkeypatch, tmp_path) -> None:
    from asgard.providers import project_section

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    current = object()

    try:
        repl.slash("/trinity model native worker local-model ollama", str(tmp_path), current)
    except repl._Reconfigure as changed:
        assert changed.rp is current
        assert "native.worker" in (changed.msg or "")
    else:
        raise AssertionError("native model change must rebuild the Heimdall session")

    assert project_section(str(tmp_path), "trinity.worker") == {
        "model": "local-model",
        "provider": "ollama",
    }


def test_skills_command_lists_only_explicit_workflows(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(ui, "_COLOR", False)

    repl.slash("/skills", str(tmp_path), None)

    out = capsys.readouterr().out
    assert "User skills" in out
    assert "╭─" in out and "╰" in out
    assert "/council" in out
    assert "/blueprint" in out
    assert "/domain-modeling" not in out


def test_exact_skill_slash_reaches_heimdall_as_explicit_prompt(monkeypatch, tmp_path) -> None:
    seen = []

    class Heimdall:
        total_tokens = last_context_tokens = cache_read_tokens = cache_prompt_tokens = 0
        cancel_event = None

        def handle(self, prompt):
            seen.append(prompt)
            return ""

    requests = iter(["/council checkout flow"])

    def ask():
        try:
            return next(requests)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr(repl, "_PT", True)
    monkeypatch.setattr(repl, "banner", lambda _rp: None)
    monkeypatch.setattr(repl, "prompt", ask)
    monkeypatch.setattr(repl, "_new_heimdall", lambda *_args, **_kwargs: Heimdall())
    rp = SimpleNamespace(missing=False, model="test-model")

    assert repl.run(str(tmp_path), rp) == 0
    assert len(seen) == 1
    assert '<user_invoked_skill name="council">' in seen[0]
    assert "Arguments: checkout flow" in seen[0]


def test_banner_uses_compact_mark_on_standard_terminal(monkeypatch, capsys) -> None:
    monkeypatch.setattr(os, "get_terminal_size", lambda _fd=0: os.terminal_size((120, 30)))
    monkeypatch.setattr(ui, "_COLOR", False)

    repl.banner(None)

    out = capsys.readouterr().out
    assert repl._LOGO_SLIM in out
    assert repl._LOGO not in out


def test_render_sink_mode_emits_complete_softwrapped_lines(monkeypatch) -> None:
    monkeypatch.setattr(ui, "_COLOR", False)
    monkeypatch.setattr(ui, "stream_width", lambda: 40)
    got: list[str] = []

    render = repl._Render()
    render.attach(got.append)
    render.write("word " * 20)  # 100자 — 폭 예산(36) 초과분은 공백 경계 소프트랩
    render.write("tail\n  meta line\n")
    render.finish()

    lines = "".join(got).splitlines()
    assert lines and all(len(line) <= 40 for line in lines)
    assert lines[0].startswith("  word")  # 본문 2칸 들여쓰기
    assert "  meta line" in lines  # 메타 라인 무가공 통과
    render.attach(None)
    assert render._sink is None


def test_submitted_echo_stands_in_for_erased_input_frame(monkeypatch) -> None:
    # pt 는 accept 시 입력 프레임을 지운다(erase_when_done) — 스크롤백엔 이 에코가 사용자
    # 메시지를 대표한다. 일반 요청=캐럿+본문, 커맨드(/·!)=흐림, 멀티라인=본문 열 정렬.
    monkeypatch.setattr(ui, "_COLOR", False)

    assert repl._echo_submitted("배포 상태 봐줘") == "  › 배포 상태 봐줘"
    assert repl._echo_submitted("첫 줄\n둘째 줄") == "  › 첫 줄\n    둘째 줄"
    assert repl._echo_submitted("/provider") == "  › /provider"
    assert repl._echo_submitted("!git status") == "  › !git status"


def test_pt_session_erases_input_frame_on_accept(monkeypatch, tmp_path) -> None:
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    monkeypatch.setattr(repl, "_history_path", lambda: str(tmp_path / "history"))

    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        session = repl._pt_session()
        assert session.app.erase_when_done is True


def test_pt_prompt_accepts_prefilled_draft_immediately(monkeypatch, tmp_path) -> None:
    # 턴 중 초안 + 트레일링 ⏎ → 다음 프롬프트가 프리필을 즉시 제출 (자동 제출 계약)
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    monkeypatch.setattr(repl, "_history_path", lambda: str(tmp_path / "history"))

    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        session = repl._pt_session()
        assert session.prompt("› ", default="이어서 진행해", accept_default=True) == "이어서 진행해"


def test_dock_inserts_output_above_persistent_frame(monkeypatch, capsys) -> None:
    monkeypatch.setattr(ui, "_COLOR", False)
    monkeypatch.setattr(ui, "term_cols", lambda: 80)
    repl._PT_CTX.update(root=".", rp=SimpleNamespace(missing=True), heimdall=None)

    dock = repl._Dock()
    dock.mount()
    dock.status("thinking")
    dock.write("  streamed line")
    dock.unmount()

    out = capsys.readouterr().out
    assert "╭" in out and "│" in out and "╰" in out  # 입력 프레임 상주
    assert re.match(r"\x1b\[\d+;1H", out)  # mount 즉시 마지막 행 절대 점프 — 하단 고정 (본문 위치 점프 방지)
    assert out.count(f"\x1b[{repl._Dock.HEIGHT - 1}A") >= 2  # draw 마다 스페이서 행 파킹 복귀
    assert "\x1b[0J" in out  # 출력 삽입 전 독 소거
    assert "streamed line" in out
    assert "thinking" in out
    assert not dock.mounted


def test_dock_status_and_stream_lines_stay_single_line(monkeypatch, capsys) -> None:
    # 멀티라인 명령 라벨(히어독·python -c)이 독의 고정 커서 산술을 깨고 박스 보더를 오염시키던
    # 결함 봉합 (26-07-21) — hermes compactPreview 식: 개행 포함 공백 연쇄를 접은 뒤 절단
    monkeypatch.setattr(ui, "_COLOR", False)
    monkeypatch.setattr(ui, "term_cols", lambda: 80)
    monkeypatch.setattr(ui, "stream_width", lambda: 80)
    repl._PT_CTX.update(root=".", rp=SimpleNamespace(missing=True), heimdall=None)

    assert ui.oneline("cat > x <<'PY'\nimport re\nPY") == "cat > x <<'PY' import re PY"
    clipped = ui.oneline("a" * 100, 20)
    assert len(clipped) == 20 and clipped.endswith("…")

    dock = repl._Dock()
    dock.mount()
    capsys.readouterr()
    dock.status("$ cat > smoke.py <<'PY'\nimport re\nfrom mod import y\nPY")
    out = capsys.readouterr().out
    dock.unmount()
    assert "\n" not in out  # 상태 행 페인트는 단일 물리 행 계약 — 개행이 나가면 보더가 깨진다

    from asgard.agent.session import AgentSession

    emitted: list[str] = []
    sess = SimpleNamespace(on_text=emitted.append)
    AgentSession._tool_line(sess, "$", "python3 - <<'EOF'\nimport ast\nEOF", 2.0)
    assert emitted and "\n" not in emitted[0].rstrip("\n")  # 완료 라인도 행당 1줄 — 히어독 본문 스필 금지


def test_dock_mount_places_frame_on_bottom_rows_without_scroll(monkeypatch, capsys) -> None:
    # CPR 응답 경로 — 흐름(4행)이 독 영역(19~24행) 위: 스크롤 0, 절대 배치 + 입력행 캐럿 파킹
    monkeypatch.setattr(ui, "_COLOR", False)
    monkeypatch.setattr(ui, "term_cols", lambda: 80)
    monkeypatch.setattr(repl, "_term_rows", lambda: 24)
    monkeypatch.setattr(repl, "_cursor_row", lambda: 4)
    repl._PT_CTX.update(root=".", rp=SimpleNamespace(missing=True), heimdall=None)

    dock = repl._Dock()
    dock.mount()
    out = capsys.readouterr().out
    dock.unmount()

    assert "\n" not in out  # 무스크롤 계약 — 개행 없이 행별 절대 이동만
    for row in range(19, 25):  # 마지막 HEIGHT(6)행 각각에 절대 배치
        assert f"\x1b[{row};1H" in out
    assert out.endswith("\x1b[19;1H\x1b[3B\x1b[7G")  # 스페이서 복귀 후 입력행 캐럿 뒤 파킹


def test_dock_mount_scrolls_only_overlap_when_flow_is_deep(monkeypatch, capsys) -> None:
    # CPR 응답 경로 — 흐름(22행)이 독 영역 침범: 부족분(22-19=3)만 최하단 개행으로 밀어낸다
    monkeypatch.setattr(ui, "_COLOR", False)
    monkeypatch.setattr(ui, "term_cols", lambda: 80)
    monkeypatch.setattr(repl, "_term_rows", lambda: 24)
    monkeypatch.setattr(repl, "_cursor_row", lambda: 22)
    repl._PT_CTX.update(root=".", rp=SimpleNamespace(missing=True), heimdall=None)

    dock = repl._Dock()
    dock.mount()
    out = capsys.readouterr().out
    dock.unmount()

    assert out.startswith("\x1b[24;1H" + "\n" * 3)  # 최하단에서 3회 자연 스크롤 (스크롤백 보존)
    assert out.count("\n") == 3  # 그 외 개행 없음 — 이후는 절대 배치
    assert out.endswith("\x1b[19;1H\x1b[3B\x1b[7G")


def test_dock_live_typing_renders_draft_and_prefills_next_prompt(monkeypatch, capsys) -> None:
    # 턴 중 타이핑 → 독 입력행에 골드 캐럿+본문 표시, 캐럿 열은 CJK 전각 반영, 회수 시 초안+제출 의사
    monkeypatch.setattr(ui, "_COLOR", False)
    monkeypatch.setattr(ui, "term_cols", lambda: 80)
    monkeypatch.setattr(repl, "_term_rows", lambda: 24)
    monkeypatch.setattr(repl, "_cursor_row", lambda: 4)
    repl._PT_CTX.update(root=".", rp=SimpleNamespace(missing=True), heimdall=None)

    dock = repl._Dock()
    dock.mount()
    capsys.readouterr()
    dock._apply_keys("다음 요청")
    out = capsys.readouterr().out
    dock.unmount()

    assert "\r\x1b[2K" in out and "› 다음 요청" in out  # 입력행 제자리 갱신
    assert out.endswith(f"\x1b[{7 + repl._disp_w('다음 요청')}G")  # 캐럿 = 본문 끝
    assert dock.take_pending() == ("다음 요청", False)
    assert dock.take_pending() == ("", False)  # 회수는 1회성

    dock._apply_keys("이어서 진행해\n")
    assert dock.take_pending() == ("이어서 진행해", True)  # 트레일링 ⏎ = 자동 제출 의사


def test_dock_apply_keys_edits_draft_backspace_and_clear() -> None:
    dock = repl._Dock()  # 미마운트 — 화면 무접촉 편집 로직만
    dock._apply_keys("abcd")
    dock._apply_keys("\x7f\x7f")
    assert dock._pending == "ab"
    dock._apply_keys("\x15x")
    assert dock._pending == "x"


def test_decode_keys_scrubs_escapes_and_holds_partial_sequences() -> None:
    # 화살표·CPR 응답 등 완성 시퀀스는 폐기 — 다음 프롬프트 오염 경로 차단
    assert repl._decode_keys(b"ab\x1b[A\x1b[24;1Rcd") == ("abcd", b"")
    # 청크 경계의 미완성 시퀀스는 carry 로 보류 → 다음 청크와 합류해 통째로 폐기
    text, carry = repl._decode_keys(b"ok\x1b[24;")
    assert (text, carry) == ("ok", b"\x1b[24;")
    assert repl._decode_keys(carry + b"1R!") == ("!", b"")
    # 미완성 UTF-8 꼬리 보류 → 합류 시 복원 (CJK 멀티바이트)
    raw = "한글".encode()
    text, carry = repl._decode_keys(raw[:4])
    assert text == "한" and carry == raw[3:4]
    assert repl._decode_keys(carry + raw[4:]) == ("글", b"")


def test_enter_submits_but_trailing_backslash_continues() -> None:
    calls: list[str] = []
    buf = SimpleNamespace(
        document=SimpleNamespace(current_line_before_cursor="do this \\"),
        delete_before_cursor=lambda n: calls.append(f"del{n}"),
        insert_text=lambda s: calls.append(f"ins{s!r}"),
        validate_and_handle=lambda: calls.append("accept"),
    )
    repl._kb_enter(SimpleNamespace(current_buffer=buf))
    assert calls == ["del1", "ins'\\n'"]  # 백슬래시 제거 후 줄 내림 — 제출 아님

    calls.clear()
    buf.document = SimpleNamespace(current_line_before_cursor="do this")
    repl._kb_enter(SimpleNamespace(current_buffer=buf))
    assert calls == ["accept"]

    calls.clear()
    repl._kb_newline(SimpleNamespace(current_buffer=buf))  # Shift+Enter/Ctrl+J
    assert calls == ["ins'\\n'"]


def test_multiline_continuation_prefix_matches_prompt_width() -> None:
    frags = repl._pt_continuation(6, 1, False)
    visible = "".join(text for _, text in frags)
    assert len(visible) == 6  # 첫 행 '  │ › ' 와 동일 폭 — 본문 열 정렬
    assert "│" in visible


def test_fallback_input_supports_backslash_continuation(monkeypatch) -> None:
    lines = iter(["첫 줄 \\", "둘째 줄\\", "셋째"])
    monkeypatch.setattr("builtins.input", lambda _p: next(lines))

    assert repl._input_continued("› ", "… ") == "첫 줄 \n둘째 줄\n셋째"


def test_completion_menu_reservation_is_dynamic(monkeypatch, tmp_path) -> None:
    # 하단 고정 계약 — 평소 0(입력행·toolbar 밀착), '/' 커맨드 입력 중에만 8행 확보
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    monkeypatch.setattr(repl, "_history_path", lambda: str(tmp_path / "history"))

    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        session = repl._pt_session()
        assert session.reserve_space_for_menu == 0
        session.default_buffer = SimpleNamespace(text="/lag")  # text 대입은 이벤트 루프 요구 — 스텁 치환
        assert session.reserve_space_for_menu == 8
        session.default_buffer = SimpleNamespace(text="일반 요청")
        assert session.reserve_space_for_menu == 0
        assert session.multiline is True  # 줄 내림 허용 (Enter 제출은 _kb_enter 계약)

        # 바닥 정렬 필러 — CPR(rows_above_layout) 미확보 상태에선 0 (원점 폴백, 예외 없이)
        assert session._asgard_bottom_pad().preferred == 0

    from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
    from prompt_toolkit.keys import Keys

    # Shift+Enter 시퀀스(CSI-u·modifyOtherKeys)가 줄내림(c-j)으로 별칭됐는지
    assert ANSI_SEQUENCES["\x1b[13;2u"] == Keys.ControlJ
    assert ANSI_SEQUENCES["\x1b[27;2;13~"] == Keys.ControlJ
