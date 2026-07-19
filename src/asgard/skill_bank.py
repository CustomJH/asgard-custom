"""learned 스킬 뱅크 — 파일 기반 스킬 레지스트리 (자가발전 Phase 0, CUS-252).

정본 = <root>/.asgard/skills/<name>/SKILL.md (프로젝트) + ~/.asgard/skills/<name>/SKILL.md (글로벌).
번들 스킬(templates/freyja.py 등 코드 상수)과 달리, 세션 경험에서 증류·승인된 스킬이 사는 층이다.
mtime 서명 캐시로 변경만 감지 — 프로세스 재시작 없이 새 스킬이 다음 디스패치에 라우팅된다.

자가발전 헌법 (CUS-251):
- 이 층은 advisory 지식 주입만 — 게이트·판정 표면(Verifier/loki)에는 절대 주입하지 않는다.
- 설치 경로는 evolution 인박스 승인(asgard evolve approve)뿐 — 이 모듈엔 쓰기 API가 없다.
- 주입 시 usage 를 기록해 큐레이션(노화 판정)의 원료로 남긴다 (SkillOps: 라이브러리는 자산).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time

SKILL_FILE = "SKILL.md"
APPROVAL_FILE = ".asgard-approval.json"
USAGE_FILE = "skill-usage.json"
_MAX_BODY = 8000  # 주입 상한 (스킬당) — 컨텍스트 예산 보호
_CAP = 2  # 태스크당 최대 주입 수 — 과주입 = 노이즈

# (sig, skills) per root — mtime 서명이 같으면 재파싱 없이 재사용
_cache: dict[str, tuple[tuple, dict[str, dict]]] = {}


def _approval_key(create: bool = False) -> bytes | None:
    """Machine-local owner-only key; repository contents cannot mint their own approval."""
    path = os.environ.get("ASGARD_APPROVAL_KEY_FILE") or os.path.join(
        os.path.expanduser("~"), ".asgard", "skill-approval.key"
    )
    try:
        st = os.lstat(path)
        if os.path.islink(path) or st.st_mode & 0o077 or (hasattr(os, "getuid") and st.st_uid != os.getuid()):
            return None
        key = open(path, "rb").read()
        return key if len(key) >= 32 else None
    except FileNotFoundError:
        if not create:
            return None
    except OSError:
        return None
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    key = secrets.token_bytes(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
        return key
    except FileExistsError:
        return _approval_key(False)
    except OSError:
        return None


def approval_receipt(root: str, name: str, text: str, *, create_key: bool = False, **metadata) -> dict:
    """Authenticate an approval to this machine, canonical project, skill directory and content."""
    digest = hashlib.sha256(text.encode()).hexdigest()
    key = _approval_key(create_key)
    if key is None:
        raise RuntimeError("machine-local skill approval key unavailable or unsafe")
    payload = "\0".join((os.path.realpath(root), name, digest)).encode()
    mac = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return {"schema": 2, "sha256": digest, "hmac_sha256": mac, **metadata}


def _valid_project_approval(root: str, name: str, text: str, receipt: dict) -> bool:
    try:
        expected = approval_receipt(root, name, text)
    except RuntimeError:
        return False
    return secrets.compare_digest(str(receipt.get("sha256") or ""), expected["sha256"]) and secrets.compare_digest(
        str(receipt.get("hmac_sha256") or ""), expected["hmac_sha256"]
    )


def skill_dirs(root: str) -> list[str]:
    """스캔 대상 — 프로젝트가 글로벌을 이긴다 (settings 병합 규칙과 동일 방향)."""
    return [
        os.path.join(root, ".asgard", "skills"),
        os.path.join(os.path.expanduser("~"), ".asgard", "skills"),
    ]


def parse_skill_md(text: str) -> tuple[dict, str] | None:
    """SKILL.md → (frontmatter dict, body). 형식 불량 = None (fail-open: 라우팅에서 제외)."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta: dict = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    if not meta.get("name") or not meta.get("triggers"):
        return None  # trigger 없는 스킬은 영원히 라우팅되지 않는다 — 등록 자체를 거부
    meta["triggers"] = tuple(t.strip().lower() for t in str(meta["triggers"]).split(",") if t.strip())
    meta.setdefault("agent", "worker")
    return meta, parts[2].lstrip()


