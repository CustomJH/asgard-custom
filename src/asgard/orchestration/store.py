"""오케스트레이션 SQLite — Run·Task·Dispatch·메시지·게이트의 정본 자리.

자리는 **프로젝트 안**이다(`<root>/.asgard/orchestration.db`). 스튜디오의 워크스페이스가
기계 전역(`<에이전트 홈>/studio/workspace.db`)인 것과 반대인데, 담는 것이 다르기 때문이다:
티켓은 사람이 저장소를 오가며 들고 다니는 일감이고, 여기 든 것은 **한 퀘스트가 도는 동안의
배차 상태**다. 퀘스트가 프로젝트에 매여 있으므로(`.asgard/quest/`) 그 배차도 같은 자리에 있어야
한다. `.gitignore` 의 `.asgard/*` 규칙이 이 파일을 이미 제외한다.

**파생 상태다.** 손상되면 지우고 다시 만든다 — 퀘스트 로그(`.asgard/quest/*.jsonl`)가 원문이고
이 DB 는 그 위에 세운 배차 장부다. 그래서 스튜디오 저장소와 달리 열기 실패를 StoreError 로
올리지 않고 fail-open 한다: 오케스트레이션이 안 서는 것이 Trinity 순환 자체를 막으면, 배차
장부를 얻으려다 작업을 잃는다.

쓰기는 프로세스 안에서 `_WRITE_LOCK` 으로 직렬화하고, 프로세스 사이의 경합은 WAL 과
busy_timeout 이 받는다 — wave 병렬 실행에서 워커 스레드 여럿이 같은 DB 에 완료 보고를 적는
것이 정상 사용이다. 조회는 락을 안 잡고 아무것도 안 쓴다: 스키마 판이 이미 맞으면
`_ensure_schema` 가 곧바로 돌아가고, 장부 파일이 아예 없으면 메모리 위의 빈 스키마로 붙는다.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
from collections.abc import Iterator

SCHEMA_VERSION = 1
DB_DIR = ".asgard"
DB_FILE = "orchestration.db"
STATE_ENV = "ASGARD_ORCHESTRATION_DB"  # 시험이 사용자의 배차 장부를 안 건드리게 하는 문

# 이 저장소의 재시도 상한(`trinity-policy.json` 의 ticket_runtime.max_attempts). Run 이 아니라
# meta 에 두는 이유는 배차와 정산이 서로 다른 호출자에서 오기 때문이다 — 배차는 장부(정책을
# 안다)가 열지만 정산은 워커의 완료 보고가 하고, 그쪽은 정책을 모른다. 두 자리가 다른 수를
# 보면 실제로는 다섯 번 돌았는데 장부에는 세 번만 남는다.
META_MAX_ATTEMPTS = "max_attempts"

_WRITE_LOCK = threading.Lock()
_BUSY_TIMEOUT_MS = 10_000

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS meta(
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    # Run — 이름 공간이자 코디네이터 우편함. quest_id 로 Trinity 퀘스트와 묶인다.
    """
    CREATE TABLE IF NOT EXISTS runs(
        id          TEXT PRIMARY KEY,
        objective   TEXT NOT NULL DEFAULT '',
        quest_id    TEXT NOT NULL DEFAULT '',
        coordinator TEXT NOT NULL DEFAULT '',
        shape       TEXT NOT NULL DEFAULT '',
        shape_why   TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'open',
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL,
        closed_at   REAL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS runs_quest ON runs(quest_id)
    """,
    # Task — 일감. deps 는 같은 Run 안의 task id 를 담은 JSON 배열이다.
    """
    CREATE TABLE IF NOT EXISTS tasks(
        id           TEXT PRIMARY KEY,
        run_id       TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        parent_id    TEXT,
        unit_id      TEXT NOT NULL DEFAULT '',
        spec         TEXT NOT NULL DEFAULT '',
        deps         TEXT NOT NULL DEFAULT '[]',
        status       TEXT NOT NULL DEFAULT 'pending',
        result       TEXT,
        attempts     INTEGER NOT NULL DEFAULT 0,
        created_at   REAL NOT NULL,
        updated_at   REAL NOT NULL,
        completed_at REAL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS tasks_run ON tasks(run_id, status)
    """,
    # Dispatch — Task 한 번의 시도. attempt 는 1 부터 세고, retry_of 는 직전 시도를 가리킨다.
    """
    CREATE TABLE IF NOT EXISTS dispatches(
        id             TEXT PRIMARY KEY,
        run_id         TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        task_id        TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        worker         TEXT NOT NULL DEFAULT '',
        role           TEXT NOT NULL DEFAULT '',
        agent          TEXT NOT NULL DEFAULT '',
        model          TEXT NOT NULL DEFAULT '',
        attempt        INTEGER NOT NULL DEFAULT 1,
        retry_of       TEXT,
        state          TEXT NOT NULL DEFAULT 'ready',
        outcome        TEXT,
        summary        TEXT NOT NULL DEFAULT '',
        files_modified TEXT NOT NULL DEFAULT '[]',
        created_at     REAL NOT NULL,
        updated_at     REAL NOT NULL,
        settled_at     REAL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS dispatches_task ON dispatches(task_id, state)
    """,
    # 메시지 — delivery_id 가 배달 묶음을 표시하고, acked_at 이 그 묶음의 소비를 표시한다.
    # 둘을 나눠 둔 이유는 재생(replay)이다: 묶었지만 ack 안 된 배달은 같은 내용으로 다시 나간다.
    """
    CREATE TABLE IF NOT EXISTS messages(
        id          TEXT PRIMARY KEY,
        run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        task_id     TEXT,
        dispatch_id TEXT,
        thread_id   TEXT NOT NULL DEFAULT '',
        sender      TEXT NOT NULL DEFAULT '',
        recipient   TEXT NOT NULL DEFAULT '',
        type        TEXT NOT NULL,
        subject     TEXT NOT NULL DEFAULT '',
        body        TEXT NOT NULL DEFAULT '',
        payload     TEXT NOT NULL DEFAULT '{}',
        priority    TEXT NOT NULL DEFAULT 'normal',
        outcome     TEXT,
        answer      TEXT,
        answered_at REAL,
        delivery_id TEXT,
        acked_at    REAL,
        created_at  REAL NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS messages_inbox ON messages(run_id, acked_at, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS messages_delivery ON messages(delivery_id)
    """,
    # 게이트 — 코디네이터가 DAG 를 멈추고 내리는 결정. 워커의 질문(`question` 메시지)과 다르다:
    # 저쪽은 워커가 막혀서 묻는 것이고, 이쪽은 코디네이터가 다음 갈래를 고르는 것이다.
    """
    CREATE TABLE IF NOT EXISTS gates(
        id          TEXT PRIMARY KEY,
        run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        task_id     TEXT,
        question    TEXT NOT NULL DEFAULT '',
        options     TEXT NOT NULL DEFAULT '[]',
        status      TEXT NOT NULL DEFAULT 'open',
        resolution  TEXT,
        created_at  REAL NOT NULL,
        resolved_at REAL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS gates_run ON gates(run_id, status)
    """,
)

# 유니크 제약은 따로 둔다. 이 DB 는 파생 상태라 이전 판으로 만들어진 파일이 이미 제약을 어기는
# 행을 갖고 있을 수 있는데, 그 파일을 아예 못 열게 하면 장부 하나 때문에 퀘스트가 안 열린다.
# 제약 생성 실패는 그 파일에만 제약이 없는 상태로 남기고 나머지는 그대로 쓴다.
_UNIQUE_INDEXES = (
    # 한 퀘스트에 열린 Run 은 하나뿐이다. `run_bind` 가 한 트랜잭션 안에서 조회 후 삽입하지만,
    # 그것만으로는 **다른 프로세스**의 동시 bind 를 막지 못한다(스튜디오가 떠 있는 채로 CLI 를
    # 치는 것이 정상 사용이다). Run 이 갈리면 같은 퀘스트의 Task 와 우편함이 둘로 나뉘어
    # 코디네이터가 반대쪽 완료 보고를 영영 못 본다.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS runs_one_open_per_quest
        ON runs(quest_id) WHERE quest_id != '' AND status = 'open'
    """,
    # 한 Run 에서 배정 단위 하나는 Task 하나다. 프로세스 재시작 후 같은 퀘스트를 이어 받으면
    # 장부가 메모리에 들고 있던 "이미 만든 단위" 목록이 비어 있어 같은 단위가 두 벌로 생기고,
    # 그러면 시도 횟수가 갈려 회로 차단이 영영 안 걸린다. 조건의 `parent_id IS NOT NULL` 이
    # **배정 단위만** 고르는 자리다 — 역할 턴 Task 는 부모가 없고, VERIFIER 처럼 한 퀘스트에서
    # 여러 번 도는 역할이 정상이라 유니크 대상이 아니다.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS tasks_one_per_unit
        ON tasks(run_id, unit_id) WHERE unit_id != '' AND parent_id IS NOT NULL
    """,
)


def db_path(root: str) -> str:
    """이 저장소의 배차 장부 자리. 환경변수가 있으면 그쪽이 우선한다."""
    override = os.environ.get(STATE_ENV)
    if override:
        return override
    return os.path.join(os.path.abspath(root), DB_DIR, DB_FILE)


def exists(root: str) -> bool:
    return os.path.isfile(db_path(root))


@contextlib.contextmanager
def connect(root: str, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    """스키마가 선 연결을 연다. 쓰기면 프로세스 안에서 직렬화한다.

    호출자는 커밋을 신경 쓰지 않는다 — 예외 없이 블록을 빠져나오면 커밋하고, 예외가 나면
    되돌린다.

    **조회는 없는 장부를 만들지 않는다.** 파일이 아직 없는데 읽으러 오면 메모리 위에 빈
    스키마를 세워 그쪽을 읽는다. `asgard siege` 같은 조회 명령이 디스크에 빈 DB 를 남기면
    "읽기 전용" 이라는 문서가 곧바로 거짓이 되고, 잘못된 디렉터리에서 친 조회가 그 자리에
    유령 장부를 만들어 다음 조회를 계속 속인다.
    """
    path = db_path(root)
    if write or os.path.isfile(path):
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    else:
        path = ":memory:"
    lock = _WRITE_LOCK if write else contextlib.nullcontext()
    with lock:
        conn = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA foreign_keys=ON")
            _ensure_schema(conn)
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """스키마 판이 이미 맞으면 아무것도 쓰지 않는다.

    판정을 `PRAGMA user_version` 으로 하는 것이 요점이다. 예전에는 매 연결이
    `CREATE TABLE IF NOT EXISTS` 와 meta upsert 를 돌렸는데, upsert 는 조회 경로에서도 쓰기
    트랜잭션을 여는 문장이다. 그래서 "읽기" 라고 적힌 연결이 `_WRITE_LOCK` 밖에서 쓰기 락을
    잡았고, 0.25초마다 도는 답 대기(`mail.wait_answer`)가 그만큼의 경합을 만들었다.
    """
    version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
    if version == SCHEMA_VERSION:
        return
    for statement in _SCHEMA:
        conn.execute(statement)
    for statement in _UNIQUE_INDEXES:
        try:
            conn.execute(statement)
        except sqlite3.IntegrityError:
            # 이전 판이 남긴 중복 행이 있는 파일이다. 제약 없이 열어 두는 편이 장부를 통째로
            # 못 쓰게 하는 것보다 싸다 — 이 DB 는 파생 상태라 지우고 다시 만들 수 있다.
            continue
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    """meta 한 칸을 읽는다. 없으면 기본값 — 없는 것은 실패가 아니다."""
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row is not None else default


def set_meta(root: str, key: str, value: str) -> None:
    """meta 한 칸을 적는다 — 이 저장소의 배차 정책처럼 Run 을 가로지르는 값의 자리."""
    with connect(root, write=True) as conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def reset(root: str) -> bool:
    """배차 장부를 지운다. 파생 상태라 지워도 퀘스트 로그는 남는다.

    Returns:
        지울 파일이 있었으면 True. 없었으면 False — 실패가 아니다.
    """
    path = db_path(root)
    removed = False
    for suffix in ("", "-wal", "-shm"):
        with contextlib.suppress(OSError):
            os.remove(path + suffix)
            removed = removed or not suffix
    return removed
