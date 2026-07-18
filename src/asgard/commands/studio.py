"""studio — 세스룸니르 생성 파이프라인의 첫 구간 (CUS-261 generate 슬라이스).

브리프 → 프로젝트 스캐폴드 → Heimdall 헤드리스 1회(라우터가 프레이야/편대·시각 게이트로
디스패치) → 자기완결 HTML 아티팩트. 시나리오 라우터·discovery/critique 단계는 CUS-261
본체 잔여 — 실행 기록(runs.jsonl)에 stage 필드를 남겨 후속 단계가 이어붙일 수 있게 한다.

디스크 계약 (studio_dashboard.data 와 공유):
  projects/<slug>/project.json   메타 (name·brief·created·updated)
  projects/<slug>/.studio/       스튜디오 북키핑 — state.json(현재 실행)·runs.jsonl(이력)·run.log
                                 (숨김 디렉터리 = 아티팩트 목록에서 자동 제외)
  projects/<slug>/index.html     산출 아티팩트 (자기완결 단일 HTML, assets/ 허용)
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

from .. import ui
from .studio_dashboard.data import (
    BOOK,
    ENGINES,
    META,
    PROJECTS,
    RUN_LOG,
    RUNS,
    SETTINGS,
    STATE,
    engine,
    ensure_home,
    read_settings,
    slug_ok,
    studio_dir,
    template_file,
    template_meta,
)

# 산출 계약 — 프롬프트에 그대로 주입된다. 게이트는 프롬프트를 신뢰하지 않는다:
# 아티팩트 존재는 run 기록 시점에 디스크에서 다시 센다.
_TASK_TEMPLATE = """[세스룸니르 스튜디오 생성 과업]
브리프:
{brief}

