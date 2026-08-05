"""업데이트가 **말없이 오래 걸리지 않는다** — 진행 표시가 실제로 그려지는지.

신고는 "윈도우에서 설치·업데이트 때 프로그레스 바 같은 게 안 보인다"였다. 설치기(install.ps1)
쪽은 tests/test_install_ps1.py가 잡고, 이 파일은 나머지 절반인 `asgard update`를 본다.

여기서 잡히는 것과 안 잡히는 것을 갈라 둔다:
  · Windows 콘솔에서 색·ANSI가 켜지는가 → tests/test_color_capability.py (그게 `_COLOR` 다)
  · 그 `_COLOR`가 켜졌을 때 바·등불이 **정말 그려지는가** → 이 파일
두 번째가 비어 있으면 첫 번째만 초록인 채로 화면은 그대로 멎어 있을 수 있다. 실제로 그 조합이
"UI 판정은 고쳤는데 사용자는 여전히 아무것도 못 본다"의 모양이다.

뒤쪽 절반은 같은 화면의 실패 쪽이다: uv가 실패한 이유가 화면에 남는지, 그리고 Windows에서
설치가 자기 자신을 지우려 들지 않는지.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time

import pytest

from asgard import ui
from asgard.commands import update


class _Sink:
    """스레드에서도 쓰이는 stdout 대역 (spin은 별도 스레드가 그린다)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._parts: list[str] = []

    def write(self, s: str) -> int:
        with self._lock:
            self._parts.append(s)
        return len(s)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return True

    @property
    def text(self) -> str:
        with self._lock:
            return "".join(self._parts)


def _sink(monkeypatch) -> _Sink:
    """stdout 대역 — **본문에서** 갈아야 한다.

    픽스처에 두면 못 잡는다: pytest는 setup 국면과 call 국면 사이에 캡처를 다시 꽂아 픽스처가
    심어둔 sys.stdout을 덮는다. 같은 함정을 두 번 밟았다 (macOS 픽스처 / Windows 콘솔 핸들) —
    **pytest 픽스처는 프로세스 전역 IO 상태를 못 붙든다**가 그 교훈이고, 여기가 세 번째 자리다.
    """
    s = _Sink()
    monkeypatch.setattr("sys.stdout", s)
    return s


def _capable(monkeypatch) -> None:
    """색 가능한 터미널 — Windows 콘솔에서 이 상태가 되는 것은 test_color_capability가 증명한다."""
    monkeypatch.setattr(ui, "_COLOR", True)
    monkeypatch.setattr(ui, "_QUIET", False)


def _plain(monkeypatch) -> None:
    monkeypatch.setattr(ui, "_COLOR", False)
    monkeypatch.setattr(ui, "_QUIET", False)


# ── 진행률 바 ────────────────────────────────────────────────────────────────


def test_bar_draws_a_determinate_gauge(monkeypatch) -> None:
    """총량을 아는 다운로드는 채워지는 바 + % + MB로 보여야 한다 (사용자가 없다고 한 그것)."""
    _capable(monkeypatch)
    sink = _sink(monkeypatch)
    with ui.bar("asgard wheel", 4_000_000) as b:
        b.advance(1_000_000)
        b.advance(1_000_000)
    out = sink.text
    assert "25%" in out and "50%" in out, out
    assert "1.0/4.0 MB" in out and "2.0/4.0 MB" in out, out
    assert "asgard wheel" in out
    assert "━" in out, "the filled portion of the gauge never appeared"


def test_bar_redraws_in_place(monkeypatch) -> None:
    """매 프레임 \\r로 같은 줄을 다시 쓴다 — 안 그러면 다운로드 한 번이 화면을 수백 줄 밀어낸다."""
    _capable(monkeypatch)
    sink = _sink(monkeypatch)
    with ui.bar("asgard wheel", 1000) as b:
        b.advance(500)
    assert sink.text.count("\r") >= 3  # 최초 그리기 + advance + 종료 시 지우기
    assert "\n" not in sink.text, "the gauge broke onto a new line"


