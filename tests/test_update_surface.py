"""업데이트가 **말없이 오래 걸리지 않는다** — 진행 표시가 실제로 그려지는지.

신고는 "윈도우에서 설치·업데이트 때 프로그레스 바 같은 게 안 보인다"였다. 설치기(install.ps1)
쪽은 tests/test_install_ps1.py가 잡고, 이 파일은 나머지 절반인 `asgard update`를 본다.

여기서 잡히는 것과 안 잡히는 것을 갈라 둔다:
  · Windows 콘솔에서 색·ANSI가 켜지는가 → tests/test_color_capability.py (그게 `_COLOR` 다)
  · 그 `_COLOR`가 켜졌을 때 바·등불이 **정말 그려지는가** → 이 파일
두 번째가 비어 있으면 첫 번째만 초록인 채로 화면은 그대로 멎어 있을 수 있다. 실제로 그 조합이
"UI 판정은 고쳤는데 사용자는 여전히 아무것도 못 본다"의 모양이다.
"""

from __future__ import annotations

import threading
import time

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

    def _run(*a: object, **k: object) -> _Done:
        ran_inside.append(spinning["on"])
        return _Done()

    monkeypatch.setattr(update.ui, "spin", _Spin)
    monkeypatch.setattr(update.subprocess, "run", _run)
    assert update._uv_install("asgard-9.9.9.whl", "installing asgard v9.9.9…") == 0
    assert seen == ["installing asgard v9.9.9…"]
    assert ran_inside == [True], "uv ran outside the spinner - the screen would sit dead"
