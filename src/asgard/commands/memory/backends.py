"""memory 커맨드 — 백엔드 연결과 시맨틱 레인. 결속·제공자·MCP 브리지·주기 작업."""

import json as _json
import os
import re
import uuid
from typing import NamedTuple

from ... import errors, memory, ui
from ._core import _emit, _guard


def _backend_options(values: list[str]) -> dict:
    options = {}
    for value in values:
        key, separator, raw = value.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ValueError(f"invalid backend option {value!r}; expected KEY=VALUE")
        if re.search(r"(?:secret|password|passwd|token|api[_-]?key|credential)", key, re.I):
            raise ValueError(f"backend option {key!r} looks secret; use an environment variable in the adapter")
        try:
            options[key] = _json.loads(raw)
        except Exception:
            options[key] = raw
    return options


def _bind_namespace(
    config: dict,
    pid: str,
    project_uid: str,
    binding_id: str,
    *,
    explicit_project_id: bool,
    claim: bool,
    adopt_existing: bool,
    json_out: bool,
) -> str:
    """backend 네임스페이스에 이 프로젝트의 소유 마커를 세우고 그 binding_id를 돌려준다.

    남의 뱅크에 얹히는 것을 막는 관문이다. 마커가 이미 있으면 신원이 같은지 보고, 없으면 비어
    있는지 센 뒤에 쓴다 — 데이터가 든 네임스페이스는 `--adopt-existing` 없이는 넘겨받지 않는다.
    쓴 뒤 다시 읽어 확인하는 것은 write가 성공을 보고하고도 반영되지 않는 게이트웨이 때문이다."""
    from ...project_memory_backends import ProjectMemoryBinding, get_backend

    backend = get_backend(config)
    try:
        readiness = backend.readiness()
        if readiness.status != "ready":
            raise ValueError(
                f"backend is not ready ({readiness.detail or readiness.status}); binding was not trusted or saved"
            )
        marker = backend.read_binding()
        if marker is not None:
            if marker.project_id != pid or marker.project_uid != project_uid:
                raise ValueError("selected project-memory namespace is already bound to a foreign project")
            if binding_id and marker.binding_id != binding_id:
                raise ValueError("selected project-memory namespace binding has drifted")
            if not binding_id and not adopt_existing:
                raise ValueError("existing bound namespace requires --adopt-existing for this project configuration")
            return marker.binding_id
        count = backend.namespace_document_count()
        if count > 0 and not adopt_existing:
            raise ValueError(
                f"unbound namespace already contains {count} document(s); use a new bank or --adopt-existing explicitly"
            )
        if count == 0 and explicit_project_id and not claim and not adopt_existing:
            # 빈 뱅크의 명시 이름은 곧 새 뱅크 개설 의사 — 별도 --claim을 요구하던 마찰 제거
            # (오딘 결정 26-07-23: connect 한 줄이면 아스가르드가 알아서). 데이터가 있는 뱅크의
            # 입양(--adopt-existing)만 명시 동의로 남긴다.
            if not json_out:
                ui.step(f"빈 네임스페이스 '{pid}' — 새 뱅크로 클레임")
        binding_id = binding_id or str(uuid.uuid4())
        marker = ProjectMemoryBinding(project_uid=project_uid, binding_id=binding_id, project_id=pid)
        result = backend.write_binding(marker)
        if not result.success:
            raise ValueError(result.error or "project-memory binding write was rejected")
        if backend.read_binding() != marker:
            raise ValueError("project-memory binding verification failed after write")
        return binding_id
    finally:
        backend.close()


def _uninjected_note(root: str) -> str:
    """등록한 뱅크가 이 저장소 세션 프롬프트에 안 들어가면 그 사실. 들어가거나 판정 불능이면 빈 문자열.

    connect 는 backend 도달성만 보고 성공을 찍는다. 그런데 뱅크를 실제로 프롬프트에 넣는 것은
    이 저장소의 memory-activate 배선이라, 배선 없는 저장소에 연결하면 등록은 되고 자동 회수는
    영영 0인 상태가 조용히 선다 (26-08-07 실측). 등록한 그 자리에서 말해야 다음 명령을 안다."""
    try:
        from ..doctor.memory import bank_uninjected_note

        return bank_uninjected_note(root)
    except Exception:
        return ""  # 진단 실패가 연결을 실패로 만들지는 않는다