def test_bar_clears_its_line_on_exit(monkeypatch) -> None:
    """바가 남아 있으면 뒤따르는 ✔ 가 그 위에 겹쳐 찍힌다."""
    _capable(monkeypatch)
    sink = _sink(monkeypatch)
    with ui.bar("asgard wheel", 1000) as b:
        b.advance(1000)
    assert sink.text.endswith("\r\x1b[K")


def test_bar_without_a_total_still_shows_movement(monkeypatch) -> None:
    """Content-Length 없는 서버에서도 누적 MB는 흐른다 — 침묵보다 낫다."""
    _capable(monkeypatch)
    sink = _sink(monkeypatch)
    with ui.bar("asgard wheel", 0) as b:
        b.advance(2_500_000)
    assert "2.5 MB" in sink.text


def test_bar_writes_nothing_into_a_pipe(monkeypatch) -> None:
    """리다이렉트된 로그에 ANSI와 \\r가 쏟아지면 로그가 못 읽는 물건이 된다."""
    _plain(monkeypatch)
    sink = _sink(monkeypatch)
    with ui.bar("asgard wheel", 1000) as b:
        b.advance(1000)
    assert sink.text == ""


# ── 등불(스피너) ─────────────────────────────────────────────────────────────


def test_spin_animates_and_clears(monkeypatch) -> None:
    """총량을 모르는 단계(uv tool install)는 등불이 살아 있음을 알린다."""
    _capable(monkeypatch)
    sink = _sink(monkeypatch)
    with ui.spin("installing asgard v9.9.9…"):
        time.sleep(0.3)
    out = sink.text
    assert "installing asgard v9.9.9…" in out
    frames = {ch for ch in out if ch in "✦✧"}
    assert len(frames) >= 1, out
    assert out.count("\r") >= 3, "the lantern never redrew"
    assert out.endswith("\r\x1b[K"), "the lantern line was left on screen"


def test_spin_is_silent_in_a_pipe(monkeypatch) -> None:
    _plain(monkeypatch)
    sink = _sink(monkeypatch)
    with ui.spin("installing…"):
        time.sleep(0.15)
    assert sink.text == ""


# ── update가 그 둘을 실제로 쓰는가 ──────────────────────────────────────────


class _RecordBar:
    calls: list[tuple[str, int]] = []
    advanced: list[int] = []

    def __init__(self, label: str, total: int) -> None:
        _RecordBar.calls.append((label, total))

    def __enter__(self) -> "_RecordBar":
        return self

    def advance(self, n: int) -> None:
        _RecordBar.advanced.append(n)

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeResponse:
    def __init__(self, chunks: list[bytes], length: int | None) -> None:
        self._chunks = list(chunks)
        self.headers = {"Content-Length": str(length)} if length is not None else {}

    def read(self, _n: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_download_reports_progress_against_content_length(monkeypatch, tmp_path) -> None:
    """휠 내려받기는 서버가 알려준 총량으로 **결정적** 바를 연다 — 이게 사용자가 찾던 프로그레스 바다."""
    _RecordBar.calls, _RecordBar.advanced = [], []
    monkeypatch.setattr(update.ui, "bar", _RecordBar)
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda *a, **k: _FakeResponse([b"x" * 100, b"y" * 40], 140))
    dest = tmp_path / "asgard.whl"
    update._download("https://example.invalid/asgard.whl", str(dest))
    assert _RecordBar.calls == [("asgard wheel", 140)]
    assert _RecordBar.advanced == [100, 40]
    assert dest.read_bytes() == b"x" * 100 + b"y" * 40


def test_download_survives_a_server_with_no_content_length(monkeypatch, tmp_path) -> None:
    """총량 미상은 0으로 열린다 (누적 MB 표시) — 예외로 죽으면 업데이트 자체가 끊긴다."""
    _RecordBar.calls, _RecordBar.advanced = [], []
    monkeypatch.setattr(update.ui, "bar", _RecordBar)
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda *a, **k: _FakeResponse([b"z" * 10], None))
    update._download("https://example.invalid/asgard.whl", str(tmp_path / "w.whl"))
    assert _RecordBar.calls == [("asgard wheel", 0)]


