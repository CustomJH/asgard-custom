#!/usr/bin/env python3
# Asgard write-sentinel — Trinity 강제화의 잃어버린 반쪽 (verifier-gate 보강).
#
# 구멍: verifier-gate 는 "활성 quest 로그가 없으면 allow" (fail-open). 모델이 로그를 아예 안 열고
# 파일을 쓰면 게이트가 영원히 안 걸린다 — Canon 10 이 프롬프트 순응에만 매달리게 된다.
# 봉합: PostToolUse(Write|Edit|NotebookEdit)가 "이 세션이 쓴 파일 경로"를 기록하고, gate 가 Stop 에서
# "기록된 경로가 지금도 dirty 한데 quest 로그가 없다" 를 deterministic violation 으로 차단한다.
#
# 왜 플래그가 아니라 경로 목록인가: 되돌린 write(net-zero)와 사용자의 기존 dirt 를 구분하려면
# "세션이 만진 경로가 여전히 HEAD 와 다른가"를 봐야 한다. 플래그면 둘 다 오차단.
# lagom: 도구 계층 write 만 잡는다 — Bash 경유 mutation(echo > file)은 못 본다. 그 경로는
# quest 로그의 commands 기록 + git-guard 가 부분 커버; 완전 봉합이 필요해지면 Bash 훅에서
# redirection 파싱 추가.
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


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        resp = data.get("tool_response")
        if isinstance(resp, dict) and (resp.get("is_error") or resp.get("error")):
            sys.exit(0)  # 실패한 write 는 파일을 못 바꿨다 — 기록 안 함
        path = str((data.get("tool_input") or {}).get("file_path") or "")
        if not path or ".asgard" in path:
            sys.exit(0)  # 로그/상태 파일 자체는 증거 대상이 아니다 (자기참조 방지)
        proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("session_id") or "default"))[:64]
        base = os.path.join(proj, ".asgard")
        d = os.path.join(base, "state")  # 런타임 상태 격리 — verifier-gate 읽기 경로와 동일 유지
        os.makedirs(d, exist_ok=True)
        gi = os.path.join(base, ".gitignore")
        if not os.path.exists(gi):
            try:
                open(gi, "w").write("*\n")
            except Exception:
                pass
        f = os.path.join(d, "writes-" + sid + ".json")
        writes = []
        try:
            writes = json.load(open(f))
        except Exception:
            try:  # 레거시(.asgard/ 직하) 세션 잔재 승계 — 세션 중 업그레이드 대비
                writes = json.load(open(os.path.join(base, "writes-" + sid + ".json")))
            except Exception:
                writes = []
        rel = os.path.relpath(path, proj) if os.path.isabs(path) else path
        if rel not in writes and len(writes) < 500:  # cap — 상태 파일 폭주 방지
            writes.append(rel)
            json.dump(writes, open(f, "w"))
    except Exception:
        pass  # 관측용 훅 — 어떤 오류든 세션을 방해하지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