def _connected_report(root: str, engine: str, project_id: str, config_path: str) -> None:
    """연결 성공의 사람 표면 — 등록됐다는 사실과 그게 세션 프롬프트에 들어가는지를 같은 화면에 놓는다."""
    ui.ok(f"connected: engine={engine} project_id={project_id} → {config_path} (커밋해서 팀과 공유)")
    if uninjected := _uninjected_note(root):
        ui.warn(uninjected)
        ui.step("asgard init --force 로 이 저장소에 메모리 배선을 깔면 프롬프트에 들어가요 (뱅크 설정은 그대로 남아요)")
    ui.step("팀원 1회 등록: claude mcp add --scope user asgard-memory -- asgard memory mcp")


def _first(*values: object) -> str:
    """여러 출처에서 오는 한 칸의 값 — 비어 있지 않은 첫 값, 없으면 빈 문자열."""
    for value in values:
        if text := str(value or "").strip():
            return text
    return ""


def _same_target(previous: dict, *, endpoint: str, engine: str, project_id: str) -> bool:
    """직전 설정이 지금 붙는 곳과 같은 엔진·엔드포인트·뱅크인가 — 결속을 물려받아도 되는 조건."""
    return (
        _first(previous.get("engine"), "hindsight").lower() == engine
        and _first(previous.get("endpoint"), previous.get("server")).rstrip("/") == endpoint.rstrip("/")
        and _first(previous.get("project_id"), previous.get("bank")) == project_id
    )


def _identity_in_history(root: str, *, has_identity: bool, recover_binding: bool, json_out: bool) -> dict:
    """git 이력이 든 신원 — `--recover-binding`을 받은 실행에서만 쓴다. 그 밖에는 늘 빈 dict.

    플래그는 "지금 적혀 있는 신원 말고 이력이 든 신원"이라는 말이므로, 이미 신원이 있어도 이력이
    우선한다. 그러지 않으면 엉뚱한 뱅크에 한 번 묶인 저장소는 영영 못 돌아온다 — "foreign project"
    거절을 만난 사람의 다음 수가 다른 뱅크에 새로 붙는 것이고, 그 순간 설정과 사이드카에 새 uid가
    적혀 조회가 거기서 멈추기 때문이다 (26-08-20 실측).

    플래그가 없으면 이 함수는 아무것도 안 정한다. 신원이 없을 때 이력에 되찾을 게 있다는 사실만
    화면에서 말하고 빈 dict를 돌려준다 — 못 찾는 플래그는 없는 플래그다."""
    from ... import memory_bridge

    if has_identity and not recover_binding:
        return {}
    in_history = memory_bridge.recover_binding_sidecar(root)
    if not in_history:
        return {}
    if recover_binding:
        if not json_out:
            uid = in_history.get("project_uid", "")
            ui.step(f"git 이력에서 소유권 신원을 되찾았어요 (project_uid={uid[:8]}…)")
        return in_history
    if not json_out:
        ui.warn("git 이력에 이 저장소가 쓰던 소유권 신원이 남아 있는데, 새 uid로 붙어요")
        ui.step("예전 뱅크로 돌아가려면 같은 명령을 `--recover-binding`으로 다시 실행하세요")
    return {}


class _ConnectIdentity(NamedTuple):
    """connect가 backend에 내밀 신원 — 누구인지(project_uid), 어느 뱅크인지(project_id), 어느 결속인지."""

    project_id: str
    project_uid: str
    binding_id: str
    explicit_project_id: bool
    recovered: dict  # git 이력에서 되찾은 사이드카 — 되찾은 게 없으면 빈 dict


