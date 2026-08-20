"""doctor — 기억 검사. 개인 위키·프로젝트 백엔드·시맨틱 레인·큐레이터·내구성."""

import os
from dataclasses import asdict


def _shared_memory_check(root: str) -> dict | None:
    """설정된 프로젝트 메모리의 trust·exact binding·readiness를 Trinity와 독립 진단한다."""
    try:
        from ...memory_bridge import (
            GATE_UNAPPROVED,
            auto_retain_turns_state,
            autosave_state,
            find_config,
            is_backend_trusted,
            verify_backend_binding,
        )
        from ...project_memory_backends import get_backend

        found = find_config(root, strict=True)
        if not found:
            # enabled=false는 미연결과 다른 의도적 비활성 — 무음이면 "왜 안 쌓이지" 조회가 불가능하다.
            try:
                from ...memory_bridge import project_memory_disabled, project_memory_section
                from ...settings import load_project

                section = project_memory_section(load_project(root))
                if project_memory_disabled(section):
                    return {
                        "name": "shared memory backend",
                        "ok": True,
                        "detail": "off (project_memory.enabled=false — 의도된 비활성)",
                        "fix": "",
                    }
            except Exception:
                pass
            # 미연결도 한 줄을 낸다. 행 자체를 빼면 doctor 화면에 개인 메모리 다섯 줄만 남고
            # 2차 메모리는 이름조차 안 나온다 — 26-08-11 에 "2차 메모리가 왜 회수되지 않느냐"는
            # 물음이 여기서 답을 못 얻었다. 갓 init 한 저장소의 정상 상태이므로 ok 는 뒤집지 않는다.
            return {
                "name": "shared memory backend",
                "ok": True,
                "detail": "미연결 — 이 저장소도, 위쪽 폴더도, 선언된 작업 뿌리도 project_memory 를 안 적었어요",
                "fix": "asgard memory connect <endpoint> (짝 저장소의 뱅크를 쓰려면 `asgard root add <dir> --yes`)",
            }
        mroot, mcfg = found
        try:
            if not is_backend_trusted(mcfg):
                raise PermissionError("untrusted backend target; run asgard memory connect")
            backend = get_backend(mcfg)
            try:
                binding = verify_backend_binding(mcfg, backend=backend)
                readiness = backend.readiness()
                enabled = [name for name, supported in asdict(backend.capabilities()).items() if supported]
                engine, project_id = backend.engine, backend.project_id
                learning_detail = ""
                learning_ok = True
                if engine == "hindsight":
                    from ...project_memory.learning import MODEL_SPECS, load_synthesis, model_ready

                    read_config = getattr(backend, "bank_config", None)
                    list_models = getattr(backend, "list_mental_models", None)
                    if callable(read_config) and callable(list_models):
                        bank_config = read_config()
                        models = {
                            str(model.get("id") or ""): model for model in list_models() if isinstance(model, dict)
                        }
                        expected = {str(spec["id"]) for spec in MODEL_SPECS}
                        ready_models = sum(model_ready(models.get(model_id, {})) for model_id in expected)
                        # 종합층이 만들어졌다고 주입되는 것이 아니다 — 회수는 로컬 사본만 읽는다.
                        # 모델은 준비됐는데 사본이 없으면 그 층은 어떤 프롬프트에도 안 들어간다.
                        synthesis = len(
                            load_synthesis(
                                mroot,
                                project_uid=str(mcfg.get("project_uid") or ""),
                                binding_id=str(mcfg.get("binding_id") or ""),
                            )
                        )
                        learning_ok = (
                            bank_config.get("enable_observations") is True
                            and bank_config.get("enable_auto_consolidation") is False
                            and ready_models == len(expected)
                            and synthesis > 0
                        )
                        learning_detail = (
                            f" · observations={'on' if bank_config.get('enable_observations') else 'off'}"
                            f" · auto_consolidation={'on' if bank_config.get('enable_auto_consolidation') else 'scoped'}"
                            f" · mental_models={ready_models}/{len(expected)}"
                            f" · synthesis_injected={synthesis}"
                        )
                    else:
                        learning_ok = False
                        learning_detail = " · learning surface unavailable"
            finally:
                backend.close()
            # auto_retain off는 유효한 선택이지만 무음이면 "2차 메모리에 안 쌓이는" 증상의
            # 원인 조회가 불가능하다 (1차 inject 게이트와 같은 계열의 무음 비활성) — 상태만 명시.
            #
            # 두 손잡이 다 참/거짓이 아니라 세 상태다: 리포 설정을 그대로 읽으면 "리포가
            # 요청했는데 이 기계가 미승인"이 off와 한 칸에 뭉치고, 진단이 그렇게 답하면 이 검사가
            # 있는 이유가 사라진다 (사람은 커밋된 설정을 보고 켜졌다고 믿는 쪽이다).
            gates = {"auto_retain": auto_retain_turns_state(mcfg), "autosave": autosave_state(mcfg)}
            detail = (
                f"engine={engine} · project_id={project_id} · {readiness.status}"
                + f" · binding={binding.binding_id[:8]} · project_uid={binding.project_uid[:8]}"
                + f" · auto_retain={gates['auto_retain']}"
                # 자동저장은 무음이면 안 된다 — 켜져 있으면 "승인한 적 없는 기록"이 쌓이고,
                # 꺼져 있으면 "승인 안 해서 안 쌓인" 것이다. 둘 다 여기서 보여야 구분된다.
                + f" · autosave={gates['autosave']}"
                + (f" · capabilities={','.join(enabled)}" if enabled else "")
                + learning_detail
                + (f" · {readiness.detail}" if readiness.detail else "")
                # unapproved는 결함이 아니라 안전한 기본값이라 ok를 뒤집지 않는다. 그래도 다음
                # 손짓은 여기서 말해야 한다 — 이 사람은 "왜 안 쌓이지"를 물으러 온 사람이다.
                + (
                    " · 미승인 손잡이는 `asgard memory autosave approve --tier project`로 켠다"
                    if GATE_UNAPPROVED in gates.values()
                    else ""
                )
            )
            ok = readiness.status == "ready" and learning_ok
        except Exception as exc:
            detail = f"engine={mcfg.get('engine', 'hindsight')} · unavailable · {type(exc).__name__}: {exc}"
            ok = False
        return {
            "name": "shared memory backend",
            "ok": ok,
            "detail": detail,
            "fix": ("" if ok else "backend 연결을 점검하고 Hindsight면 `asgard memory project-learn --apply` 실행"),
            "security": True,
        }
    except Exception as exc:
        return {
            "name": "shared memory backend",
            "ok": False,
            "detail": f"diagnostic failed closed · {type(exc).__name__}: {exc}",
            "fix": "프로젝트 memory 설정을 점검하고 asgard memory connect 재실행",
            "security": True,
        }


