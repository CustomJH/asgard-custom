"""doctor — 엔진 검사. 모델 티어·디자인 엔진·node·문서 도구·엔진 도달성."""

import os
import sys
from pathlib import Path

from ...platform import on_path


def _model_tier_check(root: str) -> dict | None:
    """역할 티어가 실제로 어떤 모델로 해석되는지 — 표가 낡으면 여기서 보인다.

    26-07-26 실측: 티어 표가 이전 세대에 박혀 있어 opus 세션이 역할 턴마다 조용히 내려갔는데
    어느 표면에도 드러나지 않았다. 해석 결과를 보여 주고, API 모드면 카탈로그로 캐시를 갱신한다
    (claude CLI 모드는 계열 별칭이라 갱신 대상이 아니다 — CLI가 최신 세대로 해석한다)."""
    try:
        from ...model_tiers import TIERS, refresh
        from ...providers import resolve

        rp = resolve(root)
        table, source = refresh(rp.profile.name, rp.profile.api_mode, rp.api_key or "")
        if not table:
            return {
                "name": "model tiers",
                "ok": True,
                "detail": f"n/a · {rp.profile.name}은 티어 매핑 없음 (설정 모델 그대로 사용)",
                "fix": "",
            }
        shown = " · ".join(f"{tier}={table[tier]}" for tier in TIERS)
        return {"name": "model tiers", "ok": True, "detail": f"{source} · {shown}", "fix": ""}
    except Exception:
        return None


def _freyja_engine_dir() -> Path:
    """Freyja 2 엔진 루트 — 훅 매니페스트의 `${FREYJA2_ENGINE}`가 가리키는 그 경로.

    번들 플러그인은 설치본에서 그 자리 그대로 실행되므로(복사 설치가 아니다) 경로는
    레지스트리가 아는 자산 루트에서 유도한다 — 두 곳이 갈라지지 않게.
    """
    from ...skill_registry import _BUNDLED_PLUGINS_DIR

    return Path(_BUNDLED_PLUGINS_DIR) / "freyja2/skills/asgard-freyja2/engine"


def _design_engine_checks() -> list[dict]:
    """디자인 엔진이 *실제로 완전체로* 실려 왔는지.

    엔진2의 정적 HTML 검출기는 htmlparser2·css-select·css-tree·domutils를 bare import
    하고, 실패하면 경고 없이 정규식 경로로 되돌아간다. 원본 대조에서 그 폴백 상태의
    검출력이 규칙 40종→15종이었다 — 조용하기 때문에 쓰는 쪽은 깨끗한 페이지와 구별할 수
    없다. 그래서 번들을 휠에 실었고, 여기서 그 존재와 node 런타임을 확인한다.
    """
    engine = _freyja_engine_dir()
    checks: list[dict] = []
    bundle = engine / "scripts/detector/vendor/static-parser.mjs"
    checks.append(
        {
            "name": "freyja2 static parser",
            "ok": bundle.is_file(),
            "detail": f"vendored ({bundle.stat().st_size // 1024}KB)"
            if bundle.is_file()
            else "missing — detector runs regex-only",
            "fix": "재설치하면 돌아와요: asgard update (휠에 동봉돼 있어 별도 설치 없음)",
        }
    )
    # 3D 엔진(브리싱아멘)의 값어치는 검증 런타임에 있다 — 스크립트가 빠지면 형상을 측정하지
    # 못한 채 "만들었다"만 남는다. 엔진2 번들과 같은 이유로 존재를 확인한다.
    from ...skill_registry import _BUNDLED_PLUGINS_DIR

    scripts = Path(_BUNDLED_PLUGINS_DIR) / "freyja-3d/skills/asgard-freyja-3d/engine/scripts"
    # cad 레인의 입구는 `cad.py` 다. 예전 이름 `cad_build.py` 를 그대로 물고 있어서, 파일이
    # 멀쩡히 있는 설치에서도 doctor 가 매번 "missing" 을 냈다 (26-08-05).
    required = ("shoot.mjs", "mesh_audit.mjs", "scene_audit.mjs", "detect3d.mjs", "preflight.mjs", "cad.py")
    missing = [name for name in required if not (scripts / name).is_file()]
    checks.append(
        {
            "name": "freyja 3d runtime",
            "ok": not missing,
            "detail": f"{len(required)} scripts bundled" if not missing else f"missing: {', '.join(missing)}",
            "fix": "재설치하면 돌아와요: asgard update (휠에 동봉 — 렌더·측정·검출이 전부 이 스크립트에 있어요)",
        }
    )

    # 엔진4(마르될)는 규칙 코퍼스 + 결정론 게이트다. 게이트가 빠지면 남는 건 자기채점뿐이고,
    # 자기채점은 리뷰가 아니다 — 그래서 코퍼스가 아니라 판정기의 존재를 본다.
    gate = Path(_BUNDLED_PLUGINS_DIR) / "freyja4/skills/asgard-freyja4/engine/scripts/slop_gate.mjs"
    themes = Path(_BUNDLED_PLUGINS_DIR) / "freyja4/skills/asgard-freyja4/references/tokens.css"
    gate_missing = [
        label for label, path in (("slop_gate.mjs", gate), ("references/tokens.css", themes)) if not path.is_file()
    ]
    checks.append(
        {
            "name": "freyja4 gate runtime",
            "ok": not gate_missing,
            "detail": "gate + 20-theme tokens bundled" if not gate_missing else f"missing: {', '.join(gate_missing)}",
            "fix": "재설치하면 돌아와요: asgard update (게이트가 없으면 슬롭 판정이 자기보고로 되돌아가요)",
        }
    )

    checks.append(_node_check())
    return checks


