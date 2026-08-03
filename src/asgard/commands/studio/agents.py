"""에이전트(에인헤랴르) 패널의 재료 — 창이 그릴 것을 JSON 으로 만든다. 화면 문장은 여기서 안 만든다.

여태 이 계층은 CLI 에만 있었다(`asgard agent list|create|use|describe|bind|…`). 창에는
에이전트 표면이 한 칸도 없어서, 스튜디오만 켜 둔 사람은 자기가 어느 에이전트로 돌고 있는지도
못 봤다. 이 모듈이 그 재료를 낸다 — **판정은 하나도 안 한다**: 이름 규약은 `profiles.validate`
가, 배치의 유효성은 `swarm.bind` 가, 설정의 자리는 `settings` 가 진다. 여기는 그 판정을
좌표·수·이름으로 꺼내 담고, 엔진이 올린 예외를 상태 코드로 옮길 뿐이다.

한 왕복에 세 갈래를 담는다: 이 기계의 에이전트 명부 · 내장 명부 · **이 프로젝트의 배치**.
셋을 갈라 놓으면 화면이 "누가 있는가"와 "여기서 누가 일하는가"를 따로 물어야 하고, 그 둘
사이에 낀 변경이 서로의 결과처럼 보인다 (튜터·오케스트레이션 패널과 같은 규율).

파괴와 전환은 조용히 안 지나간다:
  · 삭제는 `confirm` 없이는 409 다 — 그 문장에 **잃을 기억 쪽수**가 들어간다.
  · `use`(활성 전환)는 이 기계 전체를 바꾼다. 그래서 응답이 무엇이 어떻게 바뀌었는지를
    함께 돌려준다(`previous`·`scope`·`note`) — 창이 확인을 붙일 수 있어야 조용한 전환이 아니다.

실패 형식은 **이 창이 이미 쓰는 것**을 따른다: `loopback.api_error` → `{"error":{code,message,
remedy}}`. 스튜디오의 `api()` 가 그 모양을 풀어 `e.message`·`e.remedy` 로 풀어 쓰고, `errorCard()`
가 처방까지 그린다. 여기서 평평한 `{"error":…,"remedy":…}` 를 새로 내면 한 창 안에 오류
모양이 두 벌이 된다.
"""

from __future__ import annotations

import os

from ... import profiles, settings, swarm
from .. import loopback

_json_body = loopback.json_body
_api_error = loopback.api_error


# ── 재료 ────────────────────────────────────────────────────────────────────────


def panel_state(root: str) -> dict:
    """패널 한 판의 재료 — 명부·내장 명부·이 프로젝트의 배치.

    `root` 는 **에이전트가 사는 기계 뿌리**(`profiles.root()`)다. 프로젝트 경계가 아니다:
    에이전트는 폴더가 아니라 기계에 속하고, 화면이 "이것들은 여기 살아요"라고 적을 자리가
    그것뿐이다. 프로젝트 쪽 사실은 `binding`·`swarm`·`missing` 이 든다.
    """
    active = profiles.sticky()
    agents = profiles.listing()
    # 요청별 프로파일 스코프와 기계 기본은 다른 값이다. 명부의 표시는 기계 기본만 짚는다.
    for row in agents:
        row["active"] = row["id"] == active
    return {
        "agents": agents,
        "active": active,
        "builtin_available": _builtin_available(),
        "root": profiles.root(),
        "binding": _binding_view(root),
        "swarm": swarm.is_swarm(root),
        "missing": swarm.missing(root),
        # 환경을 안 물려받아 기본 에이전트에 쓰고 있는 상태 — 엔진이 쓴 문장을 그대로 내보낸다.
        # 표면이 다시 쓰면 같은 사실이 창과 doctor 에서 다르게 불린다.
        "warning": profiles.fallback_warning(),
    }


