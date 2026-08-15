#!/usr/bin/env python3
# Asgard write-sentinel — Trinity 강제화의 잃어버린 반쪽 (verifier-gate 보강).
#
# 구멍: verifier-gate는 "활성 quest 로그가 없으면 allow" (fail-open). 모델이 로그를 아예 안 열고
# 파일을 쓰면 게이트가 영원히 안 걸린다 — Canon 10이 프롬프트 순응에만 매달리게 된다.
# 봉합: PostToolUse(Write|Edit|NotebookEdit)가 "이 세션이 쓴 파일 경로"를 기록하고, gate가 Stop에서
# "기록된 경로가 지금도 dirty 한데 quest 로그가 없다"를 deterministic violation으로 차단한다.
#
# 왜 플래그가 아니라 경로 목록인가: 되돌린 write(net-zero)와 사용자의 기존 dirt를 구분하려면
# "세션이 만진 경로가 여전히 HEAD와 다른가"를 봐야 한다. 플래그면 둘 다 오차단.
# lagom: 도구 계층 write만 잡는다 — Bash 경유 mutation(echo > file)은 못 본다. 그 경로는
# quest 로그의 commands 기록 + git-guard가 부분 커버; 완전 봉합이 필요해지면 Bash 훅에서
# redirection 파싱 추가.
import json
import os
import re
import sys

# 발화 계측은 훅과 함께 깔리는 공용 라이브러리가 쥔다 — 이 훅은 자기 이름만 넘긴다.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import run  # noqa: E402
from asgard_hooklib.workspace import work_roots  # noqa: E402

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        resp = data.get("tool_response") or data.get("tool_output")
        if isinstance(resp, dict) and (resp.get("is_error") or resp.get("error")):
            sys.exit(0)  # 실패한 write는 파일을 못 바꿨다 — 기록 안 함
        tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        path = str(tool_input.get("file_path") or tool_input.get("path") or "")
        paths = [path] if path else []
        command = str(tool_input.get("command") or tool_input.get("patch") or "")
        paths.extend(
            match.strip()
            for match in re.findall(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", command, flags=re.MULTILINE)
        )
        paths = [item for item in paths if item and ".asgard" not in item]
        if not paths:
            sys.exit(0)  # 로그/상태 파일 자체는 증거 대상이 아니다 (자기참조 방지)
        proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        protocol = sys.argv[1] if len(sys.argv) > 1 else "claude"
        raw_sid = "cursor" if protocol == "cursor" else data.get("session_id") or "default"
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw_sid))[:64]
        base = os.path.join(proj, ".asgard")
        d = os.path.join(base, "state")  # 런타임 상태 격리 — verifier-gate 읽기 경로와 동일 유지
        os.makedirs(d, exist_ok=True)
        gi = os.path.join(base, ".gitignore")
        if not os.path.exists(gi):
            try:
                with open(gi, "w", encoding="utf-8") as handle:
                    handle.write("*\n")
            except Exception:
                pass
        f = os.path.join(d, "writes-" + sid + ".json")
        writes = []
        try:
            with open(f, encoding="utf-8") as handle:
                writes = json.load(handle)
        except Exception:
            try:  # 레거시(.asgard/ 직하) 세션 잔재 승계 — 세션 중 업그레이드 대비
                with open(os.path.join(base, "writes-" + sid + ".json"), encoding="utf-8") as handle:
                    writes = json.load(handle)
            except Exception:
                writes = []
        # 적는 경계는 **선언된 작업 뿌리**다 — 가드가 쓰기를 허용하는 바로 그 경계 (`work_roots`).
        # 종전에는 세션 저장소 밖을 통째로 버렸는데, 그러면 `additional_roots` 로 정식 선언한 짝
        # 저장소의 write 가 한 건도 안 남아 Canon 10 강제가 그 자리에서만 꺼졌다: 퀘스트를 안
        # 열어도 `orphan-write` 가 안 걸리고, 판정 뒤 변조도 `stale-pass` 가 안 걸린다 (26-08-11
        # 재현). 뿌리 밖은 여전히 안 적는다 — 세션 스크래치패드의 일회용 분석 스크립트가 코드처럼
        # 심판받으면 그 판정이 서브에이전트의 보고를 밀어낸다 (26-08-05 실측: 감사 워커 2기가 자기
        # 보고 대신 남이 쓴 스크래치 파일에 대한 반박을 반환했다).
        roots = work_roots(proj)
        home = os.path.realpath(proj)
        for item in paths:
            absolute = os.path.realpath(item if os.path.isabs(item) else os.path.join(proj, item))
            if not any(absolute == r or absolute.startswith(r + os.sep) for r in roots):
                continue
            # 표기는 세션 뿌리 기준 상대경로 하나로 통일한다 (`../peer/src/x.ts`). 판정 쪽의
            # 귀속 집합·변경 목록이 같은 표기를 쓰므로, 갈리면 저널의 파일이 판정과 영영 안 만난다.
            rel = os.path.relpath(absolute, home).replace("\\", "/")
            if rel not in writes and len(writes) < 500:  # cap — 상태 파일 폭주 방지
                writes.append(rel)
        with open(f, "w", encoding="utf-8") as handle:
            json.dump(writes, handle)
    except Exception:
        pass  # 관측용 훅 — 어떤 오류든 세션을 방해하지 않는다
    sys.exit(0)


if __name__ == "__main__":
    run("write-sentinel", main)