def _connect_identity(
    root: str,
    previous: dict,
    project_id: str | None,
    *,
    endpoint: str,
    engine: str,
    recover_binding: bool,
    json_out: bool,
) -> _ConnectIdentity:
    """신원 순서 — `--recover-binding`이면 git 이력이 먼저, 아니면 설정 섹션 → 사이드카 → 새로 발급.

    소유권 신원은 설정 파일이 아니라 사이드카(.asgard/memory/binding.json)에 있다 — 설정 섹션만
    읽으면 재연결이 매번 새 project_uid를 발급하고, 서버의 기존 마커와 어긋나 자기 뱅크를
    "foreign"으로 거절한다. 그러면 timeout·endpoint 조정도, 설정 변경으로 무효화된 신뢰의
    재승인도 불가능해진다 — 그 무효화가 안내하는 수리 명령이 바로 이 connect 다 (26-07-26 실측).
    find_config는 이미 같은 사이드카를 병합한다 (단일 신원 출처).

    git 이력은 `--recover-binding`을 받았을 때만 읽고, 그때는 지금 적혀 있는 신원보다 앞선다
    (`_identity_in_history`). 기본값이 되찾기가 되면 조상 저장소를 지우고 새로 시작한 fork·clone이
    아무도 안 물어본 채 조상의 뱅크로 걸어 들어간다 — 되찾은 uid가 마커와 맞아 버리기 때문이다.
    그래서 플래그가 곧 동의 표면이고, 안 주면 순서도 값도 예전 그대로다.

    되찾은 값은 증거일 뿐 통행증이 아니다 — backend 마커와 대조하는 것은 여전히
    `_bind_namespace`이고, 어긋나면 거절이다."""
    from ... import memory_bridge

    sidecar = memory_bridge.read_binding_sidecar(root)
    uid = _first(previous.get("project_uid"), sidecar.get("project_uid"))
    recovered = _identity_in_history(root, has_identity=bool(uid), recover_binding=recover_binding, json_out=json_out)
    project_uid = recovered.get("project_uid") or uid or str(uuid.uuid4())
    if recovered:
        # 되찾기가 이긴 실행에서는 뱅크도 결속도 이력 것만 쓴다. 지금 적혀 있는 결속은 다른
        # 뱅크 것이라, 섞으면 uid는 이력이고 binding_id는 남의 뱅크가 되어 drift로 막힌다.
        pid = _first(project_id, recovered.get("project_id"))
    else:
        pid = _first(project_id, previous.get("project_id"), previous.get("bank"), sidecar.get("project_id"))
    if not pid:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(root)).strip("-.") or "project"
        pid = f"{slug}-{project_uid[:8]}"
    if recovered:
        # 이력이 적어 둔 뱅크 이름과 지금 붙는 뱅크가 같을 때만 binding_id도 물려받는다 —
        # 이름이 다르면 그 뱅크를 넘겨받겠다는 동의(--adopt-existing)를 따로 받는다.
        binding_id = recovered["binding_id"] if recovered.get("project_id") == pid else ""
    elif _same_target(previous, endpoint=endpoint, engine=engine, project_id=pid):
        binding_id = _first(previous.get("binding_id"), sidecar.get("binding_id"))
    else:
        binding_id = ""
    return _ConnectIdentity(pid, project_uid, binding_id, bool(_first(project_id)), recovered)


def run_connect(
    endpoint: str,
    project_id: str | None,
    *,
    engine: str = "hindsight",
    option_values: list[str] | None = None,
    claim: bool = False,
    adopt_existing: bool = False,
    recover_binding: bool = False,
    timeout: int | None = None,
    json_out: bool = False,
) -> int:
    """프로젝트를 선택된 shared-memory backend에 연결하고 통합 설정에 기록한다."""
    errors.set_json_surface(json_out)

    def _do() -> int:
        from ... import memory_bridge
        from ...settings import load_project

        root = os.getcwd()
        previous = dict(memory_bridge.project_memory_section(load_project(root)) or {})
        selected_engine = engine.strip().lower()
        selected_options = _backend_options(option_values or [])
        identity = _connect_identity(
            root,
            previous,
            project_id,
            endpoint=endpoint,
            engine=selected_engine,
            recover_binding=recover_binding,
            json_out=json_out,
        )
        pid, project_uid, binding_id = identity.project_id, identity.project_uid, identity.binding_id
        explicit_project_id = identity.explicit_project_id
        config = {
            "engine": selected_engine,
            "endpoint": endpoint.rstrip("/"),
            "project_id": pid,
            "options": selected_options,
            "project_uid": project_uid,
            "binding_id": binding_id,
        }
        if timeout is not None:
            # 동기 retain이 backend LLM 추출을 기다린다 — 느린 게이트웨이는 기본 15s를 넘긴다
            # (실측 26-07-24: qwen3:8b 로컬 추출 ~16s → binding write가 기본값에서 항상 timeout)
            config["timeout"] = int(timeout)
        binding_id = _bind_namespace(
            config,
            pid,
            project_uid,
            binding_id,
            explicit_project_id=explicit_project_id,
            claim=claim,
            adopt_existing=adopt_existing,
            json_out=json_out,
        )
        config["binding_id"] = binding_id
        if not json_out:
            ui.ok(f"backend ready and bound: {selected_engine} @ {config['endpoint']}")
        p = memory_bridge.write_config(
            root,
            str(config["endpoint"]),
            pid,
            engine=selected_engine,
            options=selected_options,
            project_uid=project_uid,
            binding_id=binding_id,
            timeout=timeout,
        )
        memory_bridge.trust_backend(config)
        if json_out:
            _emit(
                {
                    "connected": True,
                    "engine": selected_engine,
                    "endpoint": config["endpoint"],
                    "project_id": pid,
                    "project_uid": project_uid,
                    "binding_id": binding_id,
                    "binding_recovered": bool(identity.recovered),
                    "config_path": p,
                    "auto_recall": not _uninjected_note(root),
                }
            )
            return 0
        _connected_report(root, selected_engine, pid, p)
        return 0

    return _guard(_do)