def _server_default() -> tuple[str, str]:
    """이 서버가 어느 에이전트로 섰는가 — (에이전트, 출처). 서버 밖(시험·직접 호출)이면 빈 값.

    `--isolated`가 이것에 기댄다: 에이전트 X로 띄운 서버는 쿼리가 없는 요청도 X로 답해야 한다.
    이 갈래가 없으면 서버가 자기 바인딩을 무시하고 배치·끈끈한 활성으로 떨어져, 격리 서버가
    남의 에이전트로 답한다. 여태 그게 안 드러난 이유는 시동 URL이 항상 `?agent=`를 실어
    모든 요청이 explicit으로 들어왔기 때문이다 — 그 URL을 바로잡으면 이 갈래가 필요해진다."""
    try:
        from . import state

        server = getattr(state, "_SERVER", None)
        agent = profiles.normalize(getattr(server, "agent", "") or "")
        if not agent or not profiles.exists(agent):
            return "", ""
        return agent, str(getattr(server, "agent_source", "") or "sticky")
    except Exception:  # 서버 상태를 못 읽는 것이 요청을 막으면 안 된다
        return "", ""


def request_scope(root: str, explicit: str = "") -> tuple[dict | None, tuple[int, str, bytes]]:
    """요청 하나의 에이전트와 선택 근거. URL 선택은 다른 요청의 기본값을 바꾸지 않는다."""
    wanted = str(explicit or "").strip()
    if wanted:
        try:
            wanted = profiles.validate(wanted)
        except ValueError as exc:
            return None, _name_refused(exc)
        if not profiles.exists(wanted):
            return None, _unknown(wanted)
    if not wanted:
        bound, bound_source = _server_default()
        if bound:
            try:
                from ... import sessions

                key = sessions.session_key(bound)
            except Exception:
                key = ""
            return {"agent": bound, "source": bound_source, "key": key}, _EMPTY
    try:
        from ... import sessions

        described = sessions.describe(root, explicit=wanted or None)
    except ImportError, AttributeError:
        described = {"agent": wanted or profiles.sticky(), "source": "explicit" if wanted else "sticky", "key": ""}
    agent = profiles.normalize(described.get("agent") or wanted or profiles.sticky())
    if not profiles.exists(agent):
        if wanted:
            return None, _unknown(wanted)
        agent = profiles.sticky() if profiles.exists(profiles.sticky()) else profiles.DEFAULT
        described = {"agent": agent, "source": "sticky", "key": ""}
    return {
        "agent": agent,
        "source": str(described.get("source") or "sticky"),
        "key": str(described.get("key") or ""),
    }, _EMPTY


def runs_state() -> dict:
    """기계의 Studio 실행 목록과 이 서버의 실행 id. 등록부가 아직 없으면 빈 목록이다."""
    try:
        from ... import runs

        rows = runs.listing()
    except ImportError, AttributeError, OSError:
        rows = []
    from . import state

    server = state._SERVER
    current = str(getattr(state, "_RUN_ID", "") or getattr(server, "run_id", "") or "")
    if not current:
        record = getattr(server, "run", None) or getattr(server, "run_record", None)
        if isinstance(record, dict):
            current = str(record.get("id") or "")
    return {"runs": rows, "self": current}


def _binding_view(root: str) -> dict:
    """이 프로젝트의 배치 — 목록과 bind/unbind 응답이 **같은 모양**을 쓴다.

    선언 안 함(엔진의 `""`)은 `null` 로 옮긴다: "아무도 안 앉혔다"와 "기본 에이전트를 명시로
    골랐다"(`"default"`)는 다른 상태인데, 빈 문자열로 주면 화면이 뒤를 앞으로 그린다. 한
    응답 안에서 이 칸이 두 모양이면 그 자체로 결함이라 여기 한 곳에서만 만든다."""
    binding = swarm.binding(root)
    return {
        "default": binding["default"] or None,
        "modes": dict(binding["modes"]),
        "roles": dict(binding["roles"]),
    }


