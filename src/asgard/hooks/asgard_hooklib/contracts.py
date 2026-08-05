"""criteria verify 계약 — 기준 한 줄에 검증 명령과 산출물을 결속한다.

`| verify: <명령> | artifacts: <경로…>` 를 파싱하고, 선언된 계약이 실제로 충족됐는지를
`unmet_contracts` 가 판정한다. 파싱과 판정이 갈라지면 "선언은 있는데 아무도 안 본다"가 되므로
둘을 한 자리에 둔다.
"""

from __future__ import annotations

import os

from .evidence import trivial_evidence
from .paths import outside_repo
from .scope import unbound_artifacts


def artifact_scope(criteria) -> tuple[str, ...]:
    """무시 파일 대조가 볼 경로 — 퀘스트가 `artifacts:` 로 선언한 것만. 빈 튜플이면 대조 없음.

    선언 밖의 gitignored 경로까지 세면 검증이 자기 판정을 무효로 만든다: 계측 스크립트를
    워크스페이스에 한 번 쓸 때마다 직전 PASS 가 stale 이 되어 게이트가 orphan-write 로 막았다
    (26-08-04 세션 3회 — recorded 905553b5 / current 84f3aa97). 선언한 산출물은 그대로
    결속된다: .gitignore 아래 증거물이 바뀌거나 사라지면 해시가 따라 바뀐다. 선언 밖의 무시
    파일은 배송물이 아니라서 diff 에도 안 실리고, 그 자리의 쓰기는 write-sentinel 이 적는다.
    verifier_gate.py 의 같은 이름 함수와 동일 유지 (단일 출처 원칙 — 어긋나면 영구 stale)."""
    # `criteria_contracts` 의 5건 상한은 **verify 명령**이 턴을 인질로 잡지 않게 두는 것이지
    # 결속 범위의 상한이 아니다. 그 상한을 여기까지 물리면 여섯 번째로 적힌 산출물이 조용히
    # 안 묶인다 — 해시는 안 움직이는데 증거물은 바뀔 수 있는 자리가 생긴다.
    out: set[str] = set()
    for text in criteria or []:
        if not isinstance(text, str):
            continue
        for raw in parse_criterion(text)["artifacts"]:
            path = os.path.normpath(str(raw)).replace("\\", "/")
            # `..` 는 git 이 "저장소 밖"으로 거절해 rc!=0 을 내고, 그러면 스냅샷 전체가
            # `<snapshot-unavailable>` 이 되어 퀘스트가 열리지도 닫히지도 않는다.
            # 절대 경로는 앞의 `/` 를 떼어 저장소 상대로 바꾸지 않는다: 그러면 결속은 있지도 않은
            # `tmp/run/x.json` 에 걸리는데 `unmet_contracts` 는 원문을 그대로 이어 붙여 저장소
            # **밖** 파일로 계약을 충족시킨다 — 한 선언을 두 소비처가 다른 파일로 읽는다.
            if path and path not in (".", "..") and not path.startswith(("../", "/")) and not os.path.isabs(raw):
                out.add(path)
    return tuple(sorted(out))


def quest_events_scope(events) -> tuple[str, ...]:
    """이 퀘스트가 선언한 산출물 전부 — 이벤트 어디에 실렸든 모은다.

    `contract_criteria` 는 계약을 실은 원본 **하나**를 고르지만, 결속 범위는 넓은 쪽이 안전하다:
    빠뜨린 선언은 증거를 안 묶고, 더 문 선언은 재검증을 부를 뿐이다."""
    return artifact_scope([c for e in events for c in (e.get("criteria") or []) if isinstance(c, str)])


def parse_criterion(text) -> dict:
    """ "설명 | verify: cmd | artifacts: a b" → {description, verify_cmd, artifacts}. 계약 없음 = 빈 값."""
    desc, cmd, arts = str(text), None, []
    parts = [p.strip() for p in str(text).split(" | ")]
    if len(parts) > 1:
        desc = parts[0]
        for p in parts[1:]:
            if p.startswith("verify:"):
                cmd = p[len("verify:") :].strip() or None
            elif p.startswith("artifacts:"):
                arts = [a for a in p[len("artifacts:") :].split() if a]
            else:
                desc = desc + " | " + p  # 계약 키워드가 아닌 ' | '는 설명의 일부
    if cmd and trivial_evidence(cmd):
        cmd = None  # trivial 명령은 계약이 될 수 없다 — 증거 필터와 동일 기준 (Goodhart)
    return {"description": desc, "verify_cmd": cmd, "artifacts": arts}