def run_mcp() -> int:
    """stdio MCP 브릿지 — Claude Code 등 MCP 클라이언트가 command 타입으로 기동."""
    from ... import memory_bridge

    return memory_bridge.serve()


def run_provider(set_spec: str = "", clear: bool = False, json_out: bool = False) -> int:
    """개인 메모리를 손질하는 provider를 보이거나 바꾼다 (기본 = 메인 provider)."""

    def _do() -> int:
        from ...memory import manager

        if clear:
            manager.save_manager("")
            ui.ok("개인 메모리 관리자를 해제했어요 — 이제 메인 provider가 손질해요")
        elif set_spec:
            saved = manager.save_manager(set_spec)
            ui.ok(f"개인 메모리 관리자: {saved['provider']}" + (f" · {saved['model']}" if saved["model"] else ""))
        row = manager.describe(os.getcwd())
        if json_out:
            print(_json.dumps(row, ensure_ascii=False, indent=2))
            return 0 if row.get("ready") else 1
        ui.head("personal memory · manager")
        origin = {"main": "메인 provider", "config": "설정 지정", "env": f"env {manager.MANAGER_ENV}"}
        ui.step(
            f"curator · {row.get('provider') or '미해석'} {row.get('model') or ''} ({origin.get(row['source'], row['source'])})"
        )
        if row.get("configured") and row.get("main_provider"):
            ui.step(f"main · {row['main_provider']} {row.get('main_model', '')}")
        ui.step(f"inject · {'on' if row['inject_enabled'] else 'off (kill switch)'}")
        if not row.get("ready"):
            ui.warn("관리자 호출 불가 — " + "; ".join(row.get("missing") or ["provider 미설정"]))
            ui.step("손질(norn·pattern)만 멈춰요 — 저장·검색·회상은 LLM 없이 그대로 돌아가요")
            return 1
        if row["inject_enabled"] and not row.get("inject_allowed", True):
            ui.warn(f"{row.get('provider')}에는 개인 메모리를 안 실어요 (손질만 맡겨요)")
            ui.step(f'허용하려면 ~/.asgard 전역 설정 "memory".providers에 "{row.get("provider")}" 추가')
        return 0

    return _guard(_do)


SEMANTIC_NUDGE_FLAG = "semantic-warmup-nudged"
# 색인 드리프트는 되풀이될 수 있는 고장이라 표시를 따로 둔다 — reindex가 지운다.
COVERAGE_NUDGE_FLAG = "semantic-coverage-nudged"


