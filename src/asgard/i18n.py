"""경량 i18n — 기본 영어, config/env로 한국어 전환.

문자열은 (en, ko) 튜플 테이블. t(key, **kw)가 현재 언어로 렌더한다. 언어 해석 우선순위:
프로젝트 .asgard/config.toml [ui] lang → ~/.asgard/config.toml → env ASGARD_LANG → 기본 "en".
(시스템 로케일은 보지 않는다 — "기본 영어, 명시 설정 시 한국어" 규칙.)

UI 문자열만 다룬다. 역할 에이전트 프롬프트(heimdall)는 모델 대상이라 대상 아님.
"""

from __future__ import annotations

import os

LANGS = ("en", "ko")
_LANG = "en"

# key: (english, korean)
_M: dict[str, tuple[str, str]] = {
    # 배너·환영
    "tagline": ("Bifrost's watchman · Trinity orchestrator", "비프로스트의 수호자 · Trinity 오케스트레이터"),
    "welcome": ("Welcome to Asgard, Odin.", "오딘, Asgard에 오신 걸 환영해요."),
    "welcome_hint": ("Ask anything, or type /help.", "무엇이든 물어보세요. 도움이 필요하면 /help를 입력하면 돼요."),
    "tip": (
        "Tip — ! for bash, / for commands, Ctrl-C to interrupt a turn.",
        "Tip — !로 bash 실행 · /로 커맨드 · Ctrl-C로 턴 중단",
    ),
    "cmd_hints": (
        "/help · /new · !bash · Tab complete · ↑↓ history",
        "/help · /new · !bash · Tab 자동완성 · ↑↓ 히스토리",
    ),
    "bye": ("Bifrost sealed. Farewell, Odin.", "비프로스트를 봉인했어요. 다음에 또 만나요, 오딘."),
    "ready": ("Heimdall is ready. Ask anything.", "Heimdall이 준비됐어요. 무엇이든 물어보세요."),
    # provider·온보딩
    "provider_unset": (
        "no provider — connect with /provider set",
        "아직 연결된 provider가 없어요 — /provider set으로 연결해 주세요",
    ),
    "not_connected": ("not connected — /provider set", "연결 안 됨 — /provider set"),
    "connect_needed": (
        "provider not connected — run /provider set to connect, then resend",
        "provider가 아직 연결되지 않았어요 — /provider set으로 연결한 뒤 다시 보내 주세요",
    ),
    "connect_cancel": (
        "connection cancelled — try /provider set again",
        "연결을 취소했어요 — /provider set으로 다시 시도할 수 있어요",
    ),
    "connected": ("connected", "연결됨"),
    "pick_provider": ("select a provider", "사용할 provider를 선택해 주세요"),
    "pick_model": ("select a model", "사용할 모델을 선택해 주세요"),
    # 인터랙티브 선택 패널 (picker)
    "picker_filter_ph": ("type to filter", "입력하면 바로 걸러져요"),
    "picker_hint": (
        "↑↓ move · type to filter · enter select · esc cancel",
        "↑↓ 이동 · 입력해 필터 · enter 선택 · esc 취소",
    ),
    "picker_more": ("… {n} more", "… {n}개 더"),
    "picker_no_match": ("no match", "일치하는 항목이 없어요"),
    "picker_manual_model": ('use "{q}" as model ID', '"{q}"를 모델 ID로 사용'),
    # 턴 종료 recap — 자연어 한 문장 (딤)
    "recap_created": ("created {f}", "{f} 생성"),
    "recap_patched": ("patched {f}", "{f} 수정"),
    "recap_ran": ("ran {c}", "{c} 실행"),
    "recap_agents": ("agents {a}", "에이전트 {a}"),
    # recap 메타 이벤트 — 기억·자가발전 부수 작업 (표시 1순위). 기억 체계 = 위그드라실(세계수),
    # 개인 기억은 줄기에 새기고 프로젝트 기억은 프로젝트 가지 — 승인권자는 오딘(사용자).
    "recap_ev_memory_saved": ("carved into Yggdrasil: {s}", "위그드라실에 새겼어요: {s}"),
    "recap_ev_retained": (
        "preserved this turn on Yggdrasil's project branch",
        "이 턴을 위그드라실 프로젝트 가지에 보존했어요",
    ),
    "recap_ev_proposed": (
        "proposed an update to Yggdrasil's project branch (awaiting Odin's approval)",
        "위그드라실 프로젝트 가지 갱신을 제안했어요 (오딘 승인 대기)",
    ),
    "recap_ev_distill": (
        "suggested distilling this exploration into Yggdrasil",
        "이번 탐색을 위그드라실로 증류하도록 제안했어요",
    ),
    # 답변 소스 배지 — 회상(숏컷) 발동 턴의 done 줄: 주입된 기억이 컨텍스트에서 차지한 근사 비중.
    # 무닌 = 오딘의 기억 까마귀 — 세상을 날아 기억을 물어다 오딘에게 돌려준다 (회상의 세계관 표상).
    "recap_memory_pct": ("Muninn ~{p}%", "무닌 ~{p}%"),
    "recap_memory_tok": ("Muninn ~{k}k", "무닌 ~{k}k"),
    "api_key_prompt": ("{p} API key (hidden)", "{p} API 키 (입력한 키는 화면에 보이지 않아요)"),
    "rpm_prompt": ("rpm limit (requests/min · -1 = off)", "rpm 상한 (분당 요청 수 · -1이면 제한 없음)"),
    "rpm_invalid": ("invalid rpm — keeping current", "rpm 값이 올바르지 않아요 — 기존 값을 그대로 둘게요"),
    "saved_cred": (
        "saved to ~/.asgard/credentials.json (mode 600)",
        "~/.asgard/credentials.json에 저장했어요 (권한 600)",
    ),
    "cancelled": ("(cancelled)", "(취소했어요)"),
    "no_key": ("(no key — cancelled)", "(키가 입력되지 않아 취소했어요)"),
    # 상태·턴
    "busy": ("working…", "작업하고 있어요…"),
    "interrupt_hint": ("Ctrl-C to stop", "Ctrl-C로 중단"),
    "turn_interrupted": ("(turn interrupted)", "(턴을 중단했어요)"),
    "turn_kept": ("(turn interrupted — session kept)", "(턴을 중단했어요 — 세션은 그대로 이어져요)"),
    "session_error": ("session error: {e}", "세션에 문제가 생겼어요: {e}"),
    "no_quest": ("no active quest", "진행 중인 퀘스트가 없어요"),
    "unknown_cmd": ("unknown command {c} — /help", "{c}는 모르는 커맨드예요 — /help에서 전체 목록을 볼 수 있어요"),
    "unknown_cmd_suggest": (
        "unknown command {c} — did you mean {suggestion}?",
        "{c}는 모르는 커맨드예요 — 혹시 {suggestion} 아닌가요?",
    ),
    # help 항목
    "h_help": ("this help", "이 도움말 보기"),
    "h_skills": ("list explicitly invocable skills", "직접 부를 수 있는 스킬 목록"),
    "h_new": ("new session (reset context & screen)", "새 세션 시작 (컨텍스트·화면 초기화)"),
    "h_quest": ("active quest log status", "진행 중인 퀘스트 로그 보기"),
    "h_sessions": (
        "child agent sessions · '/sessions stop' cancels the active tree",
        "하위 에이전트 세션 목록 · '/sessions stop'으로 실행 트리 취소",
    ),
    "no_sessions": ("no child sessions", "하위 세션이 없어요"),
    "sessions_stopping": ("cancelling the active session tree", "실행 중인 세션 트리를 취소할게요"),
    "h_provider": (
        "show current provider·model connection",
        "현재 provider·모델 연결 상태 보기",
    ),
    "h_provider_set": (
        "connect or change provider (interactive)",
        "provider 연결·변경 (대화형)",
    ),
    "h_model": ("select a model for the current provider", "현재 provider에서 쓸 모델 고르기"),
    "h_clear": ("clear the screen", "화면 지우기"),
    "h_exit": ("end the session (same as Ctrl-D)", "세션 종료 (Ctrl-D와 같아요)"),
    "h_lang": ("switch language: /lang en | ko", "언어 바꾸기: /lang en | ko"),
    "h_update": ("update asgard to the latest release", "asgard를 최신 릴리스로 업데이트"),
    "update_restart": (
        "new version applies after restart — /exit then `asgard start`",
        "새 버전은 다시 시작하면 적용돼요 — /exit 후 asgard start",
    ),
    "lang_set": ("language → {lang}", "언어를 바꿨어요 → {lang}"),
    "lang_usage": ("usage: /lang en | ko", "사용법: /lang en | ko"),
    "h_bash": ("run a bash command", "bash 명령 바로 실행"),
    "help_footer": ("Tab complete · ↑↓ history", "Tab 자동완성 · ↑↓ 히스토리"),
    "cancel_notice": (
        "⚠ Cancelled by user — turn stopped.",
        "⚠ 요청하신 대로 턴을 중단했어요.",
    ),
    "cancel_notice_quest": (
        " Quest {qid} remains ACTIVE — re-request to continue verification, or close it with quest-log close.",
        " 퀘스트 {qid}는 아직 ACTIVE 상태예요 — 다시 요청하면 이어서 검증하고, quest-log close로 닫을 수도 있어요.",
    ),
    "continue_restored": (
        "Restored the last conversation ({n} turns) — context only; quests and evidence are unaffected.",
        "이전 대화 {n}턴을 복원했어요 — 대화 맥락만 이어지고, 퀘스트·증거 상태는 그대로예요.",
    ),
    "needs_base_url": ("base_url required", "base_url이 필요해요"),
    "thought": ("Runes read", "룬 해독"),
    "thinking": ("reading the runes…", "룬을 읽는 중…"),
    # 분류 침묵 구간 — 하임달이 요청의 길을 살피는 상황극 (thinking() 풀과 별개의 고정 문구)
    "classifying": ("Heimdall surveys the roads from the gate…", "헤임달이 관문에서 길을 살피는 중…"),
    "ph_input": (
        "Ask anything — / commands · ! bash · \\⏎ newline",
        "무엇이든 입력하세요 — / 커맨드 · ! bash · \\⏎ 줄바꿈",
    ),
    "number": ("number", "번호"),
    "model_id_prompt": ("model ID", "모델 ID"),
    "invalid_model_id": ("invalid model ID", "모델 ID가 올바르지 않아요"),
    "model_catalog_fallback": (
        "live model catalog unavailable — showing offline fallback models",
        "실시간 모델 목록을 불러오지 못했어요 — 내장 목록을 대신 보여드릴게요",
    ),
    # trinity 배치·브릿지
    "h_trinity": (
        "role providers and host models · '/trinity set' or '/trinity model …' to configure",
        "역할별 provider·호스트 모델 보기 · '/trinity set' 또는 '/trinity model …'로 설정",
    ),
    "h_bridge": (
        "per-tool CLI bridge · '/bridge <tool> on|off'",
        "도구별 CLI 브릿지 · '/bridge <도구> on|off'",
    ),
    "h_manual": (
        "your own project rules (MANUAL.md) — what is loaded · '/manual show' for the text",
        "내가 쓴 프로젝트 규칙 (MANUAL.md) — 뭐가 실렸는지 · '/manual show'로 원문",
    ),
    "manual_none": (
        "no manual — write rules in MANUAL.md and every role in every mode reads them",
        "MANUAL.md에 규칙을 쓰면 모든 모드·모든 역할이 읽어요",
    ),
    "manual_inert": (
        "the file is there but nothing is loaded — rules go outside the comment markers",
        "파일은 있는데 실리는 게 없어요 — 규칙은 주석 밖에 써야 해요",
    ),
    "manual_off": (
        "off (manual.mode) — not injected in any mode",
        "꺼짐 (manual.mode) — 어떤 모드에도 안 실려요",
    ),
    "manual_frozen": (
        "loaded when this session opened — edits apply on the next session",
        "이 세션이 열릴 때 읽은 내용이에요 — 편집분은 다음 세션부터 적용돼요",
    ),
    # lagom
    "h_lagom": (
        "minimalism contract (just-enough code & replies) — '/lagom' shows the modes",
        "미니멀리즘 계약 (딱 적당한 코드·응답) — '/lagom'으로 모드 확인",
    ),
    "lagom_what": (
        "just enough — unwritten code is the best code, unspent tokens the best explanation.\n"
        "safety (input validation · error handling · security) is never trimmed, in any mode.",
        "딱 적당한 만큼만 — 안 쓴 코드가 최고의 코드, 안 쓴 토큰이 최고의 설명이에요.\n"
        "안전(입력 검증·에러 처리·보안)은 어떤 모드에서도 줄이지 않아요.",
    ),
    "lagom_mode_off": (
        "plain — no output compression, no efficiency ladder",
        "평소대로 — 산출 압축도, 효율 사다리도 없어요",
    ),
    "lagom_mode_lite": (
        "build as asked, add one lazier-alternative line; trim only filler",
        "요청대로 만들고 더 간단한 대안을 한 줄 제안해요 · 군더더기만 덜어내요",
    ),
    "lagom_mode_full": (
        "efficiency ladder enforced · shortest diff · shortest reply",
        "효율 사다리 적용 · 가장 짧은 diff · 가장 짧은 설명",
    ),
    "lagom_usage": (
        "usage: /lagom [default] off|lite|full · /lagom stats",
        "사용법: /lagom [default] off|lite|full · /lagom stats",
    ),
    "lagom_set": ("lagom → {mode} (this session)", "lagom → {mode} (이번 세션만)"),
    "lagom_persisted": (
        "lagom default → {mode} (asgard-setting-project.json)",
        "lagom 기본값 → {mode} (asgard-setting-project.json)",
    ),
    "lagom_session": ("session override", "이번 세션 값"),
    "lagom_default": ("default", "기본값"),
    "lagom_fixing": ("polishing the reply — style check…", "응답 문체를 다듬는 중…"),
    "lagom_corrected": (
        "⠶ style check rewrote the reply — the version below is canonical",
        "⠶ 문체 검사로 응답을 다듬었어요 — 아래가 정본이에요",
    ),
    # 배정 단위 진행 보드 — Thinker가 쪼갠 단위를 열어 보이고 하나씩 닫는다 (agent/heimdall/todo.py).
    "todo_head": ("assignment units · {n}", "배정 단위 {n}개"),
    "todo_squad_head": ("squad tasks · {n}", "편대 과업 {n}개"),
    "todo_summary_done": ("{n} done", "완료 {n}"),
    "todo_summary_left": ("{n} unfinished", "미완 {n}"),
    "todo_resume": ("resume {qid} · {n} unfinished", "resume {qid} · 미완 {n}단위"),
    "todo_wave_parallel": ("wave [{ids}] · {n} units in parallel", "wave [{ids}] · 병렬 {n}단위"),
    "todo_wave_single": ("wave [{ids}] · single", "wave [{ids}] · 단독"),
    # 영어 표면은 단복수를 맞춘다 — "1 files"는 사람이 쓴 문장으로 읽히지 않는다 (Bragi 계약).
    "todo_unit_file": ("{n} file", "파일 {n}개"),
    "todo_unit_files": ("{n} files", "파일 {n}개"),
    "todo_unit_retry": ("failed — reassigning ({e})", "실패 — 재배정 예정 ({e})"),
    "todo_unit_exhausted": ("failed — retry budget exhausted", "실패 — retry budget 소진"),
    # Trinity 최종 보고 — 퀘스트 로그가 유일한 소스. 사람이 읽는 표면이라 UI 언어를 따른다
    # (하드코딩 한국어였음 — 영어 기본 제품에서 한국어 보고가 나가던 것을 26-07-26 수리).
    "report_done": (
        "Done — verification PASS, diff hash matched, quest log closed.",
        "과업 완수 — 검증 PASS + diff-hash 일치, 퀘스트 로그 닫힘.",
    ),
    # 영어 표면은 단복수를 맞춘다 — "1 turns"는 사람이 쓴 문장으로 읽히지 않는다 (Bragi 계약).
    "report_turns": ("{turns} · roles {roles}", "턴 {n} · 역할 {roles}"),
    "report_evidence": ("Evidence", "증거"),
    "report_assumptions": (
        "Assumptions (Canon 8 — Odin's review needed):",
        "가정 (Canon 8 — Odin 검토 필요):",
    ),
    "report_gate_blocks": (
        "⚠ passed after {blocks} — the repair history is in the quest log",
        "⚠ 게이트 차단 {n}회 후 통과 — 수리 이력은 퀘스트 로그 참조",
    ),
    "report_unit_turn": ("{n} turn", "턴 {n}"),
    "report_unit_turns": ("{n} turns", "턴 {n}"),
    "report_unit_block": ("{n} gate block", "게이트 차단 {n}회"),
    "report_unit_blocks": ("{n} gate blocks", "게이트 차단 {n}회"),
    "lagom_stats_tokens": (
        "session spend {tok} tokens (input+output)",
        "이번 세션에서 {tok} 토큰을 썼어요 (입력+출력)",
    ),
    "lagom_stats_note": (
        "savings need measured coefficients — pending a measurement bench; no telemetry, local only",
        "절감량은 실측 계수를 얻은 뒤에 보여드릴게요 — 텔레메트리 없이 로컬에서만 집계해요",
    ),
    "pick_role": ("select a role", "역할을 선택해 주세요"),
    "pick_host": ("select where the agent runs", "에이전트를 실행할 환경을 선택해 주세요"),
    "current_tag": ("current", "현재"),
    "recommended_tag": ("recommended", "추천"),
    "model_override_clear": (
        "clear project override (use global/default)",
        "프로젝트 설정 해제 (글로벌/기본값 사용)",
    ),
    "placement_clear": ("default (clear placement)", "기본값 (배치 해제)"),
    "placement_saved": (
        "placement saved — applied to new turns",
        "배치를 저장했어요 — 새 턴부터 적용돼요",
    ),
    "placement_cleared": (
        "placement cleared — back to the default provider",
        "배치를 해제했어요 — 기본 provider로 돌아가요",
    ),
    "default_tag": ("(default)", "(기본)"),
    "trinity_hint": (
        "'/trinity models' lists all models · '/trinity model …' sets one · '/trinity dual on|off' toggles two-model planning",
        "'/trinity models'로 전체 확인 · '/trinity model …'로 개별 설정 · '/trinity dual on|off'로 두 모델 계획 전환",
    ),
    "trinity_model_usage": (
        "usage: /trinity model <host> <role> <model> [Claude/Codex effort | native provider] · /trinity model reset <host> <role>",
        "사용법: /trinity model <host> <role> <model> [Claude/Codex effort | native provider] · /trinity model reset <host> <role>",
    ),
    "trinity_model_saved": (
        "{host}.{role} → {value} (this project)",
        "{host}.{role} → {value} (이 프로젝트)",
    ),
    "trinity_model_reset": (
        "{host}.{role} override cleared → {value}",
        "{host}.{role} 사용자 설정 해제 → {value}",
    ),
    "trinity_dual_usage": (
        "usage: /trinity dual [default] on|off",
        "사용법: /trinity dual [default] on|off",
    ),
    "trinity_dual_same": (
        "dual mode needs a distinct thinker_alt model ({model}) — configure it with '/trinity set'",
        "dual 모드에는 지금과 다른 thinker_alt 모델이 필요해요 ({model}) — '/trinity set'으로 배치해 주세요",
    ),
    "trinity_dual_set": ("dual thinker → {mode} (this session)", "dual thinker → {mode} (이번 세션만)"),
    "trinity_dual_persisted": (
        "dual thinker default → {mode} (this project)",
        "dual thinker 기본값 → {mode} (이 프로젝트)",
    ),
    "bridge_usage": (
        "usage: /bridge <claude-code|codex|cursor> on|off — lets that tool delegate placed roles via `asgard role`",
        "사용법: /bridge <claude-code|codex|cursor> on|off — 해당 도구가 배치된 역할을 `asgard role`로 위임해요",
    ),
    "bridge_set": ("bridge.{tool} = {v}", "bridge.{tool} = {v}"),
    # ── CLI 도움말 (hc_ = help, cli) ────────────────────────────────────────────
    # 여기 있는 문자열은 Typer 데코레이터가 import 시점에 t()로 읽는다. cli.py 맨 위에서
    # load_lang()을 먼저 돌리는 이유가 이것 — 그 호출이 없으면 언어와 무관하게 영어가 굳는다.
    # 업무·창·근거 검색만 표에 있고 나머지 명령은 아직 영어 리터럴이다. ko 표면을 마저 채우려면
    # 남은 help=를 같은 규약으로 옮기면 된다.
    "hc_json": ("machine-readable output", "기계가 읽을 형태로 내보내요"),
    "hc_port": (
        "local port (falls back to a free port if it is taken)",
        "로컬 포트 (이미 쓰고 있으면 빈 포트로 넘어가요)",
    ),
    "hc_no_browser": ("do not open the browser automatically", "브라우저를 자동으로 열지 않아요"),
    # 업무 보드
    "hc_ticket": (
        "your work board — file tickets, move them, link them (the same store the Studio window uses)",
        "업무 보드 — 티켓을 발급하고 옮기고 이어요 (Studio 창과 같은 저장소예요)",
    ),
    "hc_tk_board": ("the board as it stands, in status columns", "지금 보드를 상태 칸으로 접어서 보여드려요"),
    "hc_tk_team": (
        "narrow to one team key — `.` means this folder's team (default: the whole workspace)",
        "팀 키로 좁혀요 — `.`은 이 폴더의 팀이에요 (기본값은 워크스페이스 전체)",
    ),
    "hc_tk_project": ("project name or id", "프로젝트 이름 또는 id"),
    "hc_tk_list": (
        "every ticket, most urgent first ('none' sinks to the bottom)",
        "티켓 목록 — 급한 것부터 보여드리고 '없음'은 맨 뒤로 가요",
    ),
    "hc_tk_f_status": ("keep only these statuses (comma-separated)", "이 상태인 것만 남겨요 (쉼표로 여럿)"),
    "hc_tk_f_assignee": ("keep only this assignee", "이 담당자 것만 남겨요"),
    "hc_tk_f_label": ("keep only this label", "이 라벨이 붙은 것만 남겨요"),
    "hc_tk_f_cycle": ("cycle number or name", "주기 번호 또는 이름"),
    "hc_tk_f_query": ("match part of a title, body, or number", "제목·설명·번호에 부분 일치"),
    "hc_tk_f_open": ("drop whatever is already done or cancelled", "완료·취소된 건 빼요"),
    "hc_tk_new": (
        "file a ticket — its number is handed out once and never reused",
        "티켓 발급 — 번호는 한 번만 나가고 다시 쓰이지 않아요",
    ),
    "hc_tk_title": (
        "what counts as finished — the outcome, not the topic",
        "무엇을 끝내면 되는지 — 주제가 아니라 결과로 적어요",
    ),
    "hc_tk_body": ("context, how to reproduce it, what makes it done", "맥락·재현 방법·수용 기준"),
    "hc_tk_priority": ("1 urgent · 2 high · 3 normal · 4 low · 0 none", "1 긴급 · 2 높음 · 3 보통 · 4 낮음 · 0 없음"),
    "hc_tk_assignee": ("who owns it", "담당자"),
    "hc_tk_labels": ("labels (comma-separated)", "라벨 (쉼표로 여럿)"),
    "hc_tk_parent": ("parent ticket — one level only", "상위 티켓 — 한 겹까지만 돼요"),
    "hc_tk_estimate": ("estimate, in points", "추정 포인트"),
    "hc_tk_new_team": (
        "file it against this team (default: the team bound to this folder, else the default team)",
        "이 팀 앞으로 발급해요 (기본값: 이 폴더에 묶인 팀, 없으면 기본 팀)",
    ),
    "hc_tk_new_project": (
        "attach it to a project — projects run across teams",
        "프로젝트에 붙여요 — 프로젝트는 팀을 가로질러요",
    ),
    "hc_tk_ms_opt": ("a milestone inside that project", "그 프로젝트 안의 마일스톤"),
    "hc_tk_show": (
        "one ticket in full — body, children, links, comments, activity",
        "티켓 한 건 — 본문·하위·관계·댓글·활동",
    ),
    "hc_tk_ref_full": ("number (PRJ-12), bare digits (12), or id", "번호(PRJ-12), 숫자(12), 또는 id"),
    "hc_tk_ref": ("number or id", "번호 또는 id"),
    "hc_tk_move": (
        "move it to another status — the start and finish times are recorded with it",
        "상태를 옮겨요 — 시작·완료 시각도 같이 남아요",
    ),
    "hc_tk_set": (
        "change only the fields you pass — the rest are left alone",
        "준 칸만 바꿔요 — 안 준 칸은 그대로 둬요",
    ),
    "hc_tk_set_assignee": ("an empty string unassigns it", "빈 문자열이면 담당을 떼요"),
    "hc_tk_set_labels": ("comma-separated — replaces the whole list", "쉼표로 여럿 — 통째로 갈아 끼워요"),
    "hc_tk_set_parent": ("an empty string detaches it from its parent", "빈 문자열이면 상위에서 떼요"),
    "hc_tk_set_cycle": ("an empty string takes it out of the cycle", "빈 문자열이면 주기에서 빼요"),
    "hc_tk_comment": ("leave a line on a ticket", "티켓에 한 줄 남겨요"),
    "hc_tk_comment_text": ("what you want to say", "남길 말"),
    "hc_tk_comment_author": ("who is writing (default cli)", "글쓴이 (기본값 cli)"),
    "hc_tk_link": (
        "link two tickets — blocks has a direction (ref blocks other)",
        "티켓끼리 이어요 — blocks는 방향이 있어요 (ref가 other를 막아요)",
    ),
    "hc_tk_link_ref": ("the one doing the blocking", "막는 쪽"),
    "hc_tk_link_other": ("the one being blocked", "막히는 쪽"),
    "hc_tk_link_remove": ("cut the link instead of making one", "잇지 말고 끊어요"),
    "hc_tk_delete": (
        "delete a ticket — its number is never handed out again",
        "티켓을 지워요 — 그 번호는 다시 발급되지 않아요",
    ),
    "hc_tk_cycle": (
        "cycles — list, open, close. closing one carries the unfinished work into the next",
        "주기(사이클) — 목록·신설·마감. 닫으면 안 끝난 일감이 다음 주기로 넘어가요",
    ),
    "hc_tk_cycle_new": ("open a new cycle under this name", "이 이름으로 새 주기를 열어요"),
    "hc_tk_cycle_close": ("close the cycle with this number or name", "이 번호·이름의 주기를 닫아요"),
    "hc_tk_cycle_team": (
        "whose cycle (default: the team bound to this folder, else the default team)",
        "어느 팀의 주기인지 (기본값: 이 폴더에 묶인 팀, 없으면 기본 팀)",
    ),
    "hc_tk_team_cmd": (
        "teams — they own the numbers, and workflow, cycles and triage all run per team",
        "팀 — 번호의 주인이고, 워크플로·사이클·트리아지가 도는 단위예요",
    ),
    "hc_tk_team_new": ("stand up a team under this name", "이 이름으로 팀을 세워요"),
    "hc_tk_team_key": (
        "the prefix on its numbers (default: taken from the name)",
        "번호 앞자리 (기본값: 이름에서 뽑아요)",
    ),
    "hc_tk_team_triage": (
        "on|off — work arriving from outside queues in the inbox first",
        "on|off — 밖에서 들어온 일감을 인박스에 세워요",
    ),
    "hc_tk_team_weeks": ("cycle length, in weeks", "사이클 길이 (주)"),
    "hc_tk_project_cmd": (
        "projects — work that has an end. they run across teams",
        "프로젝트 — 끝이 있는 일이에요. 팀을 가로질러요",
    ),
    "hc_tk_pj_new": ("open a project under this name", "이 이름으로 프로젝트를 열어요"),
    "hc_tk_pj_show": (
        "one project in detail — milestones, progress, updates",
        "이 프로젝트의 상세 — 마일스톤·진척·보고",
    ),
    "hc_tk_pj_lead": ("a single lead — so responsibility does not split", "리드 한 사람 — 책임이 갈리지 않게요"),
    "hc_tk_pj_target": ("target date, YYYY-MM-DD", "목표일 YYYY-MM-DD"),
    "hc_tk_pj_teams": ("team keys taking part (comma-separated)", "참여 팀 키 (쉼표로 여럿)"),
    "hc_tk_milestone": ("milestones inside a project — list, add, finish", "프로젝트 안의 마일스톤 — 목록·신설·완료"),
    "hc_tk_ms_new": ("create a milestone under this name", "이 이름으로 마일스톤을 만들어요"),
    "hc_tk_ms_done": ("mark this milestone finished", "이 마일스톤을 완료로 표시해요"),
    "hc_tk_update": (
        "post project progress — you write the health yourself",
        "프로젝트 진행 보고 — 건강도는 사람이 적어요",
    ),
    "hc_tk_update_body": ("what landed this time, and what is left", "이번에 무엇이 됐고 무엇이 남았는지"),
    "hc_tk_triage": ("a team's inbox — work nobody has accepted yet", "팀의 인박스 — 아직 받아들이지 않은 일감이에요"),
    "hc_tk_triage_accept": ("accept this number onto the board", "이 번호를 받아들여 보드로 넣어요"),
    "hc_tk_triage_decline": (
        "decline this number (closes it as cancelled, with your reason)",
        "이 번호를 거절해요 (취소로 닫고 이유를 남겨요)",
    ),
    "hc_tk_triage_note": ("a line to leave as you accept or decline", "받거나 거절하며 남길 한 줄"),
    "hc_tk_import": (
        "pull in a board from back when every folder kept its own",
        "폴더마다 보드가 하나이던 시절의 저장소를 워크스페이스로 들여와요",
    ),
    # 창
    "hc_open_studio": (
        "Asgard Studio — work, tickets, planning, artifacts, skills, settings",
        "Asgard Studio — 작업·업무·기획·산출물·스킬·설정",
    ),
    "hc_open_web": ("use a browser instead of the native app", "네이티브 앱 대신 브라우저로 열어요"),
    "hc_open_view": (
        "land on this screen (tickets|plan|projects|artifacts|plugins|settings)",
        "바로 들어갈 화면 (tickets|plan|projects|artifacts|plugins|settings)",
    ),
    "hc_open_workspace": (
        "open a particular workspace (default: this folder if it is a project, else the one you used last)",
        "작업 공간을 정해서 열어요 (기본값: 여기가 프로젝트면 여기, 아니면 최근 프로젝트)",
    ),
    "hc_open": (
        "open a local Asgard window — studio · map · memory",
        "여기 있는 Asgard 창을 열어요 — studio · map · memory",
    ),
    "hc_open_map": ("the relation graph — what your code touches", "관계 그래프 뷰 — 코드가 무엇에 닿는지 보여드려요"),
    "hc_open_memory": (
        "the Yggdrasil dashboard — your personal memory wiki (read-only)",
        "위그드라실 대시보드 — 개인 메모리 위키예요 (읽기 전용)",
    ),
    # 근거 검색
    "hc_map_why": (
        "why the code is like this — search the comments and docstrings that recorded a reason",
        "왜 이렇게 돼 있는지 — 근거를 적어 둔 주석·독스트링에서 찾아드려요",
    ),
    "hc_map_why_q": (
        "what you want the reason for, e.g. 'why the injection budget is what it is'",
        "무엇의 근거를 찾는지, 예: '주입 예산 이유'",
    ),
    "hc_map_why_limit": ("how many reasons to show", "보여줄 근거 수"),
}


