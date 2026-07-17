"""프로젝트 공유 메모리 브릿지 — 선택된 project-memory backend를 소비하는 stdio MCP 서버.

설계 (26-07-15 확정):
  등록 = user 스코프 1회 (`claude mcp add --scope user asgard-memory -- asgard memory mcp`)
  프로젝트 구분 = cwd 에서 걸어 올라가며 찾는 통합 memory 설정 (engine·project_id)
  → repo 루트 파일 0개, 설정 없는 프로젝트에선 툴 미노출 (전역 등록의 소음 제거).

서버는 무뇌 저장소 (provider=none, 키 0) — 정제는 클라이언트 몫:
  recall  = 서버 내장 임베딩 검색 패스스루 (LLM 0). 결과는 오염 스캔 + 경계 무력화 후 전달.
  retain  = 2단 승인 (개인 위키 plan-id 계약과 동일 철학): retain 이 미리보기+승인 id 를
            반환하고, 사용자 승인 후 retain_commit(id) 만 서버에 쓴다. id 는 1회 소비·1시간 만료.
            호출 모델(= 사용자의 기존 세션 모델)이 정제·용어 방화벽 재서술을 마친 내용만 넘긴다.
  파괴 툴 = backend native delete/clear 표면은 비노출.

프로토콜: MCP stdio — 개행 구분 JSON-RPC 2.0. 로그는 stderr (stdout 은 프로토콜 전용).
전 경로 fail-safe: 서버 불능·설정 파손은 툴 오류 텍스트로 — 브릿지가 세션을 죽이지 않는다.

모듈 구성 (구 단일 모듈 memory_bridge.py 의 분해 — 공개 표면은 여기서 그대로 재수출):
  config — 설정 탐색·기록 + 2단 retain 승인 저장소 (pending·consumed·승인 키)
  trust  — machine-local backend trust + 원격 ownership binding 검증
  client — backend-neutral 소비 표면 (recall·retain·target fingerprint)
  server — MCP 툴 정의·JSON-RPC 처리·stdio 루프
"""

from .client import (
    PROTOCOL_VERSION,
    RECALL_OUTPUT_BUDGET,
    _neutralize,
    backend_target,
    server_recall,
    server_retain,
    server_retain_items,
)
from .config import (
    CONFIG_NAME,
    PENDING_LOCK_STALE,
    PENDING_NAME,
    PENDING_TTL,
    ProjectMemoryConfigError,
    _apply_private_acl,
    _approval_key,
    _approval_scope,
    _consumed_mac,
    _consumed_path,
    _load_consumed_unlocked,
    _load_pending,
    _load_pending_unlocked,
    _pending_guard,
    _pending_path,
    _retain_item_hash,
    _retain_item_mac,
    _save_consumed_unlocked,
    _save_pending,
    _save_pending_unlocked,
    _secure_machine_directory,
    _validate_private_state_file,
    claim_retain,
    find_config,
    finish_retain,
    stage_retain,
    write_config,
)
from .server import _TOOLS, _call_tool, _text_result, handle, serve
from .trust import (
    TRUST_LOCK_STALE,
    TRUST_LOCK_WAIT,
    TRUST_NAME,
    _load_trust,
    _trust_guard,
    _trust_path,
    assert_backend_access,
    expected_backend_binding,
    is_backend_trusted,
    trust_backend,
    verify_backend_binding,
)

__all__ = [
    "CONFIG_NAME",
    "PENDING_LOCK_STALE",
    "PENDING_NAME",
    "PENDING_TTL",
    "PROTOCOL_VERSION",
    "RECALL_OUTPUT_BUDGET",
    "TRUST_LOCK_STALE",
    "TRUST_LOCK_WAIT",
    "TRUST_NAME",
    "ProjectMemoryConfigError",
    "_TOOLS",
    "_apply_private_acl",
    "_approval_key",
    "_approval_scope",
    "_call_tool",
    "_consumed_mac",
    "_consumed_path",
    "_load_consumed_unlocked",
    "_load_pending",
    "_load_pending_unlocked",
    "_load_trust",
    "_neutralize",
    "_pending_guard",
    "_pending_path",
    "_retain_item_hash",
    "_retain_item_mac",
    "_save_consumed_unlocked",
    "_save_pending",
    "_save_pending_unlocked",
    "_secure_machine_directory",
    "_text_result",
    "_trust_guard",
    "_trust_path",
    "_validate_private_state_file",
    "assert_backend_access",
    "backend_target",
    "claim_retain",
    "expected_backend_binding",
    "find_config",
    "finish_retain",
    "handle",
    "is_backend_trusted",
    "server_recall",
    "server_retain",
    "server_retain_items",
    "serve",
    "stage_retain",
    "trust_backend",
    "verify_backend_binding",
    "write_config",
]
