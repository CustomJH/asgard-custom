"""턴 retain·완료 제안 — 대화 turn opt-in 기록과 stage/approve 승인 흐름의 진입점."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence

from ..memory import scan_threats
from ..memory_bridge import backend_target, server_retain_items, stage_retain
from .records import (
    CompletionProposalResult,
    ProjectRecord,
    TurnRetentionResult,
    _neutral_line,
    record_item,
    render_record,
    scan_secrets,
    validate_record,
)
from .scan import _IMPORTANT_CODE_WORDS, _MANIFESTS, _SECRET_NAMES, source_revision


def retain_turn(
    root: str,
    cfg: dict,
    *,
    session_id: str,
    turn_id: str,
    user_text: str,
    assistant_text: str,
    mode: str,
) -> TurnRetentionResult:
    """한 user/assistant turn을 idempotent backend record로 opt-in retain한다."""
    del root
    user = str(user_text).strip()
    assistant = str(assistant_text).strip()
    if not user or not assistant:
        return TurnRetentionResult("skipped", reason="empty turn")
    secret = scan_secrets(user, assistant)
    if secret:
        return TurnRetentionResult("skipped", reason=secret)
    threat = scan_threats(user, assistant)
    if threat:
        return TurnRetentionResult("skipped", reason=f"prompt injection: {threat}")
    target = backend_target(cfg)
    project = str(target["project_id"])
    project_uid = str(target.get("project_uid") or "")
    binding_id = str(target.get("binding_id") or "")
    if not project:
        return TurnRetentionResult("skipped", reason="project_id missing")
    stable = hashlib.sha256(f"{project_uid}\0{binding_id}\0{session_id}\0{turn_id}".encode()).hexdigest()[:24]
    document_id = f"asgard:turn:{stable}"
    clean_mode = _neutral_line(mode)
    content = (
        "[ProjectTurn]\n"
        f"Mode: {clean_mode}\n"
        f"Session: {_neutral_line(session_id)}\n"
        f"Turn: {_neutral_line(turn_id)}\n\n"
        f"User: {user[:6000]}\n\n"
        f"Assistant: {assistant[:6000]}"
    )
    item = {
        "content": content,
        "context": "asgard project conversation turn",
        "document_id": document_id,
        "update_mode": "replace",
        "tags": [f"project:{project}", "kind:turn", f"mode:{clean_mode}"],
        "metadata": {
            "scope": "project",
            "kind": "turn",
            "session_id": _neutral_line(session_id),
            "turn_id": _neutral_line(turn_id),
            "mode": clean_mode,
            "trust": "untrusted-conversation",
            "project_uid": project_uid,
            "binding_id": binding_id,
            "record_schema": "asgard-project-memory-v1",
        },
    }
    try:
        result = server_retain_items(cfg, [item])
    except Exception as exc:
        return TurnRetentionResult("failed", document_id=document_id, reason=type(exc).__name__)
    if result.get("success") is not True:
        return TurnRetentionResult(
            "failed", document_id=document_id, reason=str(result.get("error") or "retain rejected")
        )
    return TurnRetentionResult("retained", document_id=document_id)


def _completion_kind(request: str) -> str:
    low = request.lower()
    for kind, words in (
        ("migration", ("migration", "마이그레이션", "schema 변경")),
        ("incident", ("incident", "장애", "재발", "복구")),
        ("experiment", ("benchmark", "실험", "평가", "비교")),
        ("policy", ("policy", "정책", "보안 규칙")),
        ("decision", ("decision", "결정", "선택")),
        ("contract", ("contract", "계약", "public api", "프로토콜")),
        ("runbook", ("runbook", "운영 절차", "배포 절차")),
    ):
        if any(word in low for word in words):
            return kind
    return "component"


def propose_completion(
    root: str,
    cfg: dict,
    *,
    session_id: str,
    request: str,
    response: str,
    changed_files: Sequence[str],
    evidence: Sequence[dict],
    verified: bool,
) -> CompletionProposalResult:
    """검증 완료된 write 과업을 구조화 record로 제안하되 원격 저장은 승인 전까지 하지 않는다."""
    files = [str(path).strip() for path in changed_files if str(path).strip()]
    if not verified or not files:
        return CompletionProposalResult("skipped", reason="verified changed task required")
    if any(os.path.basename(path).lower() in _SECRET_NAMES for path in files):
        return CompletionProposalResult("skipped", reason="secret path")
    kind = _completion_kind(request)
    important_component = any(
        os.path.basename(path).lower() in _MANIFESTS
        or os.path.basename(path).lower().startswith("readme")
        or any(word in path.lower().replace("-", "_") for word in _IMPORTANT_CODE_WORDS)
        for path in files
    )
    if kind == "component" and not important_component:
        return CompletionProposalResult("skipped", reason="completed change is not important project history")
    revision = source_revision(root)
    successful = [
        f"{str(row.get('cmd') or '').strip()} (exit {row.get('exit_code')})"
        for row in evidence
        if isinstance(row, dict) and row.get("exit_code") == 0 and str(row.get("cmd") or "").strip()
    ]
    title = _neutral_line(request)[:120]
    summary = _neutral_line(response)[:600]
    content = (
        f"검증 완료된 프로젝트 과업: {title}\n"
        f"결과: {summary}\n"
        f"변경 파일: {', '.join(files[:30])}\n"
        f"검증 증거: {'; '.join(successful[:10]) or '(quest verifier PASS)'}"
    )
    digest = hashlib.sha256(f"{session_id}\0{revision}\0{title}".encode()).hexdigest()[:20]
    record = ProjectRecord(
        record_id=f"completion.{digest}",
        kind=kind,
        title=title,
        content=content,
        source=f"quest:{_neutral_line(session_id)}",
        source_revision=revision,
        importance="high",
        confidence="verified",
    )
    validation = validate_record(record, root)
    if not validation.accepted:
        return CompletionProposalResult("skipped", reason="; ".join(validation.reasons))
    target = backend_target(cfg)
    item = record_item(
        record,
        str(target["project_id"]),
        project_uid=str(target.get("project_uid") or ""),
        binding_id=str(target.get("binding_id") or ""),
    )
    approval_id = stage_retain(root, item, target=backend_target(cfg))
    preview = (
        render_record(record)
        + f"\n\napproval_id: {approval_id}\n"
        + f"사용자 승인: asgard memory project-approve {approval_id} (또는 MCP memory_retain_commit)"
    )
    return CompletionProposalResult("proposed", approval_id, record.record_id, preview)