def _semantic_nudge_line(d: str) -> str:
    """시맨틱이 켜져 있는데 모델이 아직 없을 때만 한 줄. 한 번 말하면 다시 말하지 않는다.

    왜 훅이 아니라 여기인가: 훅은 자식의 stderr를 삼키므로 "준비 중" 메시지가 사용자에게
    닿지 않는다. 그리고 훅은 시간 상한 안에서 도느라 내려받기를 아예 시작하지 않는다
    (memory_semantic.deadline_bound). 그래서 **사람에게 보이는 통로**로 한 번 알려야
    신규 설치가 시맨틱 없이 조용히 계속 도는 일이 없다."""
    from ... import memory_semantic as sem

    if sem.mode() == "off":
        return ""
    # 두 가지 다른 고장을 한 통로로 알린다. ① 모델이 아직 없다 (내려받기 전) ② 모델은 있는데
    # 파생 벡터가 정본을 안 덮는다. ②가 더 조용한 고장이다 — 임베더가 서니 상태 표면은 전부
    # "동작 중"이라고 말하는데 시맨틱 스트림은 매번 빈 리스트를 낸다 (실측 26-07-29:
    # 페이지 2장·vec 0행). 사용자는 모델 로드 비용만 내고 이득은 0을 받는다.
    message = ""
    if not sem.model_cached():
        message = "시맨틱 검색이 아직 준비되지 않았어요 (어휘 회수로 도는 중) — asgard memory semantic warmup"
    else:
        coverage = memory.vec_coverage(d)
        if not coverage["ok"] and coverage["pages"]:
            missing = coverage["pages"] - coverage["fresh"]
            message = (
                f"시맨틱 색인이 정본을 못 덮어요 — {coverage['fresh']}/{coverage['pages']} 페이지 "
                f"(미색인·낡음 {missing}건). 임베더는 돌고 있으니 비용만 내고 이득은 없어요 — asgard memory reindex"
            )
    if not message:
        return ""
    # latch는 사유별로 나눈다: "준비 안 됨"을 한 번 말했다고 그 뒤에 생긴 색인 드리프트까지
    # 침묵하면, 고쳐야 할 두 번째 고장이 첫 번째 고장의 표시에 가려진다.
    flag = os.path.join(d, SEMANTIC_NUDGE_FLAG if not sem.model_cached() else COVERAGE_NUDGE_FLAG)
    if os.path.exists(flag):
        return ""
    try:
        with open(flag, "w", encoding="utf-8") as handle:
            handle.write(memory._today())
    except OSError:
        return ""  # 표시를 못 남기면 되풀이 말하느니 침묵한다
    return message


def run_tick(json_out: bool = False) -> int:
    """턴 끝 신호를 한 프로세스에서 본다 — 진화·스킬 노후·노른·패턴·2차 진화·학습·시맨틱 준비.

    Stop 훅이 네 번 띄우던 자리다: `evolve nudge` · `memory norn --wake` ·
    `memory pattern --due` · `memory semantic nudge`. 넷이 하는 일은 "낼 말이 한 줄 있는가"
    판정이고 출력도 각각 한 줄인데, 값의 대부분은 인터프리터 부팅이었다 (26-08-04 실측:
    네 자식 합계 408~434ms, 그중 프로세스 바닥값 68ms × 4).

    일곱 중 넷은 이제 말만 하지 않고 **패스를 띄운다** (norn·pattern·project_evolve·
    project_memory.automation의 wake). 판정은 여전히 파일 몇 개를 읽을 뿐이고 — 손질 본체는
    분리 스폰한 자식이 맡는다. 스킬 노후(skill_curator.wake)는 자식을 안 띄운다: 원료가
    SKILL.md 몇 개라 스폰이 판정보다 비싸다.

    판정·latch·스폰은 옮기지 않는다 — 각 모듈의 같은 함수를 그대로 부른다. 하나가 죽어도
    나머지는 낸다: 넛지는 편의지 계약이 아니라, 하나의 실패가 턴 종료를 막으면 안 된다."""
    d = memory.ensure_home()
    # 진화 넛지는 종전에 `asgard evolve nudge` 가 git toplevel 로 뿌리를 풀었다 (commands/evolve.py
    # 의 `_surface`). cwd 를 그대로 주면 하위 폴더에서 돌 때 `.asgard/evolution` latch 와
    # `.asgard/quest` 를 엉뚱한 자리에서 읽어 매 턴 초기화된다 — 나머지 패스는 원래 cwd였다.
    from ..evolve import _root as _git_toplevel

    root = _git_toplevel()
    lines: list[str] = []

    def _collect(make) -> None:
        try:
            line = (make() or "").strip()
        except Exception:
            return
        if line:
            lines.append(line.splitlines()[0])

    from ... import evolution as evo
    from ... import skill_curator
    from ...memory import norn as norn_mod
    from ...memory import pattern as pattern_mod
    from ...project_memory import automation as project_automation
    from ...project_memory import evolve as project_evolve

    _collect(lambda: evo.nudge_line(root))
    _collect(lambda: skill_curator.wake(root))
    _collect(lambda: norn_mod.wake(root, d))
    _collect(lambda: pattern_mod.wake(root, d))
    _collect(lambda: project_evolve.wake(root))
    _collect(lambda: project_automation.wake(root))
    _collect(lambda: _semantic_nudge_line(d))

    if json_out:
        print(_json.dumps({"nudges": lines}, ensure_ascii=False))
    else:
        for line in lines:
            print(line)
    return 0


