"""SQLite 접속 — 어떻게 여는가를 한 자리에 가둔다.

왜 만들었나: `sqlite3.connect` 를 부르는 자리가 여섯인데 journal_mode 와 busy_timeout 을 거는
곳은 `studio/db.py` 와 `orchestration/store.py` 둘뿐이었다. 나머지 넷은 파이썬 기본값으로
열렸고, 그 기본값은 `journal_mode=delete` · `busy_timeout=5000` 이다. delete 모드에서는 쓰는
연결이 읽는 연결까지 막으므로, 형제 워커가 6초짜리 쓰기 트랜잭션을 쥐고 있으면 읽으러 온
쪽은 5.16초를 기다린 뒤 `database is locked` 로 죽는다(실측 26-08-03). 넷 다 스키마 문장을
접속할 때마다 돌리기 때문에, 죽는 자리는 조회가 아니라 **연결을 여는 함수 자신**이었다.
그 넷의 호출자는 전부 fail-open 이라 죽음이 예외로 안 보이고 빈 결과로 보인다.

여는 계약만 여기 있다:
  - WAL — 읽기가 쓰기를 기다리지 않는다. 웨이브 병렬 실행에서 워커 스레드 여럿이 같은 DB 를
    쓰는 것이 정상 사용이므로(`orchestration/store.py` 의 독스트링), 읽기와 쓰기가 서로를
    막으면 그 정상 사용이 곧 고장이다.
  - busy_timeout — WAL 을 켜도 쓰기끼리는 한 번에 하나다. 남는 그 경합을 예외가 아니라
    대기로 받는다.

**손상 정책은 여기 없다.** 파생 인덱스는 손상되면 지우고 다시 만들고, 사람이 적은 원문은
예외로 올린다(`studio/db.py`). 그 차이는 담긴 것의 차이지 여는 방법의 차이가 아니다 — 무엇을
담았는지 아는 쪽이 깨졌을 때 어떻게 할지도 안다. 스키마·트랜잭션·row_factory 도 같은 이유로
호출자 몫이다. 이 모듈이 아는 것은 연결 하나를 여는 데까지다.
"""

from __future__ import annotations

import os
import sqlite3

# studio/db.py·orchestration/store.py 가 이미 쓰던 값. 세 자리가 서로 다르면 어느 쪽이 정본인지
# 물어야 하고, 물어야 하는 값은 계약이 아니다.
BUSY_TIMEOUT_MS = 10_000


def connect(path: str) -> sqlite3.Connection:
    """WAL 과 busy_timeout 을 건 연결. 부모 디렉터리는 호출자가 이미 만들어 둔다.

    순서가 뜻을 가진다. WAL 전환이 먼저인 이유는 그것이 옛 파일에 대해서는 쓰기이고, 파이썬
    기본 대기(5초)가 그 한 문장을 덮는 유일한 창이기 때문이다. busy_timeout 을 먼저 걸면 그
    창이 10초로 늘어나 실패해야 할 때 더 오래 매달린다. 전환이 한 번 끝나면 모드는 파일에
    남으므로 다음 연결부터 이 문장은 잠금이 필요 없다.

    예외는 삼키지 않는다 — 손상 파일 판정(`sqlite3.DatabaseError` 의 errorcode)이 호출자 몫이라
    그 예외가 그대로 올라가야 한다. 대신 열린 핸들은 여기서 닫는다: 예외와 함께 반쯤 열린
    연결이 호출자에게 가면 그것을 닫을 사람이 없다.
    """
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    except BaseException:
        conn.close()
        raise
    return conn


def remove(path: str) -> None:
    """DB 파일과 WAL 곁 파일(`-wal`·`-shm`)을 같이 지운다.

    WAL 을 켜면 저장소가 파일 하나가 아니다. 본체만 지우면 아직 체크포인트되지 않은 내용이
    `-wal` 에 남고, 지웠다고 믿은 쪽과 실제 남은 것이 갈린다. 파생 인덱스를 지우고 다시 짓는
    자리가 다섯인데 그때마다 파일 셋을 호출자가 세게 두지 않는다.

    없는 파일은 지운 것으로 친다 — 지우려는 쪽이 원한 상태가 이미 그것이다.
    """
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass  # 없거나 못 지우는 것 — 부르는 쪽이 원한 상태(그 파일이 없음)에 더 가까워졌다
