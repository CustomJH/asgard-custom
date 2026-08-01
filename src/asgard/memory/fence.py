"""주입 펜스 누출 차단 — 모델이 되뱉은 메모리 블록을 표면에 닿기 전에 제거한다.

개인 메모리는 `<memory-context>` / `<memory-recall>` 펜스에 담겨 프롬프트로 들어간다.
모델은 자기가 본 것을 따라 적을 수 있고, 그러면 두 가지가 한꺼번에 샌다 — 사람 화면에는
내부 비계가 노출되고, 그 텍스트가 다시 프롬프트로 접히는 경로(역할 간 전달)에서는 **위조된
펜스**가 정본 메모리 행세를 한다. 저장 경로의 `_neutralize`는 페이지 내용의 각괄호만
무력화하므로 모델 자신의 출력은 거기 걸리지 않는다.

한 번에 다 온 문자열이면 정규식 한 방이면 된다. 스트리밍에서는 안 된다: 여는 태그와 닫는
태그가 서로 다른 델타에 떨어지는 순간 정규식은 둘 다 못 보고 그 사이 내용이 그대로 화면으로
나간다. 그래서 델타를 가로질러 상태를 들고, 태그가 될 수 있는 꼬리는 붙잡아 둔다.

줄머리에서 시작하는 펜스만 본다. 산문 안에서 태그 이름을 언급하는 정상 문장
("`<memory-context>`는 카탈로그다")까지 삼키면 설명을 못 하는 도구가 된다.
"""

from __future__ import annotations

TAGS = ("memory-context", "memory-recall")
_OPEN = tuple(f"<{tag}" for tag in TAGS)


def _hold(buf: str, needle: str) -> int:
    """buf의 접미사 중 needle의 접두사가 되는 가장 긴 것의 길이 — 없으면 0.

    이만큼은 아직 판정할 수 없다. 다음 델타가 와야 태그인지 그냥 글자인지 갈린다."""
    for size in range(min(len(buf), len(needle) - 1), 0, -1):
        if needle.startswith(buf[-size:]):
            return size
    return 0


class FenceScrubber:
    """스트리밍 텍스트에서 메모리 펜스 블록을 제거하는 상태기계.

    턴마다 `reset()`, 스트림 끝에서 `flush()`. 닫히지 않은 블록 안에서 스트림이 끝나면
    남은 내용은 버린다 — 잘린 답보다 새는 메모리가 나쁘다."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._closing: str | None = None  # 찾는 중인 닫는 태그 (None = 블록 밖)
        self._buf = ""  # 태그가 될 수 있어 붙잡아 둔 꼬리
        self._line_start = True  # 다음 문자가 줄머리인가

    def feed(self, text: str) -> str:
        """이 델타에서 사람에게 보여도 되는 부분만 돌려준다."""
        if not text:
            return ""
        buf, self._buf = self._buf + text, ""
        out: list[str] = []
        while buf:
            if self._closing:
                idx = buf.find(self._closing)
                if idx == -1:  # 아직 안 닫혔다 — 내용은 버리고 닫는 태그 조각만 붙잡는다
                    if held := _hold(buf, self._closing):
                        self._buf = buf[-held:]
                    return "".join(out)
                buf = buf[idx + len(self._closing) :]
                self._closing = None
                self._line_start = False
                continue
            at, tag = self._find_open(buf)
            if at is None:  # 펜스 없음 — 태그 첫머리가 될 수 있는 꼬리만 남긴다
                held = max((_hold(buf, opener) for opener in _OPEN), default=0)
                if held:
                    self._append(out, buf[:-held])
                    self._buf = buf[-held:]
                else:
                    self._append(out, buf)
                return "".join(out)
            self._append(out, buf[:at])
            rest = buf[at:]
            end = rest.find(">")  # 여는 태그는 속성을 단다 (scope="personal")
            if end == -1:  # 태그가 아직 안 끝났다 — 통째로 붙잡는다
                self._buf = rest
                return "".join(out)
            self._closing = f"</{tag}>"
            buf = rest[end + 1 :]
        return "".join(out)

    def flush(self) -> str:
        """스트림 끝 — 붙잡아 둔 꼬리를 내보낸다. 블록 안이었으면 버린다."""
        if self._closing:
            self.reset()
            return ""
        tail, self._buf = self._buf, ""
        return tail

    def scrub(self, text: str) -> str:
        """비스트리밍 한 방 — 완결된 문자열 하나를 걸러낸다 (역할 간 전달용)."""
        self.reset()
        cleaned = self.feed(text) + self.flush()
        self.reset()
        return cleaned

    def _find_open(self, buf: str) -> tuple[int | None, str]:
        """줄머리에서 시작하는 여는 태그의 위치와 태그명 — 없으면 (None, "")."""
        best: tuple[int, str] | None = None
        for tag, opener in zip(TAGS, _OPEN, strict=True):
            start = 0
            while (i := buf.find(opener, start)) != -1:
                if self._starts_line(buf, i):
                    if best is None or i < best[0]:
                        best = (i, tag)
                    break
                start = i + 1
        return (best[0], best[1]) if best else (None, "")

    def _starts_line(self, buf: str, i: int) -> bool:
        if i == 0:
            return self._line_start
        head = buf[:i]
        nl = head.rfind("\n")
        return head.strip() == "" and self._line_start if nl == -1 else head[nl + 1 :].strip() == ""

    def _append(self, out: list[str], text: str) -> None:
        if not text:
            return
        out.append(text)
        nl = text.rfind("\n")
        self._line_start = text[nl + 1 :].strip() == "" if nl != -1 else (self._line_start and text.strip() == "")


def scrub(text: str) -> str:
    """완결된 문자열에서 펜스 블록을 제거한다 — 스트림이 아닌 자리의 편의 함수."""
    return FenceScrubber().scrub(text)
