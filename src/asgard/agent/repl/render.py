"""출력 — 스트리밍 렌더러, 스피너, 되짚기 한 줄, 그리고 종료 인사."""

from __future__ import annotations

import sys

from ... import theme, ui
from ...i18n import t
from .chrome import _O


def _new_heimdall(root: str, rp, emit, status=None):
    from ...providers import project_section
    from ..heimdall import Heimdall

    hd = Heimdall(rp, root, on_text=emit, on_status=status)
    hd.dual_mode = project_section(root, "trinity.mode").get("dual") is True
    return hd


class _Spinner:
    """on_status 핸들러 — 침묵 구간(thinking·툴 실행)에 라이브 스피너. 라벨 None 이면 해제."""

    def __init__(self) -> None:
        self._cur: ui.spin | None = None
        self._label: str | None = None

    def __call__(self, label: str | None) -> None:
        if label == self._label:  # 동일 상태 반복 신호(스트림 청크마다 None 등) — 무시
            return
        if self._cur:
            self._cur.__exit__(None, None, None)
            self._cur = None
        if label:
            self._cur = ui.spin(label)
            self._cur.__enter__()
        self._label = label


_MD_BOLD = None  # re 모듈 lazy — 아래 _Render에서 컴파일


class _Render:
    """스트리밍 md-lite 렌더 — 응답 본문을 2칸 들여쓰고 라인 단위로 가볍게 스타일.

    완성 라인: **볼드**·`코드`(시안)·헤더(골드)·불릿(•) 적용. 오래 안 끝나는 라인(긴 문단)은
    스타일 포기하고 즉시 플러시 — 라이브함이 스타일보다 우선. 세션 메타 라인('  │ …' 활동 스레드 등,
    이미 들여쓰기됨)은 그대로 통과하고, 미종결 산문에 접착되지 않게 write()가 먼저 닫는다."""

    FLUSH_AT = 160

    def __init__(self) -> None:
        import re

        self._re = re
        self.buf = ""
        self.dirty = False  # 현재 라인을 이미 raw로 흘려보냄 — 완성 시 스타일 생략
        self._sink = None  # 독 모드 싱크(dock.write) — 완성 라인만 전달. None=stdout 직행

    def attach(self, sink) -> None:
        """독 모드 전환 — 잔여 버퍼를 현 싱크로 먼저 방출하고 교체. 독 모드는 완성 라인 단위로만
        흘려보낸다(부분 라인 raw 스트림은 독 redraw와 충돌). 긴 문단은 폭 경계 소프트랩으로
        라인을 확정 — 터미널 자연 랩과 같은 자리라 시각 동일, 라이브함 유지."""
        self.finish()
        self._sink = sink

    def _sink_write(self, s: str) -> None:
        sink = self._sink
        if sink is None:
            return
        self.buf += s
        lines: list[str] = []
        budget = max(24, ui.stream_width() - 4)
        while True:
            if "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                lines.append(self._line(line))
                continue
            if len(self.buf) >= budget:  # 소프트랩 — 마지막 공백에서 자르고 라인 확정
                cut = self.buf.rfind(" ", 0, budget)
                cut = cut if cut > 0 else budget
                line, self.buf = self.buf[:cut], self.buf[cut:].lstrip(" ")
                lines.append(self._line(line))
                continue
            break
        if lines:
            sink("\n".join(lines) + "\n")

    def _line(self, line: str) -> str:
        """싱크 모드 라인 스타일 — _emit_line과 같은 규칙, 문자열 반환."""
        if line.startswith("  ") or not line.strip():
            return line
        return "  " + self._style(line)

    def write(self, s: str) -> None:
        if self._sink is not None:
            self._sink_write(s)
            return
        # 활동 라인(완성된 메타 라인 — 앞 2칸 들여쓰기)이 미종결 산문에 접착되는 것을 막는다:
        # 두 생산자(모델 산문 · 툴/전이 라인)가 한 싱크를 공유하므로, 메타 라인이 오면 대기 산문을 먼저 닫는다.
        if "\n" in s and s.lstrip("\n").startswith("  "):
            if self.dirty:  # 산문이 이미 raw로 흘러나간 상태 — 개행으로 닫는다
                sys.stdout.write("\n")
                sys.stdout.flush()
                self.dirty = False
            elif self.buf:  # 버퍼에 미종결 산문 — 자기 라인으로 방출
                self._emit_line(self.buf)
                self.buf = ""
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self._emit_line(line)
        if len(self.buf) >= self.FLUSH_AT:
            if not self.dirty:
                sys.stdout.write("  ")
                self.dirty = True
            sys.stdout.write(self.buf)
            sys.stdout.flush()
            self.buf = ""

    def finish(self) -> None:
        if self.buf:
            if self._sink is not None:
                self._sink(self._line(self.buf) + "\n")
            else:
                self._emit_line(self.buf)
            self.buf = ""

    def _emit_line(self, line: str) -> None:
        if self.dirty:  # 이미 raw로 나간 라인의 잔여
            sys.stdout.write(line + "\n")
            self.dirty = False
        elif line.startswith("  ") or not line.strip():  # 메타 라인·공백 — 무가공
            sys.stdout.write(line + "\n")
        else:
            sys.stdout.write("  " + self._style(line) + "\n")
        sys.stdout.flush()

    def _style(self, line: str) -> str:
        re = self._re
        if not ui._COLOR:
            return line
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:  # 헤더 — 골드 볼드
            return ui.bold(ui.paint(_O, m.group(2)))
        line = re.sub(r"\*\*(.+?)\*\*", lambda x: ui.bold(x.group(1)), line)
        line = re.sub(r"`([^`]+)`", lambda x: ui.paint(theme.ansi(theme.ACCENT_CYAN), x.group(1)), line)
        line = re.sub(r"^(\s*)[-*]\s+", lambda x: x.group(1) + ui.paint(_O, "•") + " ", line)
        return line


