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
    """초기 스캐폴드 — lagom.mode + project_memory 시드 + 빈 agent_models + trinity_policy.

    lagom.mode 는 default full 이라 resolve 기본값과 동일하지만, 이 파일이 사용자가 모드를
    조정하는 표면이므로 명시적으로 적어 둔다 — 없으면 "라곰이 꺼졌나" 오해한다.
    project_memory 는 opt-in 연결이라 기본 미연결이 정상 상태다. JSON 에 주석이 없으므로
    `_` 로 시작하는 키(_comment·_example)를 주석으로 심는다 — project_memory_section 이
    무시하고, 실 설정 키가 없으면 미연결로 해석돼 도구가 노출되지 않는다. 과거의 빈
    {"memory": {}} 시드는 무엇을 채워야 하는지 보이지 않았고 strict 탐색(doctor)에서
    malformed 로 오판됐다 — 예제 시드가 그 공란을 대체한다. `asgard memory connect` 가
    _example 과 같은 형태로 실 키를 채우며 주석 키를 걷어낸다. 나머지 섹션(provider …)은
    명령이 필요할 때 병합 기록한다 (사다리 1단). agent_models 는 빈 override 맵이다 —
    내장 역할별 기본값은 템플릿이 소유하고, 여기에 기록한 호스트/역할만 글로벌·기본값을 덮는다."""
    from ..lagom import DEFAULT_MODE

    project_memory_seed = {
        "_comment": (
            "Project shared memory — one `asgard memory connect <endpoint>` fills this in "
            "(project_id = memory bank name, auto-derived unless given). Ownership identity "
            "(project_uid/binding_id) is managed by Asgard in .asgard/memory/binding.json — "
            "never edit it by hand. Set `enabled: false` to switch project memory off. "
            "Keys starting with `_` are comments and ignored."
        ),
        "_example": {
            "engine": "hindsight",
            "endpoint": "http://127.0.0.1:8888",
            "project_id": "my-project-bank",
            "enabled": True,
        },
    }
    return (
        json.dumps(
            {
                "lagom": {"mode": DEFAULT_MODE},
                "project_memory": project_memory_seed,
                "agent_models": {},
                "trinity_policy": _POLICY,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