def bank_uninjected_note(root: str) -> str:
    """뱅크는 연결됐는데 이 저장소의 세션에 자동 주입이 안 붙을 때의 한 줄. 붙으면 빈 문자열.

    26-08-07 실측한 형상: 뱅크(vn_onm_yun)는 한 저장소에 등록돼 있고 회수 배선은 **다른**
    저장소에 있었다. 두 사실이 각각 자기 행으로만 보고돼서, 어느 행도 틀리지 않은 채로
    "등록된 뱅크가 어떤 프롬프트에도 안 들어간다"는 결론만 아무도 말하지 않았다.

    판정 대상은 주입 경로 하나다. MCP 브릿지(`memory_recall`)는 사용자 범위 등록이라 배선과
    무관하게 도므로, 여기서 "못 읽는다"고 말하면 그것대로 거짓이 된다 — 안 붙는 것은 자동
    회수다. 설정 파일과 파일 존재만 읽는다 (backend 접속 없음) — 그래서 connect 도 같이 쓴다."""
    from ...memory_bridge import find_config
    from .wiring import memory_wiring_gaps

    found = find_config(root, strict=True)
    if not found:
        return ""
    _, cfg = found
    gaps = memory_wiring_gaps(root)
    if any(not missing for _, missing in gaps):
        return ""
    bank = str(cfg.get("project_id") or cfg.get("bank") or "?")
    where = (
        "이 저장소엔 클라이언트 배선이 하나도 없어요"
        if not gaps
        else " · ".join(f"{name} 빠짐: {', '.join(missing)}" for name, missing in gaps)
    )
    return f"뱅크 {bank} 는 연결됐는데 이 저장소의 세션엔 자동 회수가 안 붙어요 — {where}"


def _bank_reachability_check(root: str) -> dict | None:
    """연결된 뱅크에 주입 경로가 없을 때만 한 줄. 정상이면 행 자체가 없다 (조용한 통과).

    배선 행이 이미 ⚠ 인 경우에도 이 행을 함께 낸다 — 빠진 항목의 목록과 "그래서 뱅크가
    프롬프트에 안 들어간다"는 결론은 다른 문장이고, 사람이 필요한 것은 뒤쪽이다."""
    try:
        note = bank_uninjected_note(root)
    except Exception:
        return None  # 진단 실패는 doctor를 막지 않는다 (fail-open)
    if not note:
        return None
    return {
        "name": "project memory reachability",
        "ok": False,
        "detail": note,
        "fix": "asgard init --force 로 메모리 배선을 깔아요 (뱅크 설정은 병합돼 남고, MCP 명시 조회는 배선과 무관해요)",
    }


