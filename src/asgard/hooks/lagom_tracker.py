#!/usr/bin/env python3
# Asgard lagom-tracker — UserPromptSubmit 모드 수명주기.
#
# 세 가지 축:
#   전환   /lagom lite|full|off          → 상태파일 갱신 (세션 한정)
#   영속   /lagom default lite|full|off  → 프로젝트 [lagom].mode 기록 + 상태 갱신
#           (review 는 세션 한정 스킬 모드 — 전환·영속 둘 다 기각, 원본 #377 계승)
#   비활성 "stop lagom" / "normal mode" 전문 입력 (대소문자 무시, 말미 구두점 허용) → off
# 보상: 상태파일이 없으면(SessionStart 훅이 없는 표면 — Codex/Cursor) 기본값을 기록하고,
# 활성 모드면 첫 프롬프트에 캐논을 주입한다. CC 는 lagom-activate 가 먼저 기록하므로 무개입.
# stdout + exit 0 = 컨텍스트 주입 (공식 스키마). 모든 오류는 무개입 통과 (fail-open).
import json
import os
import re
import sys

MODES = ("off", "lite", "full")

# 모드 마커 필터 — templates/lagom.py render_lagom 과 동일 유지 (단일 출처 원칙)
_ROW = re.compile(r"^\s*\|\s*\*\*(off|lite|full)\*\*\s*\|")
_EXAMPLE = re.compile(r"^\s*-\s*(off|lite|full):")
_SWITCH = re.compile(r"^\s*/lagom(?:\s+(default))?\s+([a-zA-Z]+)\s*$", re.I)
_BARE = re.compile(r"^\s*/lagom\s*$", re.I)
_DEACTIVATE = re.compile(r"^\s*(stop lagom|normal mode)\s*[.!]?\s*$", re.I)


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


def config_mode(root):
    """lagom_activate.py config_mode 와 동일 유지 (단일 출처 원칙: asgard/lagom.py)."""
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
    """lagom_activate.py render 와 동일 유지 (단일 출처 원칙: templates render_lagom)."""
    out = []
    for line in canon.splitlines():
        m = _ROW.match(line) or _EXAMPLE.match(line)
        if m and m.group(1) != mode:
            continue
        out.append(line)
    return "\n".join(out).replace("__MODE__", mode)


def write_state(root, mode):
    try:
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
        return True
    except Exception:
        return False


def persist_default(root, mode):
    """프로젝트 lagom.mode 영속 — asgard-setting-project.json 병합 편집 (settings.save_project 와
    동일 유지, 단일 출처 원칙). 미이관 프로젝트(신규 파일 없음 + 구 config.toml 존재)는 구 TOML 에
    기록한다 — 신규 파일을 만들면 TOML 의 다른 섹션이 통째로 가려지기 때문 (이관은 asgard sync 몫)."""
    try:
        asg = os.path.join(root, ".asgard")
        new = os.path.join(asg, "asgard-setting-project.json")
        legacy = os.path.join(asg, "config.toml")
        if not os.path.exists(new) and os.path.exists(legacy):
            txt = open(legacy, encoding="utf-8").read()
            block = '[lagom]\nmode = "%s"\n' % mode
            pat = r"^\[lagom\][^\[]*"
            if re.search(pat, txt, re.M):
                txt = re.sub(pat, block, txt, count=1, flags=re.M)
            else:
                txt = (txt.rstrip() + "\n\n" + block) if txt.strip() else block
            open(legacy, "w", encoding="utf-8").write(txt)
            return True
        try:
            data = json.load(open(new, encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        sec = dict(data.get("lagom") or {})
        sec["mode"] = mode
        data["lagom"] = sec
        os.makedirs(asg, exist_ok=True)
        tmp = "%s.%d.tmp" % (new, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, new)
        return True
    except Exception:
        return False


def canon_text():
    try:
        return open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lagom-canon.md"), encoding="utf-8").read()
    except Exception:
        return ""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        prompt = str(data.get("prompt") or "")
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()

        if _DEACTIVATE.match(prompt):
            write_state(root, "off")
            sys.stdout.write("[lagom] off — 미니멀리즘 계약 해제. 재활성: /lagom full")
            sys.exit(0)

        if _BARE.match(prompt):
            cur = read_state(root)
            sys.stdout.write(
                "[lagom] 현재 모드: %s (전환 /lagom <mode>, 영속 /lagom default <mode>)" % (cur or config_mode(root))
            )
            sys.exit(0)

        m = _SWITCH.match(prompt)
        if m:
            is_default, target = bool(m.group(1)), m.group(2).strip().lower()
            if norm(target) is None:  # review 포함 — 세션 스킬 전용, 모드 아님
                sys.stdout.write(
                    "[lagom] '%s' 는 유효한 모드가 아니다 (off|lite|full%s)"
                    % (target, " — review 는 세션 한정 스킬" if target == "review" else "")
                )
                sys.exit(0)
            target = norm(target)
            write_state(root, target)
            if is_default:
                ok = persist_default(root, target)
                sys.stdout.write(
                    "[lagom] 기본값 %s %s"
                    % (target, "영속됨 (asgard-setting-project.json)" if ok else "— 설정 기록 실패, 세션에만 적용")
                )
            else:
                sys.stdout.write("[lagom] mode → %s (세션 한정)" % target)
            if target != "off":
                canon = canon_text()
                if canon:
                    sys.stdout.write("\n\n" + render(canon, target))
            sys.exit(0)

        # 보상 주입 — SessionStart 훅이 없는 표면(Codex/Cursor): 상태파일 부재 = 첫 프롬프트
        if read_state(root) is None:  # 신규 state/ + 레거시 2종 전부 부재 (read_state 가 판정)
            mode = config_mode(root)
            write_state(root, mode)
            if mode != "off":
                canon = canon_text()
                if canon:
                    sys.stdout.write("[lagom] mode=%s\n\n%s" % (mode, render(canon, mode)))
    except Exception:
        pass  # fail-open
    sys.exit(0)


if __name__ == "__main__":
    main()
