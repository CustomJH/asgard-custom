"""세션에 1회 동결되는 카탈로그 — 칸별 예산 안에서 주입 블록을 렌더한다."""

from __future__ import annotations

from ..policy import index_budget, inject_enabled, kind_budgets, memory_dir
from ..store import _desc, _kind
from .clean import clean_pages
from .rows import _neutralize, _row

_SNAPSHOT_WARN = "- … (index over budget — asgard memory lint)"


# 칸 이름 — 사람이 읽는 표면이라 세계관 어휘를 쓴다. 순서가 곧 주입 순서다:
# 값비싼 칸을 앞에 둬서 총량 상한이 걸릴 때 뒤(싼 칸)부터 잘리게 한다.
_SECTIONS: tuple[tuple[str, str], ...] = (
    ("user", "오딘은 누구인가"),
    ("feedback", "일하는 방식"),
    ("decision", "확정된 판정"),
    ("insight", "벼려낸 통찰"),
    ("reference", "참조 사실"),
    ("note", "메모"),
)


# ── 동결 스냅샷 주입 — Heimdall 세션 생성 시 1회 ─────────────


def _snapshot_rows(d: str) -> list[tuple[str, str]]:
    """주입용 카탈로그 행 — (kind, row). 페이지 재검증(오염 제외) + 경계 무력화 + kind 화이트리스트.
    index.md와 별도(주입 안전용)이다.

    행에 kind를 적지 않는다 — 칸 머리글이 이미 말하므로 행마다 반복하면 그만큼 예산만 먹는다.
    정렬은 칸 안에서 updated 내림차순: 예산이 모자랄 때 알파벳순으로 자르면 무엇이 살아남는지가
    임의가 된다(슬러그 첫 글자가 운을 가른다). 최신이 먼저 살아야 잘림이 뜻을 갖는다."""
    rows: list[tuple[str, str, str]] = []
    # 오염 제외는 `clean_pages`가 이미 했다 — 회수와 같은 읽기·같은 판정을 나눠 쓴다.
    # 나눠 쓰기 전에는 이 함수가 `query` 직후에 같은 파일을 처음부터 다시 열고 위협 정규식을
    # 다시 돌렸다 (실측 26-08-02: 1,000페이지에서 읽기 2,000번·독립 218ms).
    for slug, (meta, body) in sorted(clean_pages(d).items(), key=lambda item: item[0]):
        title = _neutralize(meta.get("title", slug))
        rows.append((_kind(meta), str(meta.get("updated", "")), _row(title, _neutralize(_desc(meta, body)))))
    rows.sort(key=lambda r: (r[1], r[2]), reverse=True)
    return [(kind, row) for kind, _updated, row in rows]


def _section(kind: str, label: str, rows: list[str], budget: int) -> str:
    """칸 하나 렌더 — 머리글에 사용률을 적는다. 빈 칸·예산 0은 빈 문자열.

    사용률을 100% 로 깎지 않는다: 저장은 무제한이라 칸은 실제로 넘칠 수 있고, `143%`라고
    적혀 있어야 모델이 그 칸을 통합하자고 먼저 말한다. 계기가 거짓말하면 계기가 아니다.

    `budget` 이 세는 것은 **행뿐**이다 — 머리글은 계기판이라 예산 밖이고, 반환값은 그만큼
    `budget` 을 넘는다. 이 자리에서 블록 상한을 기대하면 안 된다 (`snapshot_note` 참조)."""
    if budget <= 0 or not rows:
        return ""
    full = sum(len(r) + 1 for r in rows)
    kept: list[str] = []
    used = 0
    for row in rows:
        if used + len(row) + 1 > budget:
            break
        kept.append(row)
        used += len(row) + 1
    if len(kept) < len(rows):  # 잘림 — 경고 한 줄도 예산 안에서 (자리 없으면 행을 물린다)
        while kept and used + len(_SNAPSHOT_WARN) + 1 > budget:
            used -= len(kept.pop()) + 1
        if not kept:
            return ""
        kept.append(_SNAPSHOT_WARN)
    if not kept:
        return ""
    pct = round(100 * full / budget)
    return f"## {label} `{kind}` [{pct}% — {full:,}/{budget:,} chars]\n" + "\n".join(kept)