def _builtin_available() -> dict:
    """아직 안 세운 내장 에이전트 — {id: {name, description}}.

    이미 만든 이름은 뺀다. 같은 키를 CLI(`asgard agent list --json`)가 그 뜻으로 쓰기
    때문이다 — 표면마다 같은 이름이 다른 집합을 가리키면 그 키는 계약이 아니다."""
    made = {row["id"] for row in profiles.listing()}
    return {
        short: {"name": str(entry.get("name") or short), "description": str(entry.get("description") or "")}
        for short, entry in sorted(profiles.builtin_roster().items())
        if short not in made
    }


def _row(name: str) -> dict | None:
    """명부의 한 줄 — 없는 이름이면 None. 목록과 상세가 같은 줄을 쓴다."""
    canon = profiles.normalize(name)
    for row in profiles.listing():
        if row["id"] == canon:
            row["active"] = canon == profiles.sticky()
            return row
    return None


def _target(payload: dict) -> tuple[dict | None, tuple[int, str, bytes]]:
    """요청이 가리키는 에이전트 한 줄 — 못 짚으면 (None, 그 자리의 실패 응답).

    이름이 비어 있는 것(400)과 이름이 목록에 없는 것(404)을 가른다. 둘을 합쳐 던지면
    화면이 "안 골랐다"와 "지워진 걸 고쳤다"를 같은 문장으로 그린다."""
    name = str(payload.get("name") or "").strip()
    if not name:
        return None, _api_error(
            400, "name_required", "어느 에이전트인지 이름이 필요해요.", "목록에서 하나를 골라 주세요."
        )
    row = _row(name)
    return (row, _EMPTY) if row is not None else (None, _unknown(name))


_EMPTY: tuple[int, str, bytes] = (0, "", b"")  # `_target` 이 성공했을 때의 자리채움 — 절대 안 나간다


def agent_detail(name: str, root: str) -> tuple[int, str, bytes]:
    """에이전트 하나 — 명부의 줄 + 정체성 원문 + 설정(자기 것·병합 뷰).

    한 왕복인 이유는 편집 화면 때문이다: 정체성과 설정을 따로 받으면 그 사이에 낀 남의
    저장이 이 화면의 값처럼 보이고, 사용자는 자기가 안 적은 것을 자기 것으로 덮어쓴다."""
    row, failed = _target({"name": name})
    if row is None:
        return failed
    body = profiles.identity(row["id"])
    return _json_body(
        200,
        {
            **row,
            "identity": body,
            "identity_path": os.path.join(row["path"], profiles.IDENTITY),
            # 주석뿐인 파일은 없는 것으로 친다 — 안내 템플릿만 든 에이전트는 프롬프트에서 침묵한다.
            "identity_meaningful": bool(profiles._meaningful(body)),
            "config": settings.profile_config(row["id"]),
            "config_view": settings.profile_config_view(row["id"]),
            "config_path": settings.profile_config_path(row["id"]),
        },
    )


# ── 쓰기 ────────────────────────────────────────────────────────────────────────
#
# 쓰기는 전부 바뀐 뒤의 패널 재료(`state`)를 함께 돌려준다 — 창이 GET 을 한 번 더 돌면 그 사이에
# 낀 남의 변경이 이 저장의 결과처럼 보인다 (튜터·오케스트레이션 패널과 같은 계약).


