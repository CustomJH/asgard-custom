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
_SWITCH = re.compile(r"^\s*/lagom(?:\s+(default))?\s+([a-zA-Z]+)\s*$", re.I)
_BARE = re.compile(r"^\s*/lagom\s*$", re.I)
_DEACTIVATE = re.compile(r"^\s*(stop lagom|normal mode)\s*[.!]?\s*$", re.I)


def _read_text(path):
    """텍스트 한 벌. 오류는 그대로 올린다 — 호출부마다 삼킬 범위가 다르다. quest_log.py 와 동일 유지.

    핸들 수명을 여기서 끝내는 것이 요점이다. `open(p).read()` 는 CPython 의 참조 계수에 기대
    곧장 닫히는 것이고, 그 기댐은 코드에 안 적혀 있어서 다른 런타임에서 조용히 깨진다."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _write_text(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


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
            txt = _read_text(scope_toml)
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
            txt = _read_text(legacy)
            block = '[lagom]\nmode = "%s"\n' % mode
            pat = r"^\[lagom\][^\[]*"
            if re.search(pat, txt, re.M):
                txt = re.sub(pat, block, txt, count=1, flags=re.M)
            else:
                txt = (txt.rstrip() + "\n\n" + block) if txt.strip() else block
            _write_text(legacy, txt)
            return True
        try:
            with open(new, encoding="utf-8") as handle:
                data = json.load(handle)
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
        return _read_text(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lagom-canon.md"))
    except Exception:
        return ""


CLIENTS = {"claude-code", "codex", "cursor"}


def client():
    raw = str(sys.argv[1] if len(sys.argv) > 1 else "claude-code")
    return raw if raw in CLIENTS else "claude-code"


def emit(current_client, text):
    """주입 스키마는 클라이언트마다 다르다 — map-activate·memory-activate 와 동일 유지 (단일 규약).
    한 번만 쓴다: 이 훅은 문장을 이어 붙이는 자리가 여럿이라 조각마다 JSON 을 뱉으면 파손된다.

    Cursor 의 beforeSubmitPrompt 는 컨텍스트 주입 통로가 없다 (cursor.com/docs/hooks, 26-07-27
    확인: 출력은 continue/user_message 뿐) — 그래서 사람에게 보이는 문장으로 내보낸다. 캐논
    자체는 같은 클라이언트의 sessionStart(lagom-activate)가 이미 주입한다."""
    if not text:
        return
    if current_client == "cursor":
        sys.stdout.write(json.dumps({"user_message": text}, ensure_ascii=False) + "\n")
    elif current_client == "codex":
        sys.stdout.write(
            json.dumps(
                {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}},
                ensure_ascii=False,
            )
            + "\n"
        )
    else:
        sys.stdout.write(text)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    said = ""
    try:
        prompt = str(data.get("prompt") or "")
        root = (
            os.environ.get("CLAUDE_PROJECT_DIR")
            or os.environ.get("CURSOR_PROJECT_DIR")
            or data.get("cwd")
            or os.getcwd()
        )

        if _DEACTIVATE.match(prompt):
            write_state(root, "off")
            emit(client(), "[lagom] off — minimalism contract lifted. Reactivate: /lagom full")
            sys.exit(0)

        if _BARE.match(prompt):
            cur = read_state(root)
            emit(
                client(),
                "[lagom] current mode: %s (switch: /lagom <mode>, persist: /lagom default <mode>)"
                % (cur or config_mode(root)),
            )
            sys.exit(0)

        m = _SWITCH.match(prompt)
        if m:
            is_default, target = bool(m.group(1)), m.group(2).strip().lower()
            if norm(target) is None:  # review 포함 — 세션 스킬 전용, 모드 아님
                emit(
                    client(),
                    "[lagom] '%s' is not a valid mode (off|lite|full%s)"
                    % (target, " — review is a session-only skill" if target == "review" else ""),
                )
                sys.exit(0)
            target = norm(target)
            write_state(root, target)
            if is_default:
                ok = persist_default(root, target)
                said = "[lagom] default %s %s" % (
                    target,
                    "persisted (asgard-setting-project.json)"
                    if ok
                    else "— failed to persist config, applied to this session only",
                )
            else:
                said = "[lagom] mode → %s (this session only)" % target
            if target != "off":
                canon = canon_text()
                if canon:
                    said += "\n\n" + render(canon, target)
            emit(client(), said)
            sys.exit(0)

        # 보상 주입 — SessionStart 훅이 없는 표면: 상태파일 부재 = 첫 프롬프트
        if read_state(root) is None:  # 신규 state/ + 레거시 2종 전부 부재 (read_state 가 판정)
            mode = config_mode(root)
            write_state(root, mode)
            if mode != "off":
                canon = canon_text()
                if canon:
                    emit(client(), "[lagom] mode=%s\n\n%s" % (mode, render(canon, mode)))
    except Exception:
        pass  # fail-open
    sys.exit(0)


if __name__ == "__main__":
    main()