def run_semantic(action: str = "status", json_out: bool = False) -> int:
    """시맨틱 검색 상태·워밍업·켜고 끄기. 첫 실행의 긴 내려받기를 여기서 미리 부담한다."""

    def _do() -> int:
        from ... import memory_semantic as sem

        if action == "nudge":  # 훅 전용 — 준비 안 됐을 때만 한 줄, latch는 여기가 소유한다
            line = _semantic_nudge_line(memory.ensure_home())
            if line:
                print(line)
            return 0
        if action in ("on", "off"):
            from ...settings import load_global, save_global

            configured = dict(load_global().get("memory") or {})
            configured["semantic"] = "local" if action == "on" else "off"
            save_global("memory", configured)
            ui.ok(f"시맨틱 검색 {'켬' if action == 'on' else '끔'}")
            if action == "off":
                ui.step("lexical 2경로로 그대로 돌아가요 — 저장된 기억은 안 건드려요")
                return 0
        if action in ("on", "warmup"):
            if not sem.model_cached():
                ui.step("임베딩 모델을 처음 내려받아요 — 약 1GB, 수십 초 걸려요 (한 번만)")
            state = sem.warmup()
            if json_out:
                print(_json.dumps(state, ensure_ascii=False, indent=2))
                return 0 if state["active"] else 1
            if not state["active"]:
                ui.fail("임베더를 못 불렀어요 — lexical 2경로로 계속 돌아가요")
                ui.step("uv tool install --force asgard (model2vec이 빠졌을 수 있어요)")
                return 1
            ui.ok(f"준비됨: {state['model']} · {state['dim']}d · {state['seconds']}s")
            return 0
        return _emit_semantic_status(json_out)

    return _guard(_do)


def _emit_semantic_status(json_out: bool) -> int:
    """시맨틱 **상태 표시**. 켜고 끄기·워밍업과 갈라 두는 이유는 부수효과다 — 앞의 셋은 설정을
    바꾸거나 1GB를 내려받고, 이쪽은 아무것도 안 바꾼다. 한 함수에 있으면 "상태를 봤더니
    켜졌다"가 가능한 모양이 되고, 조회가 안전하지 않은 명령은 사람이 안 쓴다."""
    from ... import memory_semantic as sem

    status = sem.status()
    coverage = memory.vec_coverage(memory.ensure_home())
    if json_out:
        print(
            _json.dumps(
                {**status, "model_cached": sem.model_cached(), "coverage": coverage},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if status["active"] and coverage["ok"] else 1
    ui.head("personal memory · semantic")
    ui.step(f"mode · {status['mode']}")
    if status["active"]:
        ui.ok(f"임베더 · {status['model']} · {status['dim']}d")
    elif status["mode"] == "off":
        ui.step("꺼져 있어요 — `asgard memory semantic on`으로 켜세요")
        return 0
    else:
        ui.warn("켜져 있는데 임베더를 못 불렀어요 — lexical 2경로로 대신 돌고 있어요")
        return 1
    # 임베더가 준비된다는 것과 시맨틱이 회수에 기여한다는 것은 다른 말이다. 덮지 못한 페이지는
    # 어휘 경로로만 찾히는데, 그 사실이 여기 안 적히면 사용자는 켰다고 믿은 채로 못 받는다.
    if coverage["ok"]:
        ui.ok(f"색인 · {coverage['fresh']}/{coverage['pages']} 페이지 (100%)")
        return 0
    detail = f"{coverage['fresh']}/{coverage['pages']} 페이지 ({coverage['coverage'] * 100:.0f}%)"
    parts = [
        f"낡음 {coverage['stale']}" if coverage["stale"] else "",
        f"고아 {coverage['orphan']}" if coverage["orphan"] else "",
    ]
    suffix = " · " + " · ".join(p for p in parts if p) if any(parts) else ""
    ui.warn(f"색인 · {detail}{suffix} — 안 덮인 페이지는 시맨틱 검색에 안 걸려요")
    ui.step("asgard memory reindex")
    return 1