def create_agent(payload: dict, root: str) -> tuple[int, str, bytes]:
    """에이전트 하나를 짓는다 — 자기 홈·자기 정체성·자기 기억을 얻는다."""
    name = str(payload.get("name") or "").strip()
    if not name:
        return _api_error(
            400, "name_required", "새 에이전트의 이름이 필요해요.", "영소문자·숫자·하이픈으로 지어 주세요."
        )
    try:
        path = profiles.create(
            name,
            based_on=str(payload.get("from") or "") or None,
            description=str(payload.get("description") or "") or None,
            clone_from=str(payload.get("clone") or "") or None,
            display=str(payload.get("display") or "") or None,
        )
    except FileExistsError as exc:
        return _api_error(
            409,
            "agent_exists",
            f"{name} 에이전트는 이미 있어요.",
            "다른 이름을 고르거나, 있는 것을 고쳐 주세요.",
            {"reason": str(exc)},
        )
    except FileNotFoundError as exc:
        return _api_error(
            404,
            "agent_not_found",
            "복제할 원본 에이전트를 못 찾았어요.",
            "목록에 있는 이름으로 복제해 주세요.",
            {"reason": str(exc)},
        )
    except ValueError as exc:
        return _name_refused(exc)
    return _json_body(200, {"created": profiles.normalize(name), "path": path, "state": panel_state(root)})


def use_agent(payload: dict, root: str) -> tuple[int, str, bytes]:
    """이 기계의 활성 에이전트를 바꾼다.

    이 한 줄이 기계 전체를 바꾼다 — 이후 모든 세션의 기억·스킬·설정이 그 에이전트의 것이
    된다. 그래서 응답이 **무엇이 어떻게 바뀌었는지**를 돌려준다: 이전 이름, 바뀐 범위,
    그리고 사람이 읽을 한 문장. 창이 이 셋으로 확인을 붙일 수 있어야, 누르면 조용히
    갈리는 버튼이 되지 않는다."""
    name = str(payload.get("name") or "").strip()
    if not name:
        return _api_error(
            400, "name_required", "어느 에이전트로 바꿀지 이름이 필요해요.", "목록에서 하나를 골라 주세요."
        )
    # 내장 명부의 이름을 고르는 것은 곧 그 에이전트의 기억을 여는 행위다(CLI `agent use`와 같다).
    # 하지만 **그 밖의 모르는 이름은 여기서 안 짓는다**: CLI 에서는 사람이 이름을 직접 타이핑한
    # 것이지만 창에서는 목록을 누른 것이라, 목록 밖의 이름이 오는 경우는 오타 아니면 낡은 화면이다.
    # 그때 조용히 새 에이전트를 세우면 사용자는 자기가 만든 적 없는 에이전트로 기계를 돌린다.
    if _row(name) is None and profiles.normalize(name) not in profiles.builtin_roster():
        return _unknown(name)
    previous = profiles.sticky()
    try:
        profiles.ensure(name)
        canon = profiles.set_active(name)
    except FileNotFoundError:
        return _unknown(name)
    except ValueError as exc:
        return _api_error(400, "invalid_name", str(exc), "목록에 있는 이름을 골라 주세요.")
    row = _row(canon) or {}
    return _json_body(
        200,
        {
            "active": canon,
            "path": row.get("path") or profiles.profile_dir(canon),
            "previous": previous,
            # 창이 확인 UI 를 세울 손잡이 — 이 전환의 범위는 프로젝트가 아니라 기계다.
            "scope": "machine",
            "note": (
                f"이제 이 기계의 새 세션은 전부 {canon} 에이전트로 돌아요 — "
                f"기억도 스킬도 설정도 그 에이전트의 것을 써요 (이전 활성: {previous})."
            ),
            "state": panel_state(root),
        },
    )


def describe_agent(payload: dict, root: str) -> tuple[int, str, bytes]:
    """명세를 고친다 — `description` 은 장식이 아니라 스웜이 일을 어디로 보낼지 읽는 문장이다."""
    row, failed = _target(payload)
    if row is None:
        return failed
    caps = payload.get("capabilities")
    profiles.write_manifest(
        row["id"],
        name=str(payload.get("display") or "") or None,
        description=payload.get("description"),
        capabilities=[str(c) for c in caps] if isinstance(caps, list) else None,
    )
    return _json_body(200, {"manifest": profiles.manifest(row["id"]), "state": panel_state(root)})