산출 계약 (반드시 지켜라):
- 이 디렉터리에 자기완결 단일 HTML 아티팩트 `index.html` 을 생성하거나 갱신하라.
- 외부 CDN·원격 폰트·원격 이미지 등 네트워크 로드 금지 — CSS/JS 는 인라인, 그림은 인라인 SVG 또는 data URI.
- 보조 파일이 꼭 필요하면 `assets/` 아래에만 두어라.
- 브리프가 요구하지 않는 프레임워크·빌드 도구를 도입하지 마라.
- 완성 후 생성/갱신한 파일 목록을 보고하라."""


def slugify(text: str, d: str | None = None) -> str:
    """브리프/이름 → 유일 슬러그. ascii 밖 문자는 걷어내고, 비면 studio-<n>, 충돌엔 -2·-3…"""
    base = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:40].strip("-")
    d = d or studio_dir()
    root = os.path.join(d, PROJECTS)
    if not base or not slug_ok(base):
        n = 1
        while os.path.exists(os.path.join(root, f"studio-{n}")):
            n += 1
        return f"studio-{n}"
    slug, n = base, 2
    while os.path.exists(os.path.join(root, slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _pdir(slug: str, d: str | None = None) -> str:
    return os.path.join(d or studio_dir(), PROJECTS, slug)


def create_project(brief: str, name: str | None = None, d: str | None = None) -> dict:
    """프로젝트 스캐폴드 — 디렉터리 + project.json + 북키핑 + git 초기화. 생성은 하지 않는다."""
    d = ensure_home(d)
    slug = slugify(name or brief, d)
    pdir = _pdir(slug, d)
    os.makedirs(os.path.join(pdir, BOOK), exist_ok=True)
    meta = {
        "name": (name or brief).strip().splitlines()[0][:80],
        "brief": brief.strip(),
        "created": _now_iso(),
        "updated": _now_iso(),
    }
    with open(os.path.join(pdir, META), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    _ensure_git(pdir)
    return {"slug": slug, "dir": pdir, **meta}


# 엔진 별칭 — CLI/대시보드 입력을 provider 이름으로 정규화
_ENGINE_ALIASES = {
    "claude": "claude-native",
    "claude-code": "claude-native",
    "claude-native": "claude-native",
    "codex": "openai-native",
    "openai-native": "openai-native",
}


def set_engine(name: str, d: str | None = None) -> str | None:
    """생성 엔진 전환 — Claude Code CLI(claude-native) ↔ Codex CLI(openai-native).
    settings.json 에 저장, 이후 모든 생성 실행의 기본 provider 가 된다."""
    provider = _ENGINE_ALIASES.get(name.strip().lower())
    if provider not in ENGINES:
        return None
    d = ensure_home(d)
    settings = read_settings(d)
    settings["engine"] = provider
    with open(os.path.join(d, SETTINGS), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=1)
    return provider


def use_template(name: str, brief: str | None = None, d: str | None = None) -> dict | None:
    """템플릿 → 즉시 프로젝트 스캐폴드 (무 LLM).
    디자인 템플릿은 example.html 이 곧 첫 아티팩트, 미디어 템플릿은 prompt.json 재료.
    이후 다듬기는 스레드 추가 지시(재생성)가 맡는다."""
    t = template_meta(name)
    if t is None:
        return None
    default_brief = f"템플릿 '{t['title']}' 기반. {t.get('desc') or ''}".strip()
    p = create_project(brief or default_brief, name=t["title"], d=d)
    pdir = p["dir"]
    if t.get("kind") == "design":
        for rel, out in (("example.html", "index.html"), ("SKILL.md", os.path.join(BOOK, "template-skill.md"))):
            got = template_file(name, rel)
            if got is not None:
                path = os.path.join(pdir, out)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(got[1])
    else:
        got = template_file(name)
        if got is not None:
            with open(os.path.join(pdir, "prompt.json"), "wb") as f:
                f.write(got[1])
    record = {
        "ts": _now_iso(),
        "stage": "template",
        "status": "ok",
        "wall_s": 0.0,
        "tokens": 0,
        "artifacts": _count_artifacts(pdir),
        "note": f"템플릿 편입: {name}",
    }
    with open(os.path.join(pdir, BOOK, RUNS), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    _write_state(pdir, {"status": "ok", "finished": _now_iso(), "template": name})
    with contextlib.suppress(Exception):  # 템플릿 편입도 증거 트리에 (fail-open)
        subprocess.run(["git", "add", "-A"], cwd=pdir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", f"🎨 studio: template {name}"], cwd=pdir, check=True, capture_output=True
        )
    return {**p, "template": name}


def append_instruction(slug: str, text: str, d: str | None = None) -> bool:
    """대시보드 스레드의 추가 지시 → 브리프에 병합 (refine-lite — 본격 refine 은 CUS-261).
    다음 생성 실행이 병합된 브리프 전체를 본다."""
    pdir = _pdir(slug, d)
    if not slug_ok(slug) or not os.path.isdir(pdir) or not text.strip():
        return False
    meta = _read_meta(pdir)
    brief = str(meta.get("brief") or "").rstrip()
    meta["brief"] = (brief + f"\n\n[추가 지시 {_now_iso()}] " + text.strip()).strip()
    meta["updated"] = _now_iso()
    with open(os.path.join(pdir, META), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return True


def _ensure_git(pdir: str) -> None:
    """프로젝트 = 독립 git 저장소 — Trinity 쓰기 퀘스트가 HEAD·시작 트리 캡처를 요구한다.
    북키핑(.studio)·에이전트 상태(.asgard)는 증거 트리 밖. 실패해도 스캐폴드는 유효(fail-open,
    이후 생성 실행이 Trinity 거부 사유를 그대로 보고한다)."""
    try:
        if not os.path.isdir(os.path.join(pdir, ".git")):
            subprocess.run(["git", "init", "-q"], cwd=pdir, check=True, capture_output=True)
        # .asgard 는 quest_dir 이 자체 .asgard/.gitignore 로 격리한다 — 프로젝트 .gitignore 에
        # 넣으면 quest 스냅샷의 명시 pathspec(:(exclude).asgard)과 충돌해 git add 가 실패한다.
        gi = os.path.join(pdir, ".gitignore")
        if not os.path.exists(gi):
            with open(gi, "w", encoding="utf-8") as f:
                f.write(".studio/\n")
        head = subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=pdir, capture_output=True)
        if head.returncode != 0:  # 첫 커밋 — 캡처 가능한 시작 트리
            subprocess.run(["git", "add", "-A"], cwd=pdir, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "🎨 studio: project scaffold"],
                cwd=pdir,
                check=True,
                capture_output=True,
            )
    except Exception:
        pass


def _read_meta(pdir: str) -> dict:
    try:
        with open(os.path.join(pdir, META), encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _write_state(pdir: str, state: dict) -> None:
    book = os.path.join(pdir, BOOK)
    os.makedirs(book, exist_ok=True)
    with open(os.path.join(book, STATE), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def _count_artifacts(pdir: str) -> int:
    from .studio_dashboard.data import _artifact_names

    return len(_artifact_names(pdir))


def run_generation(
    slug: str,
    d: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    on_text=None,
) -> int:
    """생성 실행 — 프로젝트 디렉터리를 root 로 Heimdall.handle 1회 (run_prompt 와 같은
    헤드리스 계약, ASGARD_UNATTENDED). 라우팅·프레이야 편대·시각 게이트는 Heimdall 몫.

    exit code: 0 정상 / 1 ⚠ 보고 / 2 프리플라이트 실패."""
    d = d or studio_dir()
    pdir = _pdir(slug, d)
    if not slug_ok(slug) or not os.path.isdir(pdir):
        ui.fail(f"unknown studio project: {slug}")
        return 2
    meta = _read_meta(pdir)
    brief = str(meta.get("brief") or "").strip()
    if not brief:
        ui.fail(f"project {slug} has no brief — project.json 을 확인하세요")
        return 2

    _ensure_git(pdir)  # 기존 프로젝트(재생성)도 증거 트리 보장
    provider = provider or engine(d)  # 미지정이면 스튜디오 엔진 설정 (Claude Code ↔ Codex 토글)
    from .start import preflight

    checks, rp = preflight(pdir, provider=provider, model=model)
    if not all(c["ok"] for c in checks):
        for c in checks:
            if not c["ok"]:
                ui.fail(f"{c['name']}: {c['fix'] or c['detail']}")
        _write_state(pdir, {"status": "fail", "error": "preflight", "ts": _now_iso()})
        return 2

    os.environ.setdefault("ASGARD_UNATTENDED", "1")  # Canon 8 — headless 는 무인

    def _stdout(s: str) -> None:
        sys.stdout.write(s)

    base_stream = on_text or _stdout
    book = os.path.join(pdir, BOOK)
    os.makedirs(book, exist_ok=True)
    log_f = open(os.path.join(book, RUN_LOG), "a", encoding="utf-8")  # noqa: SIM115 — 스트림 콜백 수명

    def stream(s: str) -> None:
        base_stream(s)
        try:
            log_f.write(s)  # 대시보드 스레드가 이 로그를 읽는다 — CLI/워커 실행 공통
            log_f.flush()
        except Exception:
            pass

    _write_state(pdir, {"status": "running", "started": _now_iso(), "brief": brief})

    from ..agent.heimdall import Heimdall

    t0 = time.time()
    try:
        try:
            h = Heimdall(rp, pdir, on_text=stream, on_status=None)
            result = h.handle(_TASK_TEMPLATE.format(brief=brief))
            tokens = h.total_tokens
        except Exception as exc:  # 실행 실패도 이력으로 남긴다 (대시보드 fail 표시)
            _finish(pdir, meta, status="fail", wall=time.time() - t0, tokens=0, note=f"{type(exc).__name__}: {exc}")
            ui.fail(f"generation failed: {type(exc).__name__}")
            return 1
        result = result or h.last_response_text  # DIRECT 빈 문자열 sentinel 대응 (run_prompt 와 동일)
        stream("\n" + (result or "") + "\n")
        warned = (result or "").lstrip().startswith("⚠")
        note = " ".join((result or "").split())[:300] if warned else ""  # 대시보드 이력에 사유를 남긴다
        _finish(pdir, meta, status="warn" if warned else "ok", wall=time.time() - t0, tokens=tokens, note=note)
        return 1 if warned else 0
    finally:
        with contextlib.suppress(Exception):
            log_f.close()


def _finish(pdir: str, meta: dict, status: str, wall: float, tokens: int, note: str) -> None:
    meta = {**meta, "updated": _now_iso()}
    with open(os.path.join(pdir, META), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    record = {
        "ts": _now_iso(),
        "stage": "generate",  # CUS-261 파이프라인 단계 자리 — discovery/critique 가 이어붙는다
        "status": status,
        "wall_s": round(wall, 1),
        "tokens": tokens,
        "artifacts": _count_artifacts(pdir),
        "note": note,
    }
    book = os.path.join(pdir, BOOK)
    os.makedirs(book, exist_ok=True)
    with open(os.path.join(book, RUNS), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    _write_state(pdir, {"status": status, "finished": _now_iso(), "wall_s": record["wall_s"], "tokens": tokens})


def spawn_generation(slug: str, d: str | None = None) -> int:
    """백그라운드 워커 스폰 (대시보드 POST 용) — `python -m asgard studio generate <slug>` 를
    분리 실행하고 로그를 .studio/run.log 로 흘린다. 반환 = pid."""
    d = d or studio_dir()
    pdir = _pdir(slug, d)
    book = os.path.join(pdir, BOOK)
    os.makedirs(book, exist_ok=True)
    _write_state(pdir, {"status": "running", "started": _now_iso()})
    log = open(os.path.join(book, RUN_LOG), "a", encoding="utf-8")
    env = {**os.environ, "ASGARD_UNATTENDED": "1"}
    proc = subprocess.Popen(  # noqa: S603 — 고정 argv, 사용자 입력은 검증된 slug 뿐
        [sys.executable, "-m", "asgard", "studio", "generate", slug],
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=pdir,
        env=env,
        start_new_session=True,  # 대시보드 서버 종료와 무관하게 완주
    )
    log.close()
    return proc.pid


# ── CLI ops ──────────────────────────────────────────────────────────────────


def run_new(
    brief: str,
    name: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> int:
    """`asgard studio new` — 스캐폴드 + 생성 인라인 실행 (스트리밍)."""
    if not brief.strip():
        ui.fail("브리프가 비어 있습니다")
        return 2
    p = create_project(brief, name=name)
    ui.ok(f"세스룸니르 프로젝트 생성 — {p['slug']} ({p['dir']})")
    code = run_generation(p["slug"], provider=provider, model=model)
    if code != 2:
        from .studio_dashboard.data import _artifact_names

        arts = _artifact_names(p["dir"])
        if arts:
            ui.ok(f"아티팩트 {len(arts)}건: " + ", ".join(arts[:8]))
        else:
            ui.warn("아티팩트가 생성되지 않았습니다 — run 기록·로그를 확인하세요")
        ui.step(f"대시보드: asgard studio open {p['slug']}")
    return code


def run_engine(name: str | None = None) -> int:
    """`asgard studio engine [claude|codex]` — 조회 또는 전환."""
    if name is None:
        cur = engine()
        ui.ok(f"engine: {ENGINES.get(cur, cur)} ({cur})")
        for prov, label in ENGINES.items():
            ui.step(f"{'●' if prov == cur else '○'} {label} — asgard studio engine {label.split()[0].lower()}")
        return 0
    provider = set_engine(name)
    if provider is None:
        ui.fail(f"unknown engine {name!r} — claude(claude-native) | codex(openai-native)")
        return 2
    ui.ok(f"engine → {ENGINES[provider]} ({provider})")
    return 0


def run_template_list(json_out: bool = False) -> int:
    from .studio_dashboard.data import templates_data

    data = templates_data()
    if json_out:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    ui.ok(f"템플릿 {data['total']}종 — " + " · ".join(f"{k} {v}" for k, v in sorted(data["categories"].items())))
    for t in data["templates"]:
        if t["kind"] == "design":
            ui.step(f"{t['name']}  ·  {t['category']}  ·  {t['desc'][:60]}")
    ui.step("미디어 프롬프트(이미지·동영상)는 대시보드 갤러리 또는 --json 으로 보세요")
    return 0


def run_template_use(name: str, brief: str | None = None) -> int:
    p = use_template(name, brief=brief)
    if p is None:
        ui.fail(f"unknown template: {name} — `asgard studio template list`")
        return 2
    ui.ok(f"템플릿 프로젝트 생성 — {p['slug']} ({p['dir']})")
    ui.step(f"대시보드: asgard studio open {p['slug']} · 다듬기: 스레드 추가 지시(재생성)")
    return 0


def run_open(slug: str, port: int = 8766) -> int:
    """`asgard studio open <slug>` — 해당 프로젝트로 딥링크된 대시보드 기동."""
    pdir = _pdir(slug)
    if not slug_ok(slug) or not os.path.isdir(pdir):
        ui.fail(f"unknown studio project: {slug}")
        return 2
    from .studio_dashboard import run_dashboard

    return run_dashboard(port=port, open_browser=True, focus=slug)