def _injection_budget_check(root: str) -> dict | None:
    """자동 주입이 제 시간 안에 실제로 붙는지 — 회수를 한 번 돌려 벽시계로 잰다.

    설정·연결·배선이 다 초록인데도 프롬프트에 아무것도 안 들어가는 상태가 있다. 회수가
    `project_memory.inject_timeout` 보다 느리면 주입 경로는 예외를 삼키고 빈 문자열을 내므로,
    죽은 backend 와 느린 backend 가 화면에서 똑같아 보인다 (26-08-11: 회수 8.1초 대 상한 5초).
    그 둘을 가르는 유일한 방법이 여기서 한 번 재 보는 것이다."""
    try:
        import time

        from ...memory_bridge import find_config, server_recall
        from ...memory_context import INJECTABLE_TAGS, filter_project_hits, inject_timeout

        found = find_config(root, strict=True)
        if not found:
            return None
        mroot, cfg = found
        budget = inject_timeout(cfg)
        probe = "project decision policy incident 결정 정책 사건"
        started = time.perf_counter()
        try:
            candidates = server_recall(cfg, probe, max_results=8, operation_timeout=budget, tags=INJECTABLE_TAGS)
            rows, _ = filter_project_hits(mroot, cfg, candidates, max_results=5, query=probe)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            return {
                "name": "project memory injection",
                "ok": False,
                "detail": f"{type(exc).__name__} after {elapsed:.1f}s · inject_timeout={budget}s — 턴마다 조용히 버려져요",
                "fix": (
                    "리랭커 후보를 줄이거나(docker/asgard-project-memory 의 "
                    "HINDSIGHT_RERANKER_MAX_CANDIDATES) project_memory.inject_timeout 을 올려요"
                ),
            }
        elapsed = time.perf_counter() - started
        if not candidates:
            # 후보 0건은 "이 질의에 답이 없다"가 아니다 — 태그 사전 필터가 아무것도 못 고른
            # 것이고, 뱅크가 confidence 태그보다 먼저 적재됐을 때의 모습이 정확히 이것이다.
            return {
                "name": "project memory injection",
                "ok": False,
                "detail": f"{elapsed:.1f}s · inject_timeout={budget}s · 태그 사전 필터에 걸린 후보 0건",
                "fix": (
                    "자동 주입은 status:active·confidence:verified 태그로 후보를 좁혀요 — 뱅크가 그 태그보다 "
                    "먼저 적재됐다면 `asgard memory project-rehydrate --tags-only` 로 태그만 맞춰요"
                ),
            }
        return {
            "name": "project memory injection",
            "ok": True,
            "detail": f"{elapsed:.1f}s · inject_timeout={budget}s · 후보 {len(candidates)}건 → 주입 {len(rows)}건",
            "fix": "",
        }
    except Exception:
        return None  # 진단 실패는 doctor 를 막지 않는다 (fail-open)


def _personal_memory_check(root: str) -> dict | None:
    """1차(개인) 메모리 주입 게이트 진단 — 무음 차단을 표면화한다.

    26-07-21 실측: 프로젝트 설정이 provider를 선택하면 inject_allowed가 개인 메모리 주입을
    전 세션에서 조용히 끈다 (개인정보 방화벽 — 의도된 기본값). 방화벽 자체는 유지하되,
    "저장은 되는데 어떤 세션도 회상하지 못하는" 상태를 사용자가 볼 수 있어야 한다."""
    try:
        from ...memory import autosave_enabled, inject_allowed, inject_enabled
        from ...providers import resolve

        # 쓰기 쪽 상태도 같은 줄에 넣는다 — 이 검사는 "내 기억이 어떻게 드나드는가"의 창이고,
        # 자동저장은 그 문의 한쪽 짝이다 (읽기=inject, 쓰기=autosave).
        save = f" · autosave={'on' if autosave_enabled() else 'off (승인 필요)'}"
        if not inject_enabled():
            return {
                "name": "personal memory inject",
                "ok": True,
                "detail": "off (kill switch — 의도된 비활성)" + save,
                "fix": "",
            }
        rp = resolve(root)
        if inject_allowed(rp.profile.name, rp.source):
            return {
                "name": "personal memory inject",
                "ok": True,
                "detail": f"on · provider={rp.profile.name}" + save,
                "fix": "",
            }
        return {
            "name": "personal memory inject",
            "ok": False,
            "detail": f"blocked · 프로젝트 선택 provider({rp.profile.name})는 개인 메모리 주입이 기본 거부" + save,
            "fix": f'~/.asgard/asgard-setting-global.json의 "memory".providers에 "{rp.profile.name}" 추가 (명시 허용)',
        }
    except Exception:
        return None  # 진단 실패는 doctor를 막지 않는다 (fail-open)