def save_identity(payload: dict, root: str) -> tuple[int, str, bytes]:
    """정체성 문서를 교체한다 — 다음 세션의 프롬프트에 이 본문이 들어간다.

    `meaningful` 을 함께 돌려주는 이유: 주석만 남긴 파일은 이 계층이 침묵한다. 저장은
    됐는데 프롬프트에 안 들어가는 상태를 화면이 말할 수 있어야 한다."""
    row, failed = _target(payload)
    if row is None:
        return failed
    body = payload.get("body")
    if not isinstance(body, str):
        return _api_error(400, "body_required", "정체성 본문이 필요해요.", "비우려면 빈 문자열을 보내 주세요.")
    path = profiles.write_identity(row["id"], body)
    return _json_body(
        200,
        {
            "path": path,
            "chars": len(body),
            "meaningful": bool(profiles._meaningful(body)),
            "state": panel_state(root),
        },
    )


def save_config(payload: dict, root: str) -> tuple[int, str, bytes]:
    """설정 섹션 하나를 이 에이전트의 파일에 적는다 — 섹션 **교체**(`settings.save_global` 계약).

    적은 뒤의 `config`(자기 것)와 `config_view`(실효 병합)를 함께 돌려준다. 둘이 갈리는
    자리가 곧 "물려받는 값"이고, 화면이 그 갈림을 못 보면 뿌리의 값을 자기 값으로 오해한다."""
    row, failed = _target(payload)
    if row is None:
        return failed
    section = str(payload.get("section") or "").strip()
    values = payload.get("values")
    if not section:
        return _api_error(
            400,
            "section_required",
            "어느 설정 갈래인지 이름이 필요해요.",
            "provider·memory처럼 섹션 이름을 함께 보내 주세요.",
        )
    if not isinstance(values, dict):
        return _api_error(
            400,
            "values_required",
            "설정 값은 키와 값의 묶음이어야 해요.",
            "지울 키는 값을 비운 채 보내면 빠져요.",
        )
    path = settings.save_profile_config(row["id"], section, values)
    return _json_body(
        200,
        {
            "path": path,
            "config": settings.profile_config(row["id"]),
            "config_view": settings.profile_config_view(row["id"]),
            "state": panel_state(root),
        },
    )


def rename_agent(payload: dict, root: str) -> tuple[int, str, bytes]:
    """이름을 바꾼다 — 홈 디렉터리가 곧 이름이라 기억과 설정이 함께 옮겨진다."""
    row, failed = _target(payload)
    if row is None:
        return failed
    name, target = row["id"], str(payload.get("to") or "").strip()
    if not target:
        return _api_error(400, "name_required", "새 이름이 필요해요.", "영소문자·숫자·하이픈으로 지어 주세요.")
    try:
        path = profiles.rename(name, target)
    except FileExistsError:
        return _api_error(
            409,
            "agent_exists",
            f"{target} 에이전트는 이미 있어요.",
            "다른 이름을 고르거나, 있는 것을 먼저 지워 주세요.",
        )
    except FileNotFoundError:
        return _unknown(name)
    except ValueError as exc:
        return _name_refused(exc)
    return _json_body(
        200,
        {"renamed": profiles.normalize(target), "path": path, "state": panel_state(root)},
    )


def bind_agent(payload: dict, root: str) -> tuple[int, str, bytes]:
    """이 프로젝트의 배치 하나를 적는다 — 역할 배치가 둘 이상 갈리면 그게 스웜이다."""
    name = str(payload.get("name") or "").strip()
    if not name:
        return _api_error(
            400, "name_required", "어느 에이전트를 배치할지 이름이 필요해요.", "목록에서 하나를 골라 주세요."
        )
    mode = str(payload.get("mode") or "").strip() or None
    role = str(payload.get("role") or "").strip() or None
    try:
        swarm.bind(root, name, mode=mode, role=role)
    except FileNotFoundError:
        return _unknown(name)
    except ValueError as exc:
        return _api_error(
            400,
            "invalid_binding",
            "이 배치는 적을 수 없어요.",
            "모드와 역할은 함께 못 써요 — 하나만 골라 주세요 (역할이 모드보다 좁아요).",
            {"reason": str(exc)},
        )
    return _json_body(200, {"binding": _binding_view(root), "swarm": swarm.is_swarm(root), "state": panel_state(root)})


