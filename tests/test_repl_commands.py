from __future__ import annotations

import os
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
    assert out.count(f"\x1b[{repl._Dock.HEIGHT - 1}A") >= 2  # draw 마다 스페이서 행 파킹 복귀
    assert "\x1b[0J" in out  # 출력 삽입 전 독 소거
    assert "streamed line" in out
    assert "thinking" in out
    assert not dock.mounted


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