def set_lang(lang: str | None) -> None:
    global _LANG
    _LANG = lang if lang in LANGS else "en"


def current() -> str:
    return _LANG


def load_lang(root: str | None = None) -> str:
    """설정 ui.lang → env ASGARD_LANG → 'en'. set_lang도 함께 수행하고 결과를 반환.
    설정 파일 = asgard-setting-{project,global}.json (settings.py — 구 config.toml 폴백 내장)."""
    lang = None
    try:
        from .settings import load_global, load_project

        root = root or os.getcwd()
        for cfg in (load_global(), load_project(root)):  # 프로젝트가 글로벌을 덮는다
            v = (cfg.get("ui") or {}).get("lang")
            if v:
                lang = v
    except Exception:
        pass
    lang = lang or os.environ.get("ASGARD_LANG")
    set_lang(lang)
    return _LANG


def save_lang(lang: str, root: str | None = None) -> bool:
    """언어를 프로젝트 asgard-setting-project.json의 ui.lang에 저장하고 즉시 적용."""
    if lang not in LANGS:
        return False
    try:
        from .settings import save_project

        save_project(root or os.getcwd(), "ui", {"lang": lang})
    except Exception:
        return False
    set_lang(lang)
    return True


def t(key: str, **kw) -> str:
    en, ko = _M.get(key, (key, key))
    s = ko if _LANG == "ko" else en
    return s.format(**kw) if kw else s