def _scan_sig(dirs: list[str]) -> tuple:
    """mtime 서명 — SKILL.md 들의 (경로, mtime_ns) 정렬 튜플. 변경/추가/삭제를 모두 감지."""
    sig = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith("."):  # .archive 등 숨김 = 라우팅 제외
                continue
            p = os.path.join(d, name, SKILL_FILE)
            try:
                approval = os.path.join(d, name, APPROVAL_FILE)
                sig.append(
                    (
                        p,
                        os.stat(p).st_mtime_ns,
                        os.stat(approval).st_mtime_ns if os.path.exists(approval) else None,
                    )
                )
            except OSError:
                continue
    return tuple(sig)


def _load(dirs: list[str]) -> dict[str, dict]:
    skills: dict[str, dict] = {}
    project_dir = os.path.realpath(dirs[0]) if dirs else ""
    project_root = os.path.dirname(os.path.dirname(project_dir)) if project_dir else ""
    for d in reversed(dirs):  # 글로벌 먼저 — 프로젝트가 같은 이름을 덮어쓴다
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith("."):
                continue
            p = os.path.join(d, name, SKILL_FILE)
            try:
                text = open(p, encoding="utf-8").read()
            except OSError:
                continue
            if os.path.realpath(d) == project_dir:
                try:
                    receipt = json.load(open(os.path.join(d, name, APPROVAL_FILE), encoding="utf-8"))
                except OSError, ValueError, TypeError:
                    continue
                if not _valid_project_approval(project_root, name, text, receipt):
                    continue
            parsed = parse_skill_md(text)
            if parsed:
                meta, body = parsed
                skills[str(meta["name"])] = {**meta, "body": body[:_MAX_BODY], "path": p}
    return skills


def learned_skills(root: str) -> dict[str, dict]:
    """레지스트리 뷰 (캐시) — name → {name, description, triggers, agent, origin, body, path}."""
    dirs = skill_dirs(root)
    sig = _scan_sig(dirs)
    hit = _cache.get(root)
    if hit and hit[0] == sig:
        return hit[1]
    skills = _load(dirs)
    _cache[root] = (sig, skills)
    return skills


def resolve_learned(root: str, task: str, agent: str) -> list[tuple[str, str]]:
    """디스패치 task → 매칭 learned 스킬 (이름, 본문) — 번들 리졸버와 동일한 0-LLM 부분 일치.

    agent 필터: 스킬 frontmatter 의 agent 가 현재 표면과 같거나 "any". Verifier/loki 는
    호출측이 아예 이 함수를 부르지 않는다 (게이트 무결성 — 헌법). 무매칭 = 빈 리스트."""
    t = task.lower()
    # A/B 개입 스위치 (CUS-251 C4) — 벤치 하니스가 baseline 런에서 스킬을 끈다 ("*" = 전부)
    disabled = {n.strip() for n in os.environ.get("ASGARD_LEARNED_DISABLE", "").split(",") if n.strip()}
    hits: list[tuple[int, str, str]] = []
    for name, s in learned_skills(root).items():
        if "*" in disabled or name in disabled:
            continue
        if str(s.get("disable-model-invocation") or "").lower() in ("true", "yes", "1", "on"):
            continue
        if s.get("agent") not in (agent, "any"):
            continue
        n = sum(1 for k in s["triggers"] if k in t)
        if n:
            hits.append((-n, name, s["body"]))
    hits.sort()
    return [(name, body) for _, name, body in hits[:_CAP]]


def record_use(root: str, names: list[str]) -> None:
    """주입 usage 기록 — 큐레이션(30일 미사용 = stale 후보)의 유일한 판정 원료. 실패 무해."""
    if not names:
        return
    d = os.path.join(root, ".asgard", "state")
    f = os.path.join(d, USAGE_FILE)
    try:
        os.makedirs(d, exist_ok=True)
        try:
            usage = json.load(open(f, encoding="utf-8"))
        except Exception:
            usage = {}
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for name in names:
            u = usage.get(name) or {"uses": 0}
            usage[name] = {"uses": int(u.get("uses", 0)) + 1, "last_used": now}
        tmp = f"{f}.{os.getpid()}.tmp"
        json.dump(usage, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, f)
    except Exception:
        pass


def usage(root: str) -> dict:
    try:
        d = json.load(open(os.path.join(root, ".asgard", "state", USAGE_FILE), encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}