def _memory_semantic_check() -> dict | None:
    """개인 메모리 시맨틱 스트림 상태 — 켜져 있다는 것과 실제로 도는 것을 구분해 보고한다.

    memory_semantic 계약이 "active()로 활성/비활성을 대시보드·doctor에 그대로 노출한다
    (숨기지 않는다)"고 적어 놓고 배선이 없던 자리다. 기본이 켜진 뒤로는 더 중요해졌다 —
    켠 줄 알았는데 임베더를 못 불러 2경로로 도는 상태가 가장 조용한 실패다.

    실측 근거 (26-07-27, 40페이지·80질의): hit@1 0.750→0.850, 놓친 질의 11→2건, 회귀 0건.
    대가는 프로세스당 로드 ~1.2초, 첫 실행은 모델 내려받기 ~35초·약 1GB."""
    try:
        from ... import memory_semantic

        mode = memory_semantic.mode()
        if mode == "off":
            return {
                "name": "personal memory semantic",
                "ok": True,
                "detail": "off — lexical 2경로로 동작 (명시적으로 끈 상태)",
                "fix": "다시 켜려면 asgard memory semantic on",
            }
        active = memory_semantic.active()
        status = memory_semantic.status()
        if active:
            # 임베더가 준비된 것으로 끝내면 안 된다. 파생 벡터가 정본을 안 덮으면 이 스트림은
            # 매 질의 빈 리스트를 내는데 상태 표면은 전부 "on"이라고 말한다 — 이 기계에서
            # 실제로 그랬다 (26-07-29: 페이지 2장·vec 0행·active True). 남에게 지적한 것과
            # 같은 형태의 거짓 상태라, 커버리지를 같은 칸에서 본다.
            from ... import memory

            coverage = memory.vec_coverage()
            if not coverage["ok"] and coverage["pages"]:
                return {
                    "name": "personal memory semantic",
                    "ok": False,
                    "detail": (
                        f"임베더는 도는데 색인이 정본을 못 덮어요 — "
                        f"{coverage['fresh']}/{coverage['pages']} 페이지"
                        + (f" · 낡음 {coverage['stale']}" if coverage["stale"] else "")
                        + (f" · 고아 {coverage['orphan']}" if coverage["orphan"] else "")
                        + " (덮이지 않은 페이지는 시맨틱 검색에 안 잡혀요)"
                    ),
                    "fix": "asgard memory reindex",
                }
            return {
                "name": "personal memory semantic",
                "ok": True,
                "detail": (
                    f"on · {status.get('model') or '?'} · {status.get('dim') or 0}d"
                    f" · 색인 {coverage['fresh']}/{coverage['pages']}"
                ),
                "fix": "",
            }
        cached = memory_semantic.model_cached()
        return {
            "name": "personal memory semantic",
            "ok": False,
            "detail": (
                f"mode={mode} 인데 임베더를 못 불렀다 — 2경로로 폴백 중"
                + ("" if cached else " (모델을 아직 안 받았어요)")
            ),
            "fix": "asgard memory semantic warmup (실패하면 asgard memory semantic off로 명시적으로 꺼 주세요)",
        }
    except Exception:
        return None  # 진단 실패는 doctor를 막지 않는다 (fail-open)


def _memory_curator_check(root: str) -> dict | None:
    """개인 메모리를 손질하는 provider 진단.

    관리자가 없으면 노른·패턴 학습이 멈춘다. 그런데 저장·검색·회상은 LLM 없이 그대로 돌기
    때문에 사용자에게는 아무 일도 안 일어난 것처럼 보인다 — 조용히 멈춘 자가 진화를 보이게 한다."""
    try:
        from ...memory.manager import describe

        row = describe(root)
        origin = {"main": "메인 provider", "config": "설정 지정", "env": "env override"}.get(
            row["source"], row["source"]
        )
        if row.get("ready"):
            return {
                "name": "personal memory curator",
                "ok": True,
                "detail": f"{row.get('provider')} {row.get('model', '')} ({origin})",
                "fix": "",
            }
        return {
            "name": "personal memory curator",
            "ok": False,
            "detail": "없음 — 노른·패턴 학습이 멈춰요 (저장·검색·회상은 정상)",
            "fix": "asgard memory provider --set <provider>[:<model>] (또는 메인 provider 연결)",
        }
    except Exception:
        return None  # 진단 실패는 doctor를 막지 않는다 (fail-open)