# ── 침묵 구간 라이브 라벨 — 등불 옆 상황극 문구 (단조로움 방지) ─────────────────
# 모델이 생각하는 동안 매번 다른 세계관 문구가 뜬다. 공용 풀 + 역할(페르소나)별 풀에서
# 무작위 — 역할 풀이 있으면 절반 확률로 우선해 "지금 누가 무엇을 하는지"가 배어나게.
# (en, ko) 규약은 _M과 동일. t() 키가 아닌 전용 함수인 이유 = 호출마다 무작위 선택.
_THINKING_COMMON: list[tuple[str, str]] = [
    ("reading the runes…", "룬을 읽는 중…"),
    ("Huginn and Muninn are circling…", "후긴과 무닌이 하늘을 도는 중…"),
    ("drawing from Mimir's well…", "미미르의 샘에서 지혜를 긷는 중…"),
    ("the Norns are weaving the threads…", "노른들이 운명의 실을 잣는 중…"),
    ("leafing through the sagas…", "사가를 뒤적이는 중…"),
    ("tracing Yggdrasil's branches…", "위그드라실 가지를 더듬는 중…"),
    ("gazing out from Hlidskjalf…", "흘리드스캴프에서 아홉 세계를 굽어보는 중…"),
    ("listening for footsteps on the Bifrost…", "비프로스트의 발소리에 귀 기울이는 중…"),
]
_THINKING_ROLE: dict[str, list[tuple[str, str]]] = {
    "direct": [
        ("Heimdall handles it at the gate…", "헤임달이 관문에서 직접 처리하는 중…"),
        ("a swift stroke of the watchman's hand…", "문지기가 손수 빠르게 매듭짓는 중…"),
    ],
    "worker": [
        ("stoking the forge…", "대장간 화덕을 달구는 중…"),
        ("hammering at the anvil…", "모루 위에서 망치질하는 중…"),
        ("tempering the blade…", "칼날을 벼리는 중…"),
    ],
    "thinker": [
        ("weighing the paths at the crossroads…", "갈림길에서 길을 저울질하는 중…"),
        ("unrolling the war maps…", "전략 지도를 펼치는 중…"),
        ("taking counsel at the long table…", "긴 탁자에 모여 숙의하는 중…"),
    ],
    "verifier": [
        ("weighing the evidence on the scales…", "증거를 저울에 다는 중…"),
        ("holding the work up to the light…", "결과물을 빛에 비춰 보는 중…"),
        ("Gjallarhorn in hand, watching…", "걀라르호른을 쥐고 지켜보는 중…"),
    ],
    "thor": [
        ("summoning the thunderheads…", "천둥구름을 부르는 중…"),
        ("gripping Mjölnir tighter…", "묠니르를 고쳐 쥐는 중…"),
    ],
    "freyja": [
        ("threading Brísingamen…", "브리싱가멘 목걸이를 꿰는 중…"),
        ("mixing pigments in Fólkvangr…", "폴크방에서 물감을 개는 중…"),
        ("laying gold leaf on the panel…", "패널에 금박을 펴 바르는 중…"),
    ],
    "eitri": [
        ("firing the kilns of Nidavellir…", "니다벨리르의 가마에 불을 지피는 중…"),
        ("truing the wheelwork…", "톱니를 맞물리는 중…"),
    ],
    "loki": [
        ("prodding at the seams for mischief…", "빈틈을 찔러 보며 장난을 꾸미는 중…"),
        ("tugging at loose threads…", "풀린 실밥을 잡아당기는 중…"),
    ],
    "mimir": [
        ("stirring the well of memory…", "기억의 샘을 휘젓는 중…"),
    ],
}


def thinking(role: str | None = None) -> str:
    """침묵 구간 라벨 한 개 — 호출마다 달라진다. role은 페르소나명('-lead' 접미 무시)."""
    import random

    role_pool = _THINKING_ROLE.get((role or "").removesuffix("-lead"), [])
    pool = role_pool if role_pool and random.random() < 0.5 else _THINKING_COMMON
    en, ko = random.choice(pool)
    return ko if _LANG == "ko" else en
