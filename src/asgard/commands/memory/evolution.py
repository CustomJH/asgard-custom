"""memory 커맨드 — 자가진화와 되묻기. 노른 패스·패턴 채굴·질문."""

import json as _json
import os

from ... import errors, memory, ui
from ._core import _emit, _fail, _guard


def run_norn(
    apply: bool = False, nudge: bool = False, json_out: bool = False, auto: bool = False, wake: bool = False
) -> int:
    """노른 패스 — LLM 제안 델타를 결정적 검증으로 거른 뒤, --apply 시에만 커밋한다.

    자율 계층 (오딘 결정 26-07-24): --wake(훅)는 due 시 모드에 따라 백그라운드 --auto를
    분리 스폰하거나(safe/full) 넛지만 남긴다(off). --auto는 자격 op만 즉시 자동 적용."""

    def _do() -> int:
        from ...memory import norn as norn_mod

        d = memory.ensure_home()
        if wake:  # 훅 소비 표면 — 판정·등급 분기·latch·스폰은 전부 norn.wake 단일 출처
            line = norn_mod.wake(os.getcwd(), d)
            if line:
                print(line)
            return 0
        if auto:  # 자율 실행 본체 — 모드 자격분만 적용, 잔류분은 제안으로 보고
            result = norn_mod.run_auto(os.getcwd(), d)
            if json_out:
                print(_json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            ui.head(f"위그드라실 노른 자동 통합 · 모드 {result['mode']}")
            for op in result["applied"]:
                if op["op"] == "insight":
                    ui.ok(f"insight 기록 · {op['title']} ({op['confidence']}) ← {', '.join(op['sources'])}")
                elif op["op"] == "contradiction":
                    ui.warn(f"contradiction · {op['a']} ↔ {op['b']} — 사람이 해소")
                else:
                    ui.ok(f"{op['op']} · {op.get('slug') or op.get('src', '')}")
            for op in result["proposed"]:
                flag = f" ⚠ 극성 충돌 [{op['polarity_conflict']}]" if op.get("polarity_conflict") else ""
                ui.step(f"제안 잔류 · {op['op']}{flag} — asgard memory norn으로 검토")
            if result["report"]:
                ui.step(f"리포트 · {os.path.relpath(result['report'], d)}")
            if not result["applied"] and not result["proposed"]:
                ui.ok("고칠 것도 제안할 것도 없어요 — 위키가 이미 정돈돼 있네요")
            return 0
        if nudge:  # 훅 소비 표면 — due + latch 통과 시 한 줄, 그 외 침묵
            line = norn_mod.nudge_line(d)
            if line:
                print(line)
            return 0
        due, reason = norn_mod.norn_due(d)
        plan = norn_mod.plan_norn(os.getcwd(), d)
        if json_out and not apply:
            print(
                _json.dumps(
                    {"due": due, "reason": reason, **{k: plan[k] for k in ("ops", "dropped")}},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        ui.head(f"위그드라실 노른 · {'due — ' + reason if due else reason}")
        if not plan["ops"] and not plan["dropped"]:
            ui.ok("제안할 게 없어요 — 위키가 이미 정돈돼 있네요")
            return 0
        for op in plan["ops"]:
            if op["op"] == "merge":
                ui.step(f"merge · {op['src']} → {op['dst']} (sim {op['sim']}) — {op['why']}")
            elif op["op"] == "archive":
                ui.step(f"archive · {op['slug']} — {op['why']}")
            elif op["op"] == "insight":
                ui.step(f"insight · {op['title']} ({op['confidence']}) ← {', '.join(op['sources'])}")
                # 적용 전에 반드시 보여야 하는 표식 — 출처의 주장을 뒤집었을 수 있다는 신호다.
                if flag := op.get("polarity_conflict"):
                    ui.warn(f"  ⚠ 극성 충돌 [{flag}] — 출처와 대조하고 적용할 것")
            else:
                ui.warn(f"contradiction · {op['a']} ↔ {op['b']} — {op['why']}")
        for row in plan["dropped"]:
            ui.step(ui.dim(f"기각 · {row['op'].get('op', '?')} — {row['reason']}"))
        if not apply:
            ui.warn("아직 적용하지 않음 — 검토 후 asgard memory norn --apply")
            return 0
        result = norn_mod.apply_norn(d, plan)
        if json_out:
            print(_json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        for op in result["failed"]:
            ui.fail(f"{op['op']} 실패 — {op.get('error', '')}")
        ui.ok(
            f"노른 적용: {len(result['applied'])}건 (실패 {len(result['failed'])}건) · "
            f"리포트 {os.path.relpath(result['report'], d)}"
            + (f" · 백업 {os.path.relpath(result['backup'], d)}" if result["backup"] else "")
        )
        return 0 if not result["failed"] else 1

    return _guard(_do)


def run_norn_restore(slug: str, json_out: bool = False) -> int:
    """노른 archive 복원 — 최신 아카이브 스냅샷을 pages/ 로 되돌린다."""
    errors.set_json_surface(json_out)

    def _do() -> int:
        from ...memory.norn import restore_page

        if restore_page(slug):
            if json_out:
                _emit({"slug": slug, "restored": True})
            else:
                ui.ok(f"복원됨: {slug}")
            return 0
        return _fail(
            f"아카이브에 없음: {slug}",
            code="not_found",
            remedy="asgard memory norn으로 어떤 페이지가 치워졌는지 먼저 보세요",
            detail={"slug": slug},
        )

    return _guard(_do)


def run_pattern(apply: bool = False, json_out: bool = False, due_only: bool = False) -> int:
    """패턴 학습 — 대화 원문에서 오딘 관측을 뽑아 개인 위키로 승격 (기본 dry-run)."""

    def _do() -> int:
        from ...memory import pattern
        from ...memory.manager import ManagerUnavailable

        root, d = os.getcwd(), memory.ensure_home()
        if due_only:  # 훅 소비 표면 — due + latch 통과 시 한 줄, 그 외 침묵
            if json_out:
                due, why = pattern.pattern_due(root, d)
                print(_json.dumps({"due": due, "reason": why}, ensure_ascii=False))
                return 0
            line = pattern.nudge_line(root, d)
            if line:
                print(line)
            return 0
        try:
            plan = pattern.plan_pattern(root, d)
        except Exception as exc:
            # 관리자가 없든 호출이 실패했든 패턴 학습만 멈춘다 — 저장·검색·회상은 무LLM 경로다
            reason = str(exc) if isinstance(exc, ManagerUnavailable) else f"{type(exc).__name__}: {exc}"
            ui.warn(f"패턴 학습을 못 돌렸어요 — {reason}")
            ui.step("`asgard memory provider --set <provider>`로 관리자를 정하거나, 메인 provider를 고쳐 주세요")
            return 1
        if not apply:
            if json_out:
                print(_json.dumps(plan, ensure_ascii=False, indent=2, default=str))
                return 0
            ui.head(f"pattern plan · {len(plan.get('turns') or [])} turn(s) 검토")
            for row in plan["observations"]:
                ui.step(
                    f"{row['kind']} · {row['text'][:90]} "
                    f"({row['confidence']}, grounding {row['grounding']}, turns {row['evidence']})"
                )
            for row in plan["dropped"]:
                ui.warn(f"기각 · {str(row['observation'].get('text', ''))[:70]} — {row['reason']}")
            if not plan["observations"]:
                ui.ok(plan.get("reason") or "승격할 관측 없음")
            else:
                ui.ok(f"{len(plan['observations'])}건 승격 대기 — 적용하려면 --apply")
            return 0
        result = pattern.apply_pattern(root, plan, d)
        if json_out:
            print(_json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0 if not result["failed"] else 1
        for row in result["failed"]:
            ui.fail(f"{row['kind']} 실패 — {row.get('error', '')}")
        ui.ok(
            f"패턴 적용: {len(result['applied'])}건 (실패 {len(result['failed'])}건) · "
            f"리포트 {os.path.relpath(result['report'], d)}"
            + (f" · peer card [[{result['peer_card']}]]" if result["peer_card"] else "")
        )
        return 0 if not result["failed"] else 1

    return _guard(_do)


def run_ask(question: str, k: int = 5, json_out: bool = False) -> int:
    """오딘에 대한 자연어 질문 — 개인 관측·에피소드·프로젝트 메모리를 근거로 답한다."""

    def _do() -> int:
        from ...memory import pattern
        from ...memory.manager import ManagerUnavailable

        root, d = os.getcwd(), memory.ensure_home()
        try:
            result = pattern.ask(question, root, d, k=k)
        except Exception as exc:
            # provider가 없든(ManagerUnavailable) 있는데 실패했든(호출 중 오류) 결과는 같다:
            # 합성은 못 하지만 근거는 이미 손에 있다. 회수까지 같이 죽일 이유가 없다.
            reason = str(exc) if isinstance(exc, ManagerUnavailable) else f"{type(exc).__name__}: {exc}"
            ui.warn(f"답을 못 만들었어요 — {reason}")
            evidence = pattern.gather_evidence(question, root, d, k=k)
            if json_out:
                print(_json.dumps({"answer": "", "evidence": evidence, "error": reason}, ensure_ascii=False, indent=2))
                return 1
            for rows in evidence.values():
                for row in rows:
                    ui.step(f"[{row['id']}] {row['text'][:160]}")
            ui.step("근거만 보여드려요 — 합성은 provider를 고친 뒤에 다시 해 주세요")
            return 1
        if json_out:
            print(_json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["used"] else 1
        if not result["used"]:
            ui.warn("근거가 없어요 — 개인 위키에도, 에피소드에도, 프로젝트 메모리에도 관련 기록이 없네요")
            return 1
        counts = {scope: len(rows) for scope, rows in result["evidence"].items() if rows}
        ui.head("memory ask · " + " · ".join(f"{scope} {n}" for scope, n in counts.items()))
        print(result["answer"])
        return 0

    return _guard(_do)


def run_backup(
    action: str = "create",
    name: str = "",
    label: str = "",
    keep: int = 0,
    json_out: bool = False,
) -> int:
    """개인 메모리 정본 백업 — create/list/restore/verify/prune."""

    def _do() -> int:
        from ...memory import backup as mb

        d = memory.ensure_home()
        keep_n = keep or mb.KEEP_DEFAULT
        if action == "list":
            rows = mb.listing(d)
            if json_out:
                print(_json.dumps({"backups": rows}, ensure_ascii=False, indent=2))
                return 0
            ui.head(f"memory backups · {len(rows)}건 · {os.path.join(d, mb.BACKUPS_DIR)}")
            for row in rows:
                ui.step(f"{row['name']} · {row['bytes'] / 1024:.1f} KiB")
            if not rows:
                ui.warn("백업이 없어요 — `asgard memory backup`으로 첫 스냅샷을 만들어 보세요")
            return 0
        if action == "verify":
            summary = mb.verify(mb.resolve(d, name or "latest"))
            if json_out:
                print(_json.dumps(summary, ensure_ascii=False, indent=2))
            else:
                ui.ok(f"무결성 확인: {os.path.basename(summary['path'])} · {summary['members']} member(s)")
            return 0
        if action == "restore":
            summary = mb.restore(name or "latest", d)
            if json_out:
                print(_json.dumps(summary, ensure_ascii=False, indent=2))
            else:
                ui.ok(
                    f"복원됨: {summary['restored']} · {summary['pages']} page(s) 재색인 · "
                    f"직전 상태는 {summary['safety_backup']}로 보관"
                )
            return 0
        if action == "prune":
            removed = mb.prune(d, keep=keep_n)
            if json_out:
                print(_json.dumps({"pruned": removed, "keep": keep_n}, ensure_ascii=False, indent=2))
            else:
                ui.ok(f"정리됨: {len(removed)}건 삭제 · 최신 {keep_n}건 유지")
            return 0
        summary = mb.create(d, label=label, keep=keep_n)
        mb.write_manifest_sidecar(d, summary)
        if json_out:
            print(_json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            ui.ok(
                f"백업됨: {summary['name']} · {summary['pages']} page(s)"
                + (f" · archive {summary['archived']}" if summary["archived"] else "")
            )
        return 0

    return _guard(_do)


def run_sync(
    set_remote: str = "",
    transport: str = "dir",
    branch: str = "main",
    unset: bool = False,
    dry_run: bool = False,
    adopt: bool = False,
    status_only: bool = False,
    json_out: bool = False,
) -> int:
    """개인 메모리 서버 연동 — dir(공유 폴더) 또는 git(원격 저장소) 전송."""

    def _do() -> int:
        from ...memory import sync as ms

        if unset:
            ms.clear_settings()
            ui.ok("동기화 원격 해제됨")
            return 0
        if set_remote:
            saved = ms.save_settings(set_remote, transport=transport, branch=branch)
            ui.ok(f"동기화 원격 설정: transport={saved['transport']} · {saved['remote']}")
            if not status_only:
                return 0
        if status_only:
            state = ms.status()
            if json_out:
                print(_json.dumps(state, ensure_ascii=False, indent=2))
                return 0
            ui.head("memory sync status")
            ui.step(f"remote · {state['remote'] or '미설정'} ({state['transport'] or '-'})")
            ui.step(f"last sync · {state['last_sync'] or '없음'}")
            ui.step(f"tracked · {state['tracked']} / local {state['local_files']}")
            if state["unresolved_conflicts"]:
                ui.warn(f"아직 안 풀린 충돌이 {len(state['unresolved_conflicts'])}건 있어요 — conflicts/를 봐 주세요")
            return 0
        result = ms.sync(dry_run=dry_run, adopt=adopt)
        if json_out:
            print(_json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if not result.get("conflict") else 1
        head = "sync plan" if dry_run else "sync"
        ui.head(f"memory {head} · {result['transport']} · {result['remote']}")
        if result["transport"] == "git":
            if result.get("conflict"):
                ui.fail("원격과 갈라졌어요 — 메모리 홈에서 직접 정리해 주셔야 해요")
                ui.step(f"git -C {memory.memory_dir()} pull --rebase origin {result['branch']}")
                return 1
            if dry_run:
                for path in result.get("pending", []):
                    ui.step(f"pending · {path}")
                if not result.get("pending"):
                    ui.ok("로컬 변경 없음")
                return 0
            ui.ok(
                f"committed={len(result.get('committed', []))} pushed={result.get('pushed')} "
                f"head={result.get('head', '') or '-'}"
            )
            if not result.get("pushed"):
                ui.warn(result.get("detail", "") or "push를 못 했어요 — 원격 권한을 확인해 주세요")
                return 1
            return 0
        for key, verb in (
            ("push", "push"),
            ("pull", "pull"),
            ("delete_local", "delete local"),
            ("delete_remote", "delete remote"),
            ("merge", "merge log"),
        ):
            for path in result.get(key, []):
                ui.step(f"{verb} · {path}")
        for path in result.get("conflict", []):
            ui.warn(f"conflict · {path}")
        if result.get("conflict_copies"):
            ui.warn(f"원격본 보존: {len(result['conflict_copies'])}건 → conflicts/ (로컬 정본은 유지)")
        moved = sum(len(result.get(k, [])) for k in ("push", "pull", "delete_local", "delete_remote", "merge"))
        if dry_run:
            ui.ok(
                f"계획 {moved}건 · 충돌 {len(result.get('conflict', []))}건 — 실제로 적용하려면 --dry-run을 빼 주세요"
            )
        else:
            ui.ok(f"동기화 완료: {moved}건 반영 · 충돌 {len(result.get('conflict', []))}건")
        return 1 if result.get("conflict") else 0

    return _guard(_do)