def unbind_agent(payload: dict, root: str) -> tuple[int, str, bytes]:
    """배치 하나를 지운다 — 그 자리는 다시 루트의 활성 에이전트로 떨어진다."""
    mode = str(payload.get("mode") or "").strip() or None
    role = str(payload.get("role") or "").strip() or None
    swarm.unbind(root, mode=mode, role=role)
    return _json_body(200, {"binding": _binding_view(root), "swarm": swarm.is_swarm(root), "state": panel_state(root)})


def delete_agent(payload: dict, root: str) -> tuple[int, str, bytes]:
    """에이전트를 지운다 — **되돌릴 수 없다**. 기억이 함께 사라진다.

    `confirm` 없이는 409 다. 그 문장에 잃을 기억 쪽수를 담는 이유는, 이 화면에서 사용자가
    아는 것이 이름뿐이기 때문이다: 쪽수를 안 보여 주면 "빈 에이전트를 치우는 일"과 "반년치
    일지를 버리는 일"이 같은 버튼이 된다."""
    row, failed = _target(payload)
    if row is None:
        return failed
    if payload.get("confirm") is not True:
        pages = int(row.get("memory_pages") or 0)
        loss = f"이 에이전트가 기억한 {pages}쪽이 함께 사라져요" if pages else "이 에이전트의 홈이 통째로 사라져요"
        return _api_error(
            409,
            "confirm_required",
            f"{row['id']} 에이전트를 지우면 되돌릴 수 없어요 — {loss}.",
            "정말 지우려면 confirm을 참으로 다시 보내 주세요.",
            {"agent": row["id"], "memory_pages": pages, "path": row["path"]},
        )
    try:
        path = profiles.delete(row["id"])
    except FileNotFoundError:
        return _unknown(row["id"])
    except ValueError as exc:
        # 기본 에이전트는 지울 수 없다 — `~/.asgard` 자체다.
        return _api_error(
            400,
            "undeletable",
            "기본 에이전트는 지울 수 없어요 — 이 기계의 뿌리 자체예요.",
            "이 프로젝트에서만 걷어내려는 거라면 배치(bind)를 푸세요.",
            {"reason": str(exc)},
        )
    return _json_body(200, {"deleted": row["id"], "path": path, "state": panel_state(root)})


def _name_refused(exc: Exception) -> tuple[int, str, bytes]:
    """이름 규약을 못 넘은 자리 — 판정은 `profiles.validate` 의 것이고 문장만 여기서 짓는다.

    엔진의 문장을 그대로 내보내지 않는 이유는 문체다: 그쪽은 CLI 를 향해 쓰인 해라체이고
    때로 플래그 이름을 포함한다. 원문은 `detail.reason` 에 남겨 두 표면이 같은 판정을 봤다는
    것을 잃지 않는다."""
    return _api_error(
        400,
        "invalid_name",
        "그 이름은 쓸 수 없어요.",
        "영소문자로 시작하고 영숫자·하이픈·밑줄만 쓰세요 (CLI 하위 명령과 겹치는 이름도 못 써요).",
        {"reason": str(exc)},
    )


def _unknown(name: str) -> tuple[int, str, bytes]:
    """없는 이름 한 자리 — 목록에 없는 것을 고쳤다고 말하면 기록이 거짓이 된다."""
    label = str(name or "").strip() or "(이름 없음)"
    return _api_error(
        404,
        "agent_not_found",
        f"{label} 에이전트를 못 찾았어요.",
        "목록에 있는 이름을 고르거나, 그 이름으로 새로 세워 주세요.",
    )