def section_usage(d: str | None = None) -> list[tuple[str, int, int]]:
    """칸별 (kind, 실제 주입 문자수, 예산). 페이지가 없는 칸은 빼고 _SECTIONS 순서로.

    lint·대시보드가 "어느 칸이 꽉 찼나"를 묻는 유일한 통로다. 세는 대상은 주입 행이라
    잘림 여부와 무관하게 '원래 얼마인지'를 돌려준다 — 넘친 양을 알아야 통합 여부를 판단할 수 있다."""
    d = d or memory_dir()
    rows = _snapshot_rows(d)
    budgets = kind_budgets()
    usage: list[tuple[str, int, int]] = []
    for kind, _label in _SECTIONS:
        used = sum(len(r) + 1 for k, r in rows if k == kind)
        if used:
            usage.append((kind, used, budgets.get(kind, 0)))
    return usage


def _fit_total(prefix: str, body: str, suffix: str, budget: int) -> str:
    """총량 상한 — 조립된 블록을 뒤에서부터 잘라 예산 안에 넣는다 (구 index_budget_chars).

    뒤가 먼저 죽는 건 의도다: _SECTIONS가 값비싼 칸을 앞에 세워 뒀다."""
    lines = body.split("\n")
    truncated = False
    while lines:
        while lines and lines[-1].startswith("## "):  # 행 없는 머리글은 계기가 아니라 껍데기
            lines.pop()
            truncated = True
        if not lines:
            break
        candidate = [*lines, _SNAPSHOT_WARN] if truncated else lines
        text = prefix + "\n".join(candidate) + suffix
        if len(text) <= budget:
            return text
        lines.pop()
        truncated = True
    warned = prefix + _SNAPSHOT_WARN + suffix
    return warned if len(warned) <= budget else ""


def snapshot_note(d: str | None = None) -> str:
    """세션 프롬프트 주입분 — 카탈로그를 부분(kind)별 예산 안에서 동결. 페이지 없으면 빈 문자열.

    칸을 나누는 이유는 예산이 아니라 굶주림이다. 총량 하나면 수가 많은 칸(reference)이
    값비싼 칸(user·feedback)을 밀어내는데, 사람이 같은 말을 반복하지 않게 만드는 건 뒤쪽이다.
    칸마다 상한을 주면 어느 칸도 굶지 않는다.

    **`INDEX_BUDGET` 은 블록 상한이 아니다.** 이름이 "블록이 이보다 안 커진다"로 읽히지만
    실제로는 `KIND_BUDGETS` 의 합이고, 그 예산은 칸마다 **행에만** 걸린다. 예산 밖에 남는 것:
    prefix 90자 + suffix 18자 + 칸 머리글 6줄 282자 + 칸 사이 개행 5자 = **395자**. 그래서 여섯
    칸이 다 찬 블록은 `INDEX_BUDGET` 을 넘는다 (26-08-03 실측: 611페이지에서 9,201자 vs 예산
    9,200자). 의도된 설계다 — 계기판을 예산에서 빼야 "737%" 같은 넘침 표시가 자기 자리를
    잃지 않는다. 진짜 블록 상한은 설정 `index_budget_chars` 를 켰을 때만 생기고, 그때는
    `_fit_total` 이 prefix·suffix 까지 포함해 자른다.

    "동결" 계약 = Heimdall 인스턴스 수명. self.identity에 1회 결합 후 세션 중 불변
    (KV 캐시 보존). /lagom 등 Heimdall 재생성 경로에서만 재렌더된다."""
    try:
        if not inject_enabled():  # 킬스위치 (2차 리뷰 ⑦) — off 면 어느 provider 로도 전송 없음
            return ""
        d = d or memory_dir()
        rows = _snapshot_rows(d)
        if not rows:
            return ""
        budgets = kind_budgets()
        prefix = (
            '\n\n<memory-context scope="personal">\n'
            "개인 메모리 카탈로그 (힌트 — 완료 증거 아님). 상세는 asgard memory query.\n"
        )
        suffix = "\n</memory-context>"
        sections = [
            block
            for kind, label in _SECTIONS
            if (block := _section(kind, label, [r for k, r in rows if k == kind], budgets.get(kind, 0)))
        ]
        if not sections:
            return ""
        body = "\n".join(sections)
        total = index_budget()
        if total is not None:
            return _fit_total(prefix, body, suffix, total)
        return prefix + body + suffix
    except Exception:
        return ""  # fail-open — 메모리 불능이 세션을 막지 않는다
