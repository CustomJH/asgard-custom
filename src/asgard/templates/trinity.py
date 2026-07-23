"""Trinity policy template — 통합 설정(asgard-setting-project.json)의 trinity_policy 섹션.

역할 서브에이전트 3종은 `asgard.templates.roles` 의 실제 .md 파일로 관리한다 (훅과 같은 패턴 — 문자열 임베딩
금지). 결정 테이블 로직은 quest_log.py(전이 함수)가 유일한 출처고, 이 정책 파일은 임계값·경로 패턴
같은 선언 데이터만 담는다 — 코드/데이터 이중 관리를 피한다."""

import json

# 시드 값의 유일한 출처 = quest_log.DEFAULT_POLICY (verifier_gate 는 부분집합 미러). 파일은 사용자가
# 조정하는 표면이고, 스크립트 내장값은 파일이 없거나 깨졌을 때의 fail-open 바닥이다 — 리터럴 사본을
# 두면 훅 패치가 시드에 안 실려 4모드 전부 낡은 정책으로 덮인다(26-07-23 sensitive_paths 드리프트).
from ..hooks.quest_log import DEFAULT_POLICY as _POLICY


def trinity_policy() -> str:
    return json.dumps(_POLICY, ensure_ascii=False, indent=2) + "\n"


def project_settings() -> str:
    """초기 스캐폴드 — lagom.mode + 빈 memory/agent_models + trinity_policy 시드.

    lagom.mode 는 default full 이라 resolve 기본값과 동일하지만, 이 파일이 사용자가 모드를
    조정하는 표면이므로 명시적으로 적어 둔다 — 없으면 "라곰이 꺼졌나" 오해한다. memory 는
    빈 객체로 둔다 — 프로젝트 메모리는 opt-in 연결이라 기본 미연결(공란)이 정상 상태고,
    `asgard memory connect` 가 engine·endpoint·project_id 를 채운다. 빈 {} 는 find_config
    에서 미연결로 해석돼 도구가 노출되지 않는다. 나머지 섹션(provider …)은 명령이 필요할
    때 병합 기록한다 (사다리 1단). agent_models 는 빈 override 맵이다 — 내장 역할별 기본값은
    템플릿이 소유하고, 여기에 기록한 호스트/역할만 글로벌·기본값을 덮는다."""
    from ..lagom import DEFAULT_MODE

    return (
        json.dumps(
            {"lagom": {"mode": DEFAULT_MODE}, "memory": {}, "agent_models": {}, "trinity_policy": _POLICY},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