def criteria_contracts(criteria) -> list[dict]:
    """verify 계약이 선언된 기준만 — verify_cmd 또는 artifacts 보유."""
    out = []
    for t in criteria or []:
        c = parse_criterion(t)
        if c["verify_cmd"] or c["artifacts"]:
            out.append(c)
    return out[:5]  # 상한 — 계약 폭주가 verify 턴을 인질로 잡지 않게


def contract_criteria(*sources) -> list:
    """계약 추출 원본 — 문자열 항목을 실은 첫 후보. verifier_gate.py와 동일 유지.

    계약은 `"<설명> | verify: <명령>"` 문자열에만 담긴다. 그런데 판정자는 기준별 판정을
    `[{"id":..,"status":"met","evidence":..}]` 객체로 함께 보낸다 — 역할 계약이 그것을 요구한다.
    그 객체를 계약 원본으로 쓰면 계약이 0건으로 보여 하네스가 계약 명령을 실행하지 않는데,
    게이트는 퀘스트 선언(문자열)에서 계약을 계속 읽으므로 영구 미충족이 된다 (26-07-26 실측:
    CC 모드에서 `criteria-unverified`로 Stop이 막혀 세션이 49분간 종료하지 못했다).
    형태로 원본을 고르면 두 경로가 같은 계약을 본다.

    형태만으로는 부족하다 — 판정자는 같은 기준별 판정을 **문자열 목록**으로도 보낸다(역할 계약이
    산문 판정을 허용한다). 그러면 계약을 한 줄도 안 실은 원본이 먼저 잡혀 26-07-26 과 똑같은
    영구 미충족이 다른 문으로 되살아난다 (26-08-04 실측: 판정자가 기준 6건을 산문 문자열로 보내
    close 가 `criteria-unverified` 로 두 번 거부됐다). 그래서 계약을 실은 원본을 먼저 고르고,
    어디에도 없을 때만 첫 문자열 원본으로 물러선다."""
    string_sources = [s for s in ([c for c in (src or []) if isinstance(c, str)] for src in sources) if s]
    for strings in string_sources:
        if any(c["verify_cmd"] for c in criteria_contracts(strings)):
            return strings
    return string_sources[0] if string_sources else []


def unmet_contracts(root: str, criteria, rec: dict) -> list[str]:
    """PASS 레코드(rec) 기준 미충족 계약 목록. 명령은 하네스 기록(criteria_checks)의 exit 0만 인정,
    산출물은 지금(호출 시점) 존재를 라이브 재확인 — 산출물은 .gitignore로 diff-hash 밖일 수 있어
    stale 검사가 삭제를 못 잡는다. 계약이 있는데 기록이 없으면(구버전 이벤트) 미충족 — 재검증 유도.

    존재만으로는 부족하다: 있는데 **안 묶이는** 형상이 둘 있어서 (`unbound_artifacts`) 이름만
    계약이고 내용은 해시 밖인 채로 PASS 가 통과할 수 있다. 그 둘도 미충족으로 센다."""
    unmet = []
    rows = [c for c in (rec.get("criteria_checks") or []) if isinstance(c, dict)]
    checks = {(" ".join(str(c.get("cmd", "")).split())): c.get("exit_code") for c in rows}
    stalled = {" ".join(str(c.get("cmd", "")).split()) for c in rows if c.get("timed_out")}
    for c in criteria_contracts(criteria):
        cmd = c["verify_cmd"]
        if cmd and checks.get(" ".join(cmd.split())) != 0:
            # timeout 은 실패와 다르다. 그대로 미충족이지만(기준 유지) 이유를 실패로 적으면 수리 턴이
            # 멀쩡한 코드를 고치러 가고 계약은 영영 안 채워진다 — 고칠 곳은 명령이나 baseline_timeout 이다.
            if " ".join(cmd.split()) in stalled:
                unmet.append(f"verify: {cmd} (timed out — narrow the command or raise baseline_timeout)")
            else:
                unmet.append("verify: " + cmd)
        for a in c["artifacts"]:
            if outside_repo(a):
                unmet.append(f"artifact: {a} (outside the repository — declare a repo-relative path)")
            elif not os.path.exists(os.path.join(root, a)):
                unmet.append("artifact: " + a)
    scope = artifact_scope(criteria)
    unmet += [f"artifact: {item}" for item in (unbound_artifacts(root, scope) if scope else [])]
    return unmet
