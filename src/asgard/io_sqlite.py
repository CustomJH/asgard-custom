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

import contextlib
import os
import sqlite3
import time
from collections.abc import Iterator

# studio/db.py·orchestration/store.py 가 이미 쓰던 값. 세 자리가 서로 다르면 어느 쪽이 정본인지
# 물어야 하고, 물어야 하는 값은 계약이 아니다.
BUSY_TIMEOUT_MS = 10_000
# WAL 전환 재시도 — 전환은 밀리초로 끝나므로 짧게 여러 번이 길게 한 번보다 낫다.
_WAL_TRIES = 20
_WAL_BACKOFF_S = 0.01


def connect(path: str) -> sqlite3.Connection:
    """WAL 과 busy_timeout 을 건 연결. 부모 디렉터리는 호출자가 이미 만들어 둔다.

    `busy_timeout` 이 먼저다 — 그 값은 이 연결이 뒤에 치는 모든 쓰기가 쓴다. WAL 전환만은 그
    값을 못 쓰고(`_enable_wal` 참고), 그래서 전환은 이 함수에서 유일하게 실패해도 되는 문장이다.

    나머지 예외는 삼키지 않는다 — 손상 파일 판정(`sqlite3.DatabaseError` 의 errorcode)이 호출자
    몫이라 그 예외가 그대로 올라가야 한다. 대신 열린 핸들은 여기서 닫는다: 예외와 함께 반쯤
    열린 연결이 호출자에게 가면 그것을 닫을 사람이 없다.
    """
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        _enable_wal(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def _enable_wal(conn: sqlite3.Connection) -> None:
    """WAL 로 바꾼다. 못 바꿔도 연결은 살린다 — 이 함수가 지키는 것은 모드가 아니라 연결이다.

    저널 모드 변경은 `busy_timeout` 을 안 쓴다. 다른 연결이 그 파일을 붙들고 있으면 SQLite 는
    busy handler 를 부르지 않고 즉시 SQLITE_BUSY 를 낸다. 같은 파일을 처음 여는 스레드가
    여럿이면 그중 하나만 전환에 성공하고, 나머지에서 이 예외를 올리면 그 세션의 쓰기가 통째로
    사라진다 — 26-08-06 실측(`agent/evicted.archive`, 4스레드 × 25건)에서 12회 중 4회가 그렇게
    25건씩 잃었고, 호출부가 fail-open 이라 행 수가 준 것 말고는 아무 흔적이 없었다.

    전환은 밀리초로 끝나므로 짧게 여러 번 다시 친다. 그래도 안 되면 그대로 둔다: 먼저 전환한
    연결이 세워 둔 WAL 을 쓰거나, 아무도 못 세웠으면 기본 저널로 돈다. 둘 다 정확성은 같고
    동시성만 다르다. 잠금이 아닌 실패는 올린다 — 손상 파일이 조용히 지나가면 안 된다.
    """
    for attempt in range(_WAL_TRIES):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.DatabaseError as exc:
            # errorcode 로 가른다 — 메시지 부분일치는 로케일과 SQLite 판에 따라 달라지고, 이
            # 분기가 놓치면 손상 파일이 재시도 스무 번을 돌다 조용히 지나간다. 저장소의 다른
            # 네 자리(`project_memory/documents`·`memory/index`·`agent/episodes`·`agent/evicted`)도
            # 같은 축을 쓴다.
            if getattr(exc, "sqlite_errorcode", None) not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                raise
            if attempt < _WAL_TRIES - 1:
                time.sleep(_WAL_BACKOFF_S)


@contextlib.contextmanager
def writing(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """쓰기 트랜잭션 하나. `with conn:` 대신 이것을 쓴다 — 읽고 나서 쓰는 블록이라면 특히.

    `with conn:` 은 deferred 로 연다. 그러면 첫 SELECT 가 읽기 락으로 시작하고 첫 INSERT 에서
    쓰기로 승격하는데, 그 승격은 다른 writer 가 이미 쓰고 있으면 `busy_timeout` 을 **쓰지 않고**
    즉시 `database is locked` 다: 양쪽이 서로의 읽기 락을 붙든 채 기다리면 영영 안 풀리므로
    SQLite 는 기다리는 대신 바로 포기한다. 처음부터 쓰기 락을 요청하면(`BEGIN IMMEDIATE`) 그
    경합이 정상적인 대기가 되고 `busy_timeout` 이 덮는다.

    이 계약이 먼저 지키는 것은 값이다. `archive` 처럼 `max(seq)` 를 읽고 그 위에 쓰는 블록에서
    읽기를 락 밖에 두면 두 세션이 같은 top 을 보고 같은 seq 를 쓴다.

    26-08-06 에 이 자리를 immediate 로 바꾼 커밋(dd4ce1b8)은 "4스레드 × 25건에서 승격 실패로
    50건 유실"을 근거로 들었는데, 그 유실의 실제 자리는 승격이 아니라 `_enable_wal` 이었다.
    connect 를 고친 뒤에는 deferred 로 되돌려도 같은 부하에서 20회 무손실이다. 승격 경합은
    여전히 실재하지만(위 문단), 그 숫자가 그것을 재지는 않았다.

    읽기만 하는 블록에는 쓰지 않는다 — 그때는 쓰기 락이 남의 쓰기를 막을 뿐이다."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


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