def test_uv_install_runs_inside_a_spinner(monkeypatch) -> None:
    """uv 설치는 수십 초 걸리고 출력이 없다 — 그 구간이 등불 안에 들어 있어야 한다."""
    seen: list[str] = []
    ran_inside: list[bool] = []
    spinning = {"on": False}

    class _Spin:
        def __init__(self, label: str) -> None:
            seen.append(label)

        def __enter__(self) -> "_Spin":
            spinning["on"] = True
            return self

        def __exit__(self, *exc: object) -> bool:
            spinning["on"] = False
            return False

    class _Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def _run(*a: object, **k: object) -> _Done:
        ran_inside.append(spinning["on"])
        return _Done()

    monkeypatch.setattr(update.ui, "spin", _Spin)
    monkeypatch.setattr(update.subprocess, "run", _run)
    assert update._uv_install("asgard-9.9.9.whl", "installing asgard v9.9.9…") == (0, "")
    assert seen == ["installing asgard v9.9.9…"]
    assert ran_inside == [True], "uv ran outside the spinner - the screen would sit dead"


# ── 실패했을 때 uv가 한 말 ───────────────────────────────────────────────────


def _failing_uv(monkeypatch, message: str) -> None:
    monkeypatch.setattr(update, "_WIN", False)
    monkeypatch.setattr(update, "_download", lambda url, dest: pathlib.Path(dest).write_bytes(b""))
    monkeypatch.setattr(update, "_uv_install", lambda spec, label: (1, message))


def test_a_failed_install_prints_what_uv_said(monkeypatch, capsys) -> None:
    """`update failed (uv tool install)` 한 줄은 원인을 못 담는다 — 인터프리터 없음도, 프록시도,
    잠긴 파일도 화면에서 같은 문장이었다. 사용자가 신고할 수 있는 유일한 물건이 uv의 출력이다."""
    _plain(monkeypatch)
    _failing_uv(monkeypatch, "error: No interpreter found for Python 3.14 in managed installations")
    assert update._install_release({}, "9.9.9", False, False, False) == 1
    seen = capsys.readouterr()
    assert "No interpreter found for Python 3.14" in seen.out + seen.err