def _bye() -> int:
    sys.stdout.write(f"\n  {ui.dim(t('bye'))}\n")
    return 0


def _run_bang(root: str, cmd: str) -> None:
    """!cmd — 관찰 명령만 직접 실행. 변경은 일반 요청의 Trinity 경로로 보낸다."""
    from ...hooks.readonly_guard import is_readonly_bash_safe
    from .. import tools as T

    if not is_readonly_bash_safe(cmd, root):
        sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} ! 명령은 읽기만 해요. 뭔가 바꾸려면 그냥 말씀해 주세요.\n")
        return

    try:
        out, code = T.run_bash(root, {"command": cmd})
        sys.stdout.write(f"  {ui.dim('$ ' + cmd)}\n{out}\n")
        if code:
            sys.stdout.write(f"  {ui.dim('exit ' + str(code))}\n")
    except T.ToolError as e:
        sys.stdout.write(f"  {ui.paint(ui._FAIL, '⚠')} {e}\n")


def _recap_sentence(recap: dict) -> str:
    """턴 활동 → 자연어 한 문장 — '{f} 수정 ×3 · {f} 생성 · pytest ×2 실행 · 에이전트 worker×2'.
    이미지·클로드코드 recap 스타일: 카운터 표가 아니라 읽히는 문장, 활동 없으면 빈 문자열."""
    parts: list[str] = []
    files = list((recap.get("files") or {}).items())
    for path, info in files[:6]:
        phrase = t("recap_created" if info.get("op") == "create" else "recap_patched", f=path)
        if info.get("n", 1) > 1:
            phrase += f" ×{info['n']}"
        parts.append(phrase)
    if len(files) > 6:
        parts.append(f"+{len(files) - 6}")
    cmds = recap.get("cmds")
    if cmds:
        shown = cmds.most_common(5)
        parts += [t("recap_ran", c=f"{c} ×{n}" if n > 1 else c) for c, n in shown]
        if len(cmds) > 5:
            parts.append(f"+{len(cmds) - 5}")
    agents = recap.get("agents")
    if agents:
        parts.append(t("recap_agents", a=", ".join(f"{k}×{v}" if v > 1 else str(k) for k, v in agents.most_common())))
    return " · ".join(parts)


def _memory_badge(recap: dict, ctx_tokens: int) -> str:
    """답변 소스 배지('⠶ 무닌 ~n%') — 이 턴에 결정론 회상(숏컷)으로 주입된 기억이 컨텍스트에서
    차지한 근사 비중. 무닌 = 오딘의 기억 까마귀 — 위그드라실 세계관에서 회상의 표상.
    회상이 실제 발동한 턴에만 나타난다. 문자수→토큰 환산은 한/영 혼용 근사(~3자/토큰)라 ~ 표기,
    컨텍스트 크기를 모르면(첫 턴 오류 등) 절대량(k)으로 축퇴."""
    chars = recap.get("recall_chars") or 0
    if not isinstance(chars, int) or chars <= 0:
        return ""
    est = max(1, chars // 3)
    if isinstance(ctx_tokens, int) and ctx_tokens > 0:
        pct = max(1, min(99, round(est * 100 / ctx_tokens)))
        return " · ⠶ " + t("recap_memory_pct", p=pct)
    return " · ⠶ " + t("recap_memory_tok", k=f"{est / 1000:.1f}")


def _turn_recap_str(hd, rp, secs: float, spent: int) -> str:
    """턴 종료 recap — '✓ done' 요약줄 + 자연어 한 문장(딤, ⠶ 브랜드 도트마크 — 위그드라실 표식).

    hermes recap 상응: 1순위는 메타 이벤트(기억 저장·프로젝트 메모리 보존/제안·증류 —
    백그라운드에서 함께 일어난 부수 작업), 이벤트가 없으면 활동 문장(수정 파일·커맨드·에이전트).
    회상(숏컷) 발동 턴은 done 줄에 답변 소스 배지('⠶ 무닌 ~n%')를 함께 표기한다."""
    tok = f" · {spent / 1000:.1f}k tok" if spent else ""
    recap = getattr(hd, "turn_recap", None)
    if not isinstance(recap, dict):
        return f"  {ui.dim(f'✓ done · {rp.model} · {secs:.1f}s{tok}')}"
    mem = _memory_badge(recap, getattr(hd, "last_context_tokens", 0) or 0)
    lines = [f"  {ui.dim(f'✓ done · {rp.model} · {secs:.1f}s{tok}{mem}')}"]
    events = recap.get("events") or []
    sentence = " · ".join(events) if events else _recap_sentence(recap)
    if sentence:
        import textwrap

        for ln in textwrap.wrap("⠶ " + sentence, width=max(24, ui.stream_width() - 4)):
            lines.append("    " + ui.dim(ln))
    return "\n".join(lines)
