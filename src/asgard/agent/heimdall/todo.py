"""배정 단위 진행 보드 — 계획을 열어 보이고, 하나씩 닫히는 것을 보여준다.

Thinker 가 쪼갠 배정 단위는 지금까지 실행 중에만 흘러갔다: `wave [1, 2]` 한 줄과 완료 줄.
오딘 쪽에서 보면 **무엇을 몇 개로 쪼갰는지**와 **지금 몇 번째인지**가 안 보인다 — 진행이
아니라 소음으로 읽힌다. 보드는 그 둘을 표면으로 올린다.

활동 스트림은 append-only 다 (하단 독은 고정 6행, 출력은 그 위로 삽입만 된다). 위로 올라가
다시 그릴 수 없으므로 전이마다 전체를 재출력하지 않는다 — 열 때와 닫을 때만 전체 보드를 찍고,
사이에는 상태가 바뀐 단위 한 줄씩 흘린다. 단위가 하나뿐이면 전체 보드는 그 한 줄과 같은 말이라
생략한다 (대부분의 퀘스트가 단일 단위 — 여기서 두 번 찍으면 보드가 소음이 된다).

호출 순서는 plan → start/mark* → close 이고, 전부 호출부의 단일 스레드에서 일어난다:
wave 는 병렬로 뛰지만 상태 전이는 fan-in 지점(as_completed 수거 루프)에서만 기록한다.
"""

from __future__ import annotations

from collections.abc import Iterable

from ... import i18n, theme, ui

# 사용자 표면 글리프는 텍스트 기호만 (이모지 금지 — Canon 표면 규약). 상태 하나에 글리프 하나.
_GLYPH: dict[str, str] = {"todo": "·", "run": "▸", "done": "✓", "failed": "✗", "blocked": "⚠"}
_RESOLVED = frozenset({"done", "failed", "blocked"})


def files_note(n: int) -> str:
    """완료 단위의 산출 규모 한 마디 — 영어 표면 단복수를 맞춘다 (Bragi 계약: "1 files" 금지)."""
    return i18n.t("todo_unit_file" if n == 1 else "todo_unit_files", n=n)


def _painted(state: str) -> str:
    glyph = _GLYPH.get(state, _GLYPH["todo"])
    if state == "done":
        return ui.paint(ui._OK, glyph)
    if state == "failed":
        return ui.paint(ui._FAIL, glyph)
    if state == "blocked":
        return ui.paint(ui._WARN, glyph)
    if state == "run":
        return ui.paint(theme.ansi(theme.PRIMARY), glyph)
    return ui.dim(glyph)


class TodoBoard:
    """한 판의 진행 보드. on_text 스트림에 append 로만 그린다 (재출력·커서 이동 없음)."""

    def __init__(self, on_text, head_key: str = "todo_head") -> None:
        self._on_text = on_text
        self._head_key = head_key
        self._items: dict[str, dict] = {}
        self._order: list[str] = []
        self._closed = False

    # ── 상태 전이 ───────────────────────────────────────────────────

    def plan(self, items: Iterable[tuple[object, str]]) -> None:
        """(id, 과업 문장) 목록을 등록하고 여는 보드를 찍는다 — 2단위 이상일 때만."""
        for ident, text in items:
            key = str(ident)
            if key not in self._items:
                self._order.append(key)
            self._items[key] = {"text": str(text or ""), "state": "todo", "note": ""}
        if len(self._order) > 1:
            self._board()

    def start(self, idents: Iterable[object]) -> None:
        """이 wave 에 들어간 단위 — 진행 중 표식. 무엇이 지금 도는지가 id 목록만으로는 안 읽힌다."""
        for ident in idents:
            self._set(ident, "run")

    def mark(self, ident: object, state: str, note: str = "") -> None:
        self._set(ident, state, note)

    def close(self) -> None:
        """닫는 보드 — 최종 상태 + 결과 요약. 두 번 불려도 한 번만 찍는다 (finally 중복 경로)."""
        if self._closed:
            return
        self._closed = True
        if len(self._order) < 2:
            return
        done = sum(1 for key in self._order if self._items[key]["state"] == "done")
        left = len(self._order) - done
        tail = " · " + i18n.t("todo_summary_done", n=done)
        if left:
            tail += " · " + i18n.t("todo_summary_left", n=left)
        self._board(tail)

    # ── 조회 ────────────────────────────────────────────────────────

    def resolved(self) -> int:
        return sum(1 for key in self._order if self._items[key]["state"] in _RESOLVED)

    def total(self) -> int:
        return len(self._order)

    # ── 렌더 ────────────────────────────────────────────────────────

    def _set(self, ident: object, state: str, note: str = "") -> None:
        key = str(ident)
        item = self._items.get(key)
        if item is None:  # 계획에 없던 단위 — 재개 스냅샷·재배정이 늦게 실어 올 수 있다
            self._order.append(key)
            item = {"text": key, "state": "todo", "note": ""}
            self._items[key] = item
        item["state"], item["note"] = state, note
        self._on_text(self._line(key, counter=state in _RESOLVED))

    def _line(self, key: str, counter: bool = False) -> str:
        item = self._items[key]
        note = f" · {item['note']}" if item["note"] else ""
        count = f"  [{self.resolved()}/{len(self._order)}]" if counter else ""
        # 앞머리 = 들여쓰기 4 + 글리프 1 + 공백 1 + id + 공백 2. 넘치면 터미널이 접어 버려 보드
        # 정렬이 무너진다 — ANSI 를 입히기 전, 실제로 찍힐 원문의 표시 폭으로 잰다.
        # 마지막 한 칸은 비워 둔다: 폭에 정확히 들어맞는 줄에서 커서를 다음 행으로 넘기는 터미널이 있다.
        spent = 9 + ui.disp_width(key) + ui.disp_width(note) + ui.disp_width(count)
        text = ui.fit(item["text"], max(20, ui.stream_width() - spent))
        head = ui.dim(f"{key}  {text}") if item["state"] == "todo" else f"{ui.dim(key)}  {text}"
        return f"    {_painted(item['state'])} {head}{ui.dim(note)}{ui.dim(count)}\n"

    def _board(self, tail: str = "") -> None:
        head = i18n.t(self._head_key, n=len(self._order)) + tail
        rows = "".join(self._line(key) for key in self._order)
        self._on_text(f"\n  {ui._mark()} {ui.bold(head)}\n{rows}")