def _dead_local_remote(remote: str) -> bool:
    """설정된 원격이 **로컬 경로인데 사라진** 경우. 원격 URL은 여기서 판정하지 않는다.

    doctor가 물어야 할 것은 "적어 두었는가"가 아니라 "정본이 살아남는가"다. 로컬 경로 원격은
    지워지면 그대로 무효인데 설정 파일에는 그대로 남는다 — 26-07-31 실측: 과거 E2E 세션이 남긴
    `…/.tmp-mem-test/bare`를 가리킨 채 doctor가 내구성 ✔ 를 주고 있었다 (백업 0 · 원격 사망)."""
    path = remote.strip()
    if not path or "://" in path or path.startswith("git@"):
        return False  # URL 형태 — 도달성은 네트워크 없이 못 묻는다 (fail-open)
    return not os.path.exists(os.path.expanduser(path))


def _memory_durability_check() -> dict | None:
    """개인 메모리의 내구성 — 백업 유무와 동기화 원격. 정본이 한 기계에만 있으면 그렇게 말한다."""
    try:
        from ...memory import backup as backup_mod
        from ...memory import sync as sync_mod

        state = backup_mod.state_note()
        remote = sync_mod.status()
        dead = bool(remote["configured"]) and _dead_local_remote(str(remote.get("remote") or ""))
        usable_remote = bool(remote["configured"]) and not dead
        parts = [f"backups {state['count']}" + (f" (latest {state['latest']})" if state["latest"] else "")]
        if dead:
            parts.append(f"remote {remote['transport']} — 경로 없음: {str(remote.get('remote') or '')[:60]}")
        else:
            parts.append(f"remote {remote['transport']}" if remote["configured"] else "remote 미설정")
        if remote["unresolved_conflicts"]:
            parts.append(f"미해결 충돌 {len(remote['unresolved_conflicts'])}")
        # 빈 위키는 잃을 게 없다 — 아직 아무것도 안 적은 사람에게 백업을 재촉하지 않는다
        durable = state["count"] > 0 or usable_remote or remote["local_files"] <= 1
        return {
            "name": "personal memory durability",
            "ok": durable,
            "detail": " · ".join(parts),
            "fix": "" if durable else "asgard memory backup · asgard memory sync --set-remote <path-or-url>",
        }
    except Exception:
        return None


def _document_lane_check(root: str) -> dict | None:
    """로컬 문서 레인 현황 — 레인을 쓰는 저장소에서만 한 줄.

    이 레인의 소비처는 턴 시작 주입 하나뿐이라, 인덱스가 못 서도 화면에서는 "관련 문서 없음"과
    구별이 안 된다. 여기가 그 둘을 가르는 자리다. backend 연결과는 무관하다 — 정본이 저장소에
    있고 인덱스가 로컬이라 서버가 죽어 있어도, 오프라인에서도 도는 레인이다.

    레인을 안 쓰는 저장소는 행 자체를 안 낸다 (`documents.lane_present` 와 같은 계약).
    회수가 읽는 뿌리를 그대로 재려고 `find_config` 의 결과를 먼저 따른다 — 위쪽 폴더가
    프로젝트 메모리를 적었으면 주입도 그 폴더의 정본을 읽는다."""
    try:
        from ...memory_bridge import find_config
        from ...project_memory import documents

        found = find_config(root)
        lane_root = found[0] if found else os.path.realpath(root)
        if not documents.lane_present(lane_root):
            return None
        info = documents.stats(lane_root)
    except Exception:
        return None  # 진단 실패는 doctor 를 막지 않는다 (fail-open)
    where = "" if os.path.realpath(lane_root) == os.path.realpath(root) else f" · {lane_root}"
    if info["error"]:
        return {
            "name": "project document lane",
            "ok": False,
            "detail": f"문서 {info['documents']}건 · 인덱스 불능: {info['error']}{where}",
            "fix": (
                f"인덱스는 파생물이라 지우면 다시 생겨요 — {documents.INDEX_RELATIVE_PATH} 를 지우고 다시 조회해요 "
                "(정본 문서는 그대로예요)"
            ),
        }
    return {
        "name": "project document lane",
        "ok": True,
        "detail": f"문서 {info['documents']}건 · 조각 {info['chunks']}개 · 정본 {info['bytes']:,}B{where}",
        "fix": "",
    }