def test_json_failure_carries_the_uv_error(monkeypatch, capsys) -> None:
    """--json 소비자(설치 스크립트·CI)도 같은 원인을 받는다."""
    _plain(monkeypatch)
    monkeypatch.setattr(ui, "_QUIET", True)  # run_update가 --json에서 거는 것과 같은 상태
    _failing_uv(monkeypatch, "error: Access is denied. (os error 5)")
    assert update._install_release({}, "9.9.9", False, False, True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "error: Access is denied. (os error 5)"
    assert payload["updated"] is False


# ── Windows: 자기 자신을 갈아 끼우는 설치 ────────────────────────────────────


def _windows(monkeypatch, tmp_path, *, powershell: bool = True) -> tuple[list[tuple], list[tuple[str, str]]]:
    """Windows 흉내 — 이 프로세스에서 uv가 돌면 그것 자체가 결함이다."""
    monkeypatch.setattr(update, "_WIN", True)
    found = {"asgard": r"C:\Users\odin\.local\bin\asgard.exe"}
    if powershell:
        found["powershell"] = r"C:\Windows\System32\powershell.exe"
    monkeypatch.setattr(update.shutil, "which", found.get)
    update_dir = tmp_path / "asgard-update"
    update_dir.mkdir()
    monkeypatch.setattr(update.tempfile, "mkdtemp", lambda prefix: str(update_dir))
    downloads: list[tuple[str, str]] = []

    def _download(url: str, dest: str) -> None:
        downloads.append((url, dest))
        pathlib.Path(dest).write_bytes(b"wheel")

    monkeypatch.setattr(update, "_download", _download)
    monkeypatch.setattr(update, "_uv_install", lambda spec, label: pytest.fail("uv ran inside the process it replaces"))
    spawned: list[tuple] = []
    monkeypatch.setattr(update.subprocess, "Popen", lambda argv, **kw: spawned.append((argv, kw)))
    return spawned, downloads


def test_windows_installs_from_a_process_that_outlives_this_one(monkeypatch, tmp_path) -> None:
    """`uv tool install --force`는 도구 환경을 지우고 다시 만든다 — 그 안의 python.exe가 지금
    이 프로세스다. Windows는 실행 중인 파일을 못 지우므로 설치는 이 프로세스가 끝난 뒤여야 한다."""
    _plain(monkeypatch)
    spawned, downloads = _windows(monkeypatch, tmp_path)
    assert update._install_release({}, "0.10.5", True, False, False) == 0
    assert downloads == [
        (
            update._wheel_url("0.10.5"),
            str(tmp_path / "asgard-update" / "asgard-0.10.5-py3-none-any.whl"),
        )
    ]
    (argv, kw) = spawned[0]
    script = argv[-1]
    assert f"Wait-Process -Id {os.getpid()}" in script, "설치가 이 프로세스를 안 기다린다"
    assert f"Get-Process -Id {os.getppid()}" in script, "asgard.exe launcher의 잠금 여부를 확인하지 않는다"
    assert "Wait-Process -InputObject $launcher" in script, "실행 중인 asgard.exe launcher를 기다리지 않는다"
    assert "Start-Sleep" not in script, "파일 잠금 해제를 고정 시간으로 추측한다"
    assert "-Timeout" not in script, "REPL이 열린 채면 timeout 뒤 같은 잠긴 환경을 다시 지우려 한다"
    assert "uv tool install --force --python 3.14" in script
    assert downloads[0][1] in script, "진행률을 표시하며 받은 로컬 휠을 helper에 넘기지 않았다"
    assert str(tmp_path / "asgard-update") in script, "helper가 임시 휠을 정리하지 않는다"
    assert r"'C:\Users\odin\.local\bin\asgard.exe' completions powershell --install" in script
    assert r"'C:\Users\odin\.local\bin\asgard.exe' sync" in script
    sync_at = script.index(r"'C:\Users\odin\.local\bin\asgard.exe' sync")
    done_at = script.index("update done")
    assert sync_at < script.index("$syncCode = $LASTEXITCODE", sync_at) < done_at
    assert sync_at < script.index("sync failed - press Enter to close", sync_at) < done_at
    assert "exit $syncCode" in script[sync_at:done_at]
    assert kw["creationflags"] == getattr(update.subprocess, "CREATE_NEW_CONSOLE", 0)


def test_windows_handoff_skips_sync_when_asked(monkeypatch, tmp_path) -> None:
    _plain(monkeypatch)
    spawned, _ = _windows(monkeypatch, tmp_path)
    update._install_release({}, "0.10.5", False, False, False)
    assert "sync" not in spawned[0][0][-1]


def test_windows_without_powershell_tells_the_user_the_command(monkeypatch, tmp_path, capsys) -> None:
    """창을 못 열면 사람이 칠 수 있는 한 줄을 남긴다 — 조용한 실패는 여기서 제일 나쁜 결말이다."""
    _plain(monkeypatch)
    _, downloads = _windows(monkeypatch, tmp_path, powershell=False)
    assert update._install_release({}, "0.10.5", True, False, False) == 1
    seen = capsys.readouterr()
    assert f"uv tool install --force --python 3.14 {downloads[0][1]}" in seen.out + seen.err


def test_powershell_quoting_survives_a_quote_in_the_spec(monkeypatch) -> None:
    """ASGARD_INSTALL_SPEC은 로컬 경로일 수 있다 — 작은따옴표가 들면 스크립트가 통째로 깨진다."""
    monkeypatch.setattr(update.shutil, "which", lambda n: None)
    script = update._handoff_script("C:\\o'din\\asgard.whl", False)
    assert "'C:\\o''din\\asgard.whl'" in script
