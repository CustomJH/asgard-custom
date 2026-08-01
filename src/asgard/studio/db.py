"""스튜디오 전용 SQLite — 팀·프로젝트·티켓의 **정본** 자리.

왜 파일을 하나 더 두는가 (다른 저장소 점검 결과):

  · `.asgard/studio/tasks.jsonl`은 실행 **이력**이다. 최근 200건만 남기고 매번 통째로 다시
    쓴다 — 오래된 줄은 스스로 사라지는 것이 계약이다. 티켓은 반대다: 3개월 전 백로그가
    조용히 없어지면 그건 저장소가 아니라 유실이다.
  · 기획(`plans.json`)은 계획 한 덩어리를 revision으로 **통째 교체**한다. 티켓은
    글쓴이가 여럿이다(사람이 보드에서 · 에이전트가 툴로 · CLI로). 통짜 교체는 마지막에 쓴
    사람만 살아남고 나머지 수정은 소리 없이 사라진다.
  · 그리고 티켓은 **질의**가 일이다: 상태·담당·라벨·주기로 걸러 정렬하고, 번호는 단조
    증가해야 하며(같은 번호를 두 번 발급하면 티켓이 아니다), 열린 건수를 매번 세야 한다.
    JSON 통짜 읽기로 이걸 하면 파일 크기가 곧 화면 지연이 된다.

**경계는 폴더가 아니라 워크스페이스다.**

여태 이 저장소는 `<프로젝트>/.asgard/studio/studio.db` — 폴더마다 하나였다. 그래서 폴더를
옮기면 보드가 통째로 갈렸고, "지금 뭘 해야 하지"에 답하려면 **먼저 어느 폴더를 열지 알아야**
했다. 일감은 그렇게 있지 않다: 리팩터링 하나가 저장소 셋을 건드리고, 기획은 코드가 아직
없는 데서 시작한다. Linear가 워크스페이스 아래 팀을 두는 이유가 그거다.

그래서 자리를 하나로 모은다 — `<에이전트 홈>/studio/workspace.db` (`ASGARD_STUDIO_HOME`으로
옮길 수 있다. 기획도 같은 자리에 있다 — `settings.workspace_home()`). 폴더는 사라지지 않고
**팀으로 들어올 수 있다**: 번호(`NOR-12`)는 그 팀의 것이고, 팀은 폴더 없이도 서며, 프로젝트는
팀을 가로지른다.

**폴더는 스스로 팀이 되지 않는다.** 결속은 사람이 건다(`bind_root`). 결속 없는 자리에서 적은
일감은 워크스페이스의 기본 팀이 받는다 — 폴더마다 팀이 저절로 서면, 저장소 다섯 곳을 오간
사람은 고른 적 없는 팀 다섯과 번호 다섯 갈래를 갖게 되고 그게 곧 "티켓이 프로젝트에 매였다"다.
같은 이유로 **읽기의 기본은 워크스페이스 전체**다: 폴더는 거르는 값이지 경계가 아니다.

  워크스페이스 ── 팀 ── 티켓            (티켓은 팀 하나에만 속한다 = 번호의 주인)
        │          └─ 워크플로 상태 · 사이클 · 트리아지 · 라벨
        ├─ 프로젝트 ── 마일스톤          (프로젝트는 팀을 가로지른다)
        └─ 이니셔티브 ── 프로젝트 묶음

**폴더 ↔ 팀 결속은 양쪽에 적는다.** 워크스페이스의 `team_roots`와 저장소 안의
`.asgard/studio/team.json`. 하나만 두면 각각 다른 방식으로 끊긴다 — 표만 두면 폴더를 옮겼을 때
결속을 잃고, 파일만 두면 폴더를 지웠을 때 워크스페이스가 그 팀의 출신을 모른다.

**커밋 대상이 아니다.** SQLite는 바이너리라 두 사람이 같은 날 티켓을 만지면 합칠 방법이 없다.
팀이 공유해야 하는 일감은 Linear 같은 서버가 나르고, 이 워크스페이스는 **이 기계에서 일하는
사람의 작업 목록**이다.

**파생 인덱스와 계약이 다르다.** `episodes.db`·`memory/index.py`는 손상되면 지우고 다시
만든다 — 원문에서 재생성되니까. 여기 든 것은 사람이 적은 원문이라 재생성할 곳이 없다.
그래서 손상은 **StoreError로 올린다**: 조용히 새 파일을 만들면 사용자는 티켓이 0개인 보드를
보고 "비었다"고 읽는다. 잃은 것을 잃었다고 말하는 편이 낫다.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import threading
from collections.abc import Iterator

from .. import errors

SCHEMA_VERSION = 2
# 자리를 옮기는 환경변수. 정본은 `settings.WORKSPACE_HOME_ENV` 다 — 기획도 같은 문을 본다.
STUDIO_HOME_ENV = "ASGARD_STUDIO_HOME"
STORE_DIR = os.path.join(".asgard", "studio")  # 저장소 안의 결속 파일 자리 (레거시 DB도 여기)
DB_FILE = "studio.db"  # 레거시 — 폴더마다 하나이던 시절
WORKSPACE_FILE = "workspace.db"
BIND_FILE = "team.json"

# 쓰기는 프로세스 안에서 직렬화한다. 프로세스 **사이**의 경합은 WAL + busy_timeout이 받는다
# (스튜디오 서버가 떠 있는 채로 `asgard ticket`을 치는 것이 정상 사용이다).
_WRITE_LOCK = threading.Lock()
_BUSY_TIMEOUT_MS = 10_000


class StoreError(errors.Unavailable, RuntimeError):
    """저장소를 열 수 없다 — 정본이라 조용히 새로 만들지 않는다."""

    code = "store_unavailable"


# ── 자리 ───────────────────────────────────────────────────────────────────────


def studio_home() -> str:
    """워크스페이스가 사는 곳. 환경변수로 옮길 수 있어야 테스트가 사용자의 보드를 안 더럽힌다.

    기준은 **에이전트 홈**이다(`~/.asgard`, 에인헤랴르 프로파일이면 그 홈): 일감은 그 에이전트와
    같이 일하는 사람의 것이라, 프로파일을 갈아 끼우면 보드도 같이 갈리는 편이 덜 놀랍다.

    자리를 고르는 규칙은 `settings.workspace_home()`이 소유한다 — 기획(`plan.store`)이 같은
    자리에 살아야 하고, 둘이 각자 조립하면 언젠가 한쪽만 옮겨진다."""
    from ..settings import workspace_home

    return workspace_home()


def workspace_path() -> str:
    return os.path.join(studio_home(), WORKSPACE_FILE)


def store_dir(root: str) -> str:
    """저장소 안에서 스튜디오가 쓰는 자리 — 이제 결속 파일 하나뿐이다."""
    return os.path.join(os.path.abspath(root), STORE_DIR)


def bind_path(root: str) -> str:
    return os.path.join(store_dir(root), BIND_FILE)


def legacy_db_path(root: str) -> str:
    """폴더마다 보드가 하나이던 시절의 파일. 읽기 전용으로만 연다 — 반입의 원본이다."""
    return os.path.join(store_dir(root), DB_FILE)


def db_path(root: str | None = None) -> str:
    """이 손이 쓸 저장소. root를 줘도 답은 워크스페이스다 — 경계가 폴더가 아니기 때문이다.

    (인자를 남겨 둔 이유는 호출부의 뜻이 "이 폴더의 일감"이어서다. 그 뜻은 이제 **팀**이
    받는다: 어느 팀을 볼지는 root가 정하고, 어디에 적을지는 워크스페이스가 정한다.)"""
    return workspace_path()


def exists(root: str | None = None) -> bool:
    return os.path.isfile(workspace_path())


def read_bind(root: str) -> dict:
    """이 저장소가 어느 팀에 매여 있는가. 없으면 빈 dict — 아직 안 쓴 폴더다."""
    try:
        with open(bind_path(root), encoding="utf-8") as handle:
            found = json.load(handle)
    except OSError, ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def write_bind(root: str, team_id: str, key: str) -> bool:
    """결속을 저장소 안에도 적는다 — 폴더를 옮겨도 번호가 안 갈리는 근거가 이 파일이다.

    **쓰기 경로에서만 부른다.** 읽기가 파일을 만들면, 창을 열어 본 것만으로 남의 리포에
    `.asgard/studio/`가 생긴다."""
    directory = store_dir(root)
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        with open(bind_path(root), "w", encoding="utf-8") as handle:
            json.dump({"team": team_id, "key": key}, handle, ensure_ascii=False, indent=1)
        return True
    except OSError:
        return False


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS meta(
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    # ── 팀 — 번호의 주인이자 워크플로·사이클·트리아지의 단위 ──────────────────────
    """
    CREATE TABLE IF NOT EXISTS teams(
        id             TEXT PRIMARY KEY,
        key            TEXT NOT NULL UNIQUE,
        name           TEXT NOT NULL,
        description    TEXT NOT NULL DEFAULT '',
        color          TEXT NOT NULL DEFAULT 'gold',
        seq            INTEGER NOT NULL DEFAULT 0,
        triage         INTEGER NOT NULL DEFAULT 0,
        estimates      TEXT    NOT NULL DEFAULT '',
        cycle_weeks    INTEGER NOT NULL DEFAULT 0,
        cycle_cooldown INTEGER NOT NULL DEFAULT 0,
        default_status TEXT    NOT NULL DEFAULT 'backlog',
        created_at     REAL NOT NULL,
        archived_at    REAL
    )
    """,
    # 폴더 ↔ 팀. 한 팀이 저장소 여럿을 들 수 있다(모노레포를 쪼개 열거나, 서비스가 갈릴 때).
    """
    CREATE TABLE IF NOT EXISTS team_roots(
        root       TEXT PRIMARY KEY,
        team_id    TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
        created_at REAL NOT NULL
    )
    """,
    # 팀별 워크플로 상태. Linear와 같은 계약: 이름은 팀이 짓고 **범주는 다섯**으로 고정이다
    # (backlog·unstarted·started·completed·canceled). 범주가 열려 있으면 "열린 건수"를 셀 수 없다.
    """
    CREATE TABLE IF NOT EXISTS states(
        id         TEXT PRIMARY KEY,
        team_id    TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
        slug       TEXT NOT NULL,
        name       TEXT NOT NULL,
        type       TEXT NOT NULL,
        color      TEXT NOT NULL DEFAULT 'slate',
        position   REAL NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        UNIQUE(team_id, slug)
    )
    """,
    # ── 이니셔티브 · 프로젝트 · 마일스톤 — 팀을 가로지르는 축 ─────────────────────
    """
    CREATE TABLE IF NOT EXISTS initiatives(
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        owner       TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'planned',
        priority    INTEGER NOT NULL DEFAULT 0,
        target_at   REAL,
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL,
        archived_at REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS projects(
        id            TEXT PRIMARY KEY,
        name          TEXT NOT NULL,
        description   TEXT NOT NULL DEFAULT '',
        icon          TEXT NOT NULL DEFAULT '',
        color         TEXT NOT NULL DEFAULT 'gold',
        lead          TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'planned',
        priority      INTEGER NOT NULL DEFAULT 0,
        health        TEXT NOT NULL DEFAULT '',
        initiative_id TEXT REFERENCES initiatives(id) ON DELETE SET NULL,
        starts_at     REAL,
        target_at     REAL,
        created_at    REAL NOT NULL,
        updated_at    REAL NOT NULL,
        completed_at  REAL,
        canceled_at   REAL,
        archived_at   REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_teams(
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        team_id    TEXT NOT NULL REFERENCES teams(id)    ON DELETE CASCADE,
        PRIMARY KEY(project_id, team_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_members(
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        member     TEXT NOT NULL,
        PRIMARY KEY(project_id, member)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_labels(
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        label_id   TEXT NOT NULL REFERENCES labels(id)   ON DELETE CASCADE,
        PRIMARY KEY(project_id, label_id)
    )
    """,
    # 자료 — 프로젝트가 기대는 바깥의 것들(문서 링크·디자인·대시보드). Linear의 Resources.
    # 본문(description)과 갈라 두는 이유: 링크는 **목록**이라 순서와 제목이 따로 필요하고,
    # 문서 한가운데 박아 두면 "이 프로젝트가 무엇에 기대고 있나"를 훑을 수 없다.
    """
    CREATE TABLE IF NOT EXISTS project_resources(
        id         TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        title      TEXT NOT NULL,
        url        TEXT NOT NULL DEFAULT '',
        kind       TEXT NOT NULL DEFAULT 'link',
        position   REAL NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS milestones(
        id           TEXT PRIMARY KEY,
        project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name         TEXT NOT NULL,
        description  TEXT NOT NULL DEFAULT '',
        target_at    REAL,
        position     REAL NOT NULL DEFAULT 0,
        created_at   REAL NOT NULL,
        completed_at REAL
    )
    """,
    # 프로젝트 업데이트 — 진행 보고. 건강도(on_track/at_risk/off_track)는 사람이 적는다:
    # 진척률에서 자동으로 뽑으면 '늦고 있지만 괜찮은'과 '빠르지만 틀린'을 구분 못 한다.
    """
    CREATE TABLE IF NOT EXISTS project_updates(
        id         TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        author     TEXT NOT NULL DEFAULT '',
        health     TEXT NOT NULL DEFAULT '',
        body       TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """,
    # ── 사이클 — 팀별 번호 ────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS cycles(
        id         TEXT PRIMARY KEY,
        team_id    TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
        number     INTEGER NOT NULL,
        name       TEXT    NOT NULL DEFAULT '',
        starts_at  REAL,
        ends_at    REAL,
        closed_at  REAL,
        created_at REAL    NOT NULL,
        UNIQUE(team_id, number)
    )
    """,
    # 라벨 — team_id가 비면 워크스페이스 공용. group_name은 Linear의 라벨 그룹.
    """
    CREATE TABLE IF NOT EXISTS labels(
        id         TEXT PRIMARY KEY,
        team_id    TEXT REFERENCES teams(id) ON DELETE CASCADE,
        group_name TEXT NOT NULL DEFAULT '',
        name       TEXT NOT NULL,
        color      TEXT NOT NULL DEFAULT 'slate',
        created_at REAL NOT NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS labels_scope ON labels(IFNULL(team_id,''), name)",
    # ── 티켓 ──────────────────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS tickets(
        id           TEXT    PRIMARY KEY,
        key          TEXT    NOT NULL UNIQUE,
        seq          INTEGER NOT NULL,
        team_id      TEXT    REFERENCES teams(id) ON DELETE CASCADE,
        title        TEXT    NOT NULL,
        body         TEXT    NOT NULL DEFAULT '',
        status       TEXT    NOT NULL,
        priority     INTEGER NOT NULL DEFAULT 0,
        estimate     INTEGER,
        assignee     TEXT    NOT NULL DEFAULT '',
        reporter     TEXT    NOT NULL DEFAULT '',
        source       TEXT    NOT NULL DEFAULT 'user',
        parent_id    TEXT    REFERENCES tickets(id) ON DELETE SET NULL,
        cycle_id     TEXT    REFERENCES cycles(id)  ON DELETE SET NULL,
        project_id   TEXT    REFERENCES projects(id) ON DELETE SET NULL,
        milestone_id TEXT    REFERENCES milestones(id) ON DELETE SET NULL,
        triage       INTEGER NOT NULL DEFAULT 0,
        snoozed_at   REAL,
        root         TEXT    NOT NULL DEFAULT '',
        plan_id      TEXT    NOT NULL DEFAULT '',
        plan_record  TEXT    NOT NULL DEFAULT '',
        task_id      TEXT    NOT NULL DEFAULT '',
        position     REAL    NOT NULL DEFAULT 0,
        created_at   REAL    NOT NULL,
        updated_at   REAL    NOT NULL,
        started_at   REAL,
        completed_at REAL,
        canceled_at  REAL,
        due_at       REAL,
        archived_at  REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ticket_labels(
        ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        label_id  TEXT NOT NULL REFERENCES labels(id)  ON DELETE CASCADE,
        PRIMARY KEY(ticket_id, label_id)
    )
    """,
    # 차단 관계 — 방향이 있다: source가 target을 막는다. 반대 방향은 질의로 읽는다.
    """
    CREATE TABLE IF NOT EXISTS ticket_links(
        source_id  TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        target_id  TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        kind       TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY(source_id, target_id, kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comments(
        id         TEXT PRIMARY KEY,
        ticket_id  TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        author     TEXT NOT NULL DEFAULT '',
        body       TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """,
    # 활동 — 누가 무엇을 무엇에서 무엇으로 바꿨는가. 티켓의 '왜 이렇게 됐나'는 여기에만 남는다.
    """
    CREATE TABLE IF NOT EXISTS activity(
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id  TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        actor      TEXT NOT NULL DEFAULT '',
        field      TEXT NOT NULL,
        before     TEXT NOT NULL DEFAULT '',
        after      TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL
    )
    """,
    # (저장 뷰 — Linear의 Views — 는 아직 없다. 표만 미리 세우면 아무도 안 쓰는 칸이
    #  스키마에 남아, 다음 사람이 그걸 계약으로 읽는다. 필터는 지금 질의 인자로만 산다.)
    "CREATE UNIQUE INDEX IF NOT EXISTS tickets_team_seq ON tickets(team_id, seq)",
    "CREATE INDEX IF NOT EXISTS tickets_status ON tickets(status, position)",
    "CREATE INDEX IF NOT EXISTS tickets_parent ON tickets(parent_id)",
    "CREATE INDEX IF NOT EXISTS tickets_cycle  ON tickets(cycle_id)",
    "CREATE INDEX IF NOT EXISTS tickets_project ON tickets(project_id)",
    "CREATE INDEX IF NOT EXISTS tickets_triage ON tickets(triage, created_at)",
    "CREATE INDEX IF NOT EXISTS tickets_updated ON tickets(updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS comments_ticket ON comments(ticket_id, created_at)",
    "CREATE INDEX IF NOT EXISTS activity_ticket ON activity(ticket_id, id)",
    "CREATE INDEX IF NOT EXISTS links_target ON ticket_links(target_id)",
    "CREATE INDEX IF NOT EXISTS states_team ON states(team_id, position)",
    "CREATE INDEX IF NOT EXISTS cycles_team ON cycles(team_id, number DESC)",
    "CREATE INDEX IF NOT EXISTS milestones_project ON milestones(project_id, position)",
    "CREATE INDEX IF NOT EXISTS resources_project ON project_resources(project_id, position)",
)

# v1 → v2로 올릴 때 tickets에 붙는 칸. ALTER는 되돌릴 수 없으니 **더하기만** 한다.
_V2_TICKET_COLUMNS = (
    ("team_id", "TEXT"),
    ("project_id", "TEXT"),
    ("milestone_id", "TEXT"),
    ("triage", "INTEGER NOT NULL DEFAULT 0"),
    ("snoozed_at", "REAL"),
    ("root", "TEXT NOT NULL DEFAULT ''"),
    ("archived_at", "REAL"),
)
_V2_CYCLE_COLUMNS = (("team_id", "TEXT"),)
_V2_LABEL_COLUMNS = (("team_id", "TEXT"), ("group_name", "TEXT NOT NULL DEFAULT ''"))


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.DatabaseError:
        return set()


def _add_columns(conn: sqlite3.Connection, table: str, wanted: tuple[tuple[str, str], ...]) -> None:
    if not _columns(conn, table):
        return  # 표가 아직 없다 — 스키마가 곧 만든다
    have = _columns(conn, table)
    for name, decl in wanted:
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA:
        conn.execute(statement)


def _migrate(conn: sqlite3.Connection) -> None:
    """스키마를 현재 판으로 올린다.

    판 번호는 meta에 든다. 파일을 지우고 다시 만드는 길은 정본에는 없다 — 칸을 더하고,
    되돌릴 수 없는 변경은 안 한다.

    meta부터 세우고 판을 읽는다: 판을 먼저 읽으면 **처음 만드는 파일에서 없는 표를 묻게 되고**,
    그 OperationalError가 위에서 '손상'으로 읽힌다(첫 실행이 곧 고장이 된다)."""
    conn.execute(_SCHEMA[0])
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
    try:
        found = int(row["value"]) if row else 0
    except TypeError, ValueError:
        found = 0
    if found > SCHEMA_VERSION:
        raise StoreError(
            f"the studio workspace was written by a newer Asgard "
            f"(schema {found} > {SCHEMA_VERSION}); upgrade Asgard to open it"
        )
    if found and found < 2:
        # 폴더 하나짜리 보드를 그 자리에서 올리는 길. 워크스페이스는 처음부터 v2라 여기 안 온다.
        _add_columns(conn, "tickets", _V2_TICKET_COLUMNS)
        _add_columns(conn, "cycles", _V2_CYCLE_COLUMNS)
        _add_columns(conn, "labels", _V2_LABEL_COLUMNS)
    _apply_schema(conn)
    if found != SCHEMA_VERSION:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )


def _open(path: str) -> sqlite3.Connection:
    directory = os.path.dirname(path)
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
    except OSError as exc:
        raise StoreError(f"cannot create the studio store directory: {exc}") from exc
    try:
        conn = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_MS / 1000)
    except sqlite3.Error as exc:
        raise StoreError(f"cannot open the studio store: {exc}") from exc
    conn.row_factory = sqlite3.Row
    try:
        # WAL: 보드를 읽는 중에도 에이전트가 티켓을 발급할 수 있어야 한다(읽기가 쓰기를 안 막는다).
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        with conn:
            _migrate(conn)
    except StoreError:
        conn.close()
        raise
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise StoreError(f"the studio store is unreadable and was left untouched: {exc}") from exc
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)  # sqlite 기본 0644 — 일감도 소유자 전용
    return conn


def connect(root: str | None = None) -> sqlite3.Connection:
    """워크스페이스를 연다. 없으면 만든다.

    호출자는 반드시 닫는다 — `reading()`/`writing()`을 쓰면 저절로 닫힌다."""
    return _open(workspace_path())


def open_legacy(root: str) -> sqlite3.Connection | None:
    """폴더 하나짜리 옛 보드를 **있는 그대로** 연다 — 반입의 원본이라 스키마를 안 건드린다."""
    path = legacy_db_path(root)
    if not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=_BUSY_TIMEOUT_MS / 1000)
    except sqlite3.Error as exc:
        raise StoreError(f"cannot open the legacy studio store: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


@contextlib.contextmanager
def reading(root: str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def writing(root: str | None = None) -> Iterator[sqlite3.Connection]:
    """한 건의 변경을 한 트랜잭션으로 — 예외가 나면 아무것도 남기지 않는다."""
    with _WRITE_LOCK:
        conn = connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()


def meta_get(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
