"""k6 부하 대상 — 실제 출하 경로(memory dashboard `/api/search`)를 합성 코퍼스 위에 띄운다.

왜 shim 을 안 만드는가: shim 의 지연은 shim 의 성질이지 제품의 성질이 아니다. 여기서 재는
핸들러는 `asgard memory dashboard` 가 실제로 내보내는 그 핸들러다.

왜 합성 코퍼스인가: 개인 메모리는 사람마다 다르고 사적이라 남이 재현할 수 없다. 형상을
코드로 고정해야 "같은 조건에서 다시 재기"가 성립한다. 두 프로파일이 서로 다른 것을 잰다:

  short — 정상 개인 메모리 (페이지 ~300자). 리랭크 길이 게이트가 전부 걸러낸다.
  long  — 대화 로그처럼 자란 페이지 (~12000자). 리랭크가 실제로 돈다.

`--rerank off` 로 같은 코퍼스에서 2단계만 꺼서 리랭크 비용을 귀속시킬 수 있다.

실행:
    .venv/bin/python benchmarks/latency/server.py --profile long --port 8792
    k6 run -e BASE=http://127.0.0.1:8792 -e PROFILE=long benchmarks/latency/load.js
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

TOPICS = [
    ("배포 절차", "금요일 배포를 피하고 배포 전에 테스트를 전부 돌린다"),
    ("커밋 규약", "커밋 메시지는 gitmoji 를 붙이고 사건 단위로 나눈다"),
    ("문서 위치", "문서는 저장소가 아니라 Linear 에 둔다"),
    ("테스트 실행", "uv run pytest 로 테스트를 실행한다"),
    ("리뷰 습관", "리뷰는 작은 diff 단위로 받고 큰 변경은 쪼갠다"),
    ("에디터 설정", "에디터는 vim 키바인딩을 쓰고 자동 저장을 끈다"),
    ("빌드 파이프라인", "CI 는 lint 와 타입 검사를 통과해야 병합된다"),
    ("데이터베이스", "마이그레이션은 항상 되돌릴 수 있게 작성한다"),
    ("보안 원칙", "비밀값은 저장소에 두지 않고 환경 변수로 넣는다"),
    ("회의 방식", "회의는 문서를 먼저 읽고 시작한다"),
    ("deployment policy", "avoid friday deploys and run the full suite first"),
    ("commit convention", "commit messages carry gitmoji and split by event"),
]

FILLER = (
    "이 문단은 페이지를 대화 로그 길이로 늘리기 위한 채움말이다. 실제 세션 기록은 요청과 "
    "응답이 번갈아 쌓이며 수천 자로 자란다. 그 안에서 답이 든 한 문장은 나머지에 묻히고, "
    "그래서 페이지 하나에 벡터 하나를 매기면 희석이 생긴다. "
    "The same dilution happens in English transcripts that grow to thousands of characters. "
)


def build(profile: str, pages: int) -> str:
    """합성 코퍼스 — 씨앗 고정이라 같은 인자면 같은 코퍼스가 나온다."""
    from asgard import memory

    d = tempfile.mkdtemp(prefix=f"asgard-latency-{profile}-")
    os.environ["ASGARD_MEMORY_DIR"] = d
    memory.ensure_home(d)
    rng = random.Random(20260728)
    target = 300 if profile == "short" else 12000
    for i in range(pages):
        title, fact = TOPICS[i % len(TOPICS)]
        body = f"오딘은 {fact}. (기록 {i})\n\n"
        while len(body) < target:
            body += FILLER if profile == "long" else "부연 설명 한 줄. "
        meta = {
            "title": f"{title} {i}",
            "kind": rng.choice(["user", "feedback", "decision", "note"]),
            "created": memory._today(),
            "updated": memory._today(),
        }
        memory._atomic_write(memory._page_path(d, memory.slugify(f"{title}-{i}")), memory.render_page(meta, body))
    memory.reindex(d)
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["short", "long"], default="short")
    ap.add_argument("--pages", type=int, default=100)
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--rerank", choices=["on", "off"], default="on")
    args = ap.parse_args()

    os.environ.setdefault("ASGARD_MEMORY_SEMANTIC", "on")
    d = build(args.profile, args.pages)

    os.environ["ASGARD_MEMORY_RERANK"] = args.rerank  # 제품의 정식 스위치 — 몽키패치 아님

    from asgard import memory
    from asgard.commands.memory_dashboard.server import _bind

    # 워밍업 — 임베더 적재와 첫 인덱스 접근은 정상 상태가 아니다. 측정 밖으로 뺀다.
    for _ in range(3):
        memory.query("배포", k=5, d=d, track=False)

    httpd = _bind("127.0.0.1", args.port)
    chars = sum(len(pg[1]) for pg in (memory._read(d, s) for s in memory._pages(d)) if pg)
    print(
        f"READY port={httpd.server_address[1]} profile={args.profile} rerank={args.rerank} "
        f"pages={args.pages} chars={chars} dir={d}",
        flush=True,
    )
    try:
        httpd.serve_forever()
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