def _node_check() -> dict:
    """엔진 스크립트 런타임. 번들 존재 확인과 갈라 두는 이유: 실려 왔는가와 **돌릴 수 있는가**는
    다른 실패다. 파일은 다 있는데 node가 없으면 처방이 `asgard update`가 아니라 node 설치다."""
    node = on_path("node")
    version = ""
    if node:
        import subprocess

        try:
            version = subprocess.run(
                [node, "-v"], capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
            ).stdout.strip()
        except Exception:
            version = ""
    head = version.lstrip("v").split(".")[0]
    major = int(head) if head.isdigit() else 0
    return {
        "name": "node (design engines)",
        # 엔진 스크립트는 node >= 22를 요구한다. 없으면 프레이야 자체는 돌지만
        # 검출기·훅·live가 전부 죽으므로 침묵보다 경고가 낫다.
        "ok": bool(node) and major >= 22,
        "detail": (f"{version} · {node}" if node else "not found") + ("" if major >= 22 else " — need >= 22"),
        "fix": "install node >= 22 — https://nodejs.org (프레이야 엔진1·2·3D 스크립트 런타임)",
    }


def _office_checks() -> list[dict]:
    """Sága 문서 계층. 생성·읽기·검증은 순수 파이썬이라 항상 서야 하고, 렌더만 외부 관문이다."""
    from ...skill_registry import _BUNDLED_PLUGINS_DIR

    checks: list[dict] = []
    missing = []
    for label, module in (("python-docx", "docx"), ("python-pptx", "pptx"), ("openpyxl", "openpyxl")):
        try:
            __import__(module)
        except ImportError:
            missing.append(label)
    checks.append(
        {
            "name": "office engines",
            "ok": not missing,
            "detail": "docx · pptx · xlsx bundled" if not missing else f"missing: {', '.join(missing)}",
            "fix": "재설치하면 돌아와요: asgard update (기본 의존성 — 빠지면 문서 생성 자체가 죽어요)",
        }
    )

    scripts = Path(_BUNDLED_PLUGINS_DIR) / "asgard-office/skills/asgard-office/scripts"
    required = ("build_docx.py", "build_pptx.py", "build_xlsx.py", "extract.py", "verify.py", "fill.py", "outline.py")
    absent = [name for name in required if not (scripts / name).is_file()]
    checks.append(
        {
            "name": "office lanes",
            "ok": not absent,
            "detail": f"{len(required)} lane scripts bundled" if not absent else f"missing: {', '.join(absent)}",
            "fix": "재설치하면 돌아와요: asgard update (휠에 동봉 — 생성·읽기·검증이 전부 이 스크립트에 있어요)",
        }
    )

    # 렌더는 없어도 되는 게 정상이다. 관문이 없다는 사실만 정확히 알리고 실패로 세지 않는다.
    soffice = on_path("soffice") or on_path("libreoffice") or os.environ.get("ASGARD_SOFFICE", "")
    if not soffice and sys.platform == "darwin" and Path("/Applications/LibreOffice.app").exists():
        soffice = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    checks.append(
        {
            "name": "office render gate",
            "ok": True,
            "detail": (soffice or "LibreOffice not found — verify still runs, render and --recalc do not"),
            "fix": "선택 사항: brew install --cask libreoffice (PDF·페이지 이미지·수식 재계산에만 쓰인다)",
        }
    )
    return checks


def _engine_reachable_check(root: str) -> list[dict]:
    """이 자리에 설정된 엔진이 **지금 이 프로세스에서** 실제로 닿는가.

    여태 doctor는 아스가르드 자신은 PATH에서 찾으면서 정작 일을 시킬 엔진은 안 봤다.
    그래서 창이 독에서 서면(셸을 안 거쳐 PATH가 넉 줄로 줄어든다) `claude`가 안 보이는데도
    점검은 전부 초록이었고, 사용자에게 남는 것은 "왜 아무것도 안 되지"뿐이었다.

    PATH를 되찾은 뒤에도 못 찾으면 그건 진짜로 없는 것이다 — 그때만 처방을 말한다."""
    from ...platform import ensure_user_path
    from ...providers import resolve

    ensure_user_path()
    try:
        rp = resolve(root)
    except Exception as exc:
        return [{"name": "engine", "ok": False, "detail": f"{type(exc).__name__}: {exc}", "fix": "asgard start"}]
    rows = [
        {
            "name": "engine",
            "ok": not rp.missing,
            "detail": f"{rp.profile.display} · {rp.model or '—'} ({rp.source})"
            + ("" if not rp.missing else " — " + "; ".join(rp.missing)),
            "fix": "asgard start에서 엔진을 연결하거나 창의 설정 → 기본 모델",
        }
    ]
    if rp.profile.api_mode == "claude_cli":
        cli = on_path("claude")
        rows.append(
            {
                "name": "claude CLI",
                "ok": bool(cli),
                "detail": cli or "not found",
                "fix": "https://claude.com/claude-code 설치 후 claude /login (구독) 또는 CLAUDE_CODE_OAUTH_TOKEN export",
            }
        )
    elif rp.profile.api_mode == "codex_responses":
        from ...openai_codex import login_status

        ok, detail = login_status()
        rows.append(
            {
                "name": "ChatGPT OAuth",
                "ok": ok,
                "detail": detail,
                "fix": "asgard auth login openai-native (스톡 Codex CLI 로그인과 별개예요 — 아스가르드가 자기 세션을 들어요)",
            }
        )
    return rows
