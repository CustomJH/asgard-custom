#!/usr/bin/env python3
# Asgard lagom-activate — SessionStart 모드 초기화 + 룰 주입.
#
# 배선 매처: startup|resume|clear|compact — compact/clear 는 컨텍스트 소실 지점이라 재주입이
# 필수다. 동작: 세션 런타임 상태(.asgard/lagom-mode.json)가 있으면 그 값(세션 중 전환 보존),
# 없으면 영속 기본값(LAGOM_MODE env > 프로젝트 [lagom].mode > 글로벌 > full)을 기록한다.
# off = 무주입 즉시 종료. 활성 = 훅 옆 lagom-canon.md 를 모드 필터해 stdout 으로 주입
# (SessionStart stdout + exit 0 = 컨텍스트 주입, unattended-context 와 동일 스키마).
# fail-open: 페이로드 파싱 실패는 cwd 폴백으로 주입을 계속하고(룰 누락이 더 큰 실패),
# 캐논 부재 등 그 밖의 오류는 무주입 통과 — 어느 쪽도 세션을 막지 않는다 (항상 exit 0).
import json
import os
import re
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
    except Exception:
        pass


MODES = ("off", "lite", "full")

# 모드 마커 필터 — templates/lagom.py render_lagom 과 동일 유지 (단일 출처 원칙)
_ROW = re.compile(r"^\s*\|\s*\*\*(off|lite|full)\*\*\s*\|")
_EXAMPLE = re.compile(r"^\s*-\s*(off|lite|full):")


def norm(m):
    m = str(m or "").strip().lower()
    return m if m in MODES else None


def read_state(root):
    for path, structured in (
        (os.path.join(root, ".asgard", "state", "lagom-mode.json"), True),  # 신규 — state/ 격리
        (os.path.join(root, ".asgard", "lagom-mode.json"), True),  # 레거시 0.4.x
        (os.path.join(root, ".asgard", "lagom-mode"), False),  # 레거시 0.4.1 이하
    ):
        try:
            with open(path, encoding="utf-8") as f:
                return norm(json.load(f).get("mode") if structured else f.read())
        except Exception:
            continue
    return None


def write_state(root, mode):
    state = os.path.join(root, ".asgard", "state", "lagom-mode.json")
    os.makedirs(os.path.dirname(state), exist_ok=True)
    with open(state, "w", encoding="utf-8") as f:
        json.dump({"mode": mode}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    for old in ("lagom-mode.json", "lagom-mode"):  # 레거시 이관 완료 (이원화 방지)
        try:
            os.remove(os.path.join(root, ".asgard", old))
        except FileNotFoundError:
            pass


def config_mode(root):
    """영속 기본값 — env > 프로젝트 > 글로벌 > full. asgard/lagom.py default_mode 와 동일 유지.
    tomllib 은 3.11+ 라 정규식 파싱 (config 는 save_config_section 이 쓰는 단순 TOML)."""
    m = norm(os.environ.get("LAGOM_MODE"))
    if m:
        return m
    home = os.path.expanduser("~")
    for scope_json, scope_toml in (
        (os.path.join(root, ".asgard", "asgard-setting-project.json"), os.path.join(root, ".asgard", "config.toml")),
        (os.path.join(home, ".asgard", "asgard-setting-global.json"), os.path.join(home, ".asgard", "config.toml")),
    ):
        # 신규 JSON 설정이 그 스코프의 정본 — 있으면 구 TOML 미참조 (settings.py 와 동일 유지)
        cfg = None
        try:
            with open(scope_json, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = None
        if isinstance(cfg, dict):
            m = norm((cfg.get("lagom") or {}).get("mode"))
            if m:
                return m
            continue
        try:
            txt = open(scope_toml, encoding="utf-8").read()
        except Exception:
            continue
        sec = re.search(r"(?ms)^\[lagom\]\s*$(.*?)(?=^\[|\Z)", txt)
        if sec:
            kv = re.search(r'^\s*mode\s*=\s*"?([A-Za-z]+)"?', sec.group(1), re.M)
            m = norm(kv.group(1)) if kv else None
            if m:
                return m
    return "full"


def render(canon, mode):
    """모드 필터 — 마커 행은 해당 모드만 생존. render_lagom 과 동일 유지 (단일 출처 원칙)."""
    out = []
    for line in canon.splitlines():
        m = _ROW.match(line) or _EXAMPLE.match(line)
        if m and m.group(1) != mode:
            continue
        out.append(line)
    return "\n".join(out).replace("__MODE__", mode)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        mode = read_state(root)  # 세션 전환값이 기본값을 이긴다
        if mode is None:
            mode = config_mode(root)
            try:  # best-effort — 기록 실패해도 주입은 진행
                write_state(root, mode)
            except Exception:
                pass
        if mode == "off":
            sys.exit(0)  # 무주입 — off 는 흔적도 없어야 한다 (토큰 회귀 없음)
        canon = open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "lagom-canon.md"), encoding="utf-8"
        ).read()
        sys.stdout.write("[lagom] mode=%s (source=%s)\n\n%s" % (mode, data.get("source") or "?", render(canon, mode)))
    except Exception:
        pass  # fail-open — 캐논 파일 부재 등 어떤 실패도 세션을 막지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
