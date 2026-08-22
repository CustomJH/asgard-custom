<!-- asgard:project-map schema=3 -->
# Project Map — asgard

> Asgard managed orientation map. Regenerate with `asgard map update`; do not hand-edit this file.
> It is a navigation hint, not completion evidence: re-read every path used by a plan.

## Orientation

- Project root: `./`
- Languages by observed source files: Python (787), JavaScript (12), Rust (2)
- Evidence scan: 1041 files; 51 landmarks

## Landmarks

- `README.md` — project overview and operating guide
- `docker/` — container and deployment area
- `docker/asgard-k6/` — project boundary (docker-compose.yml)
- `docker/asgard-project-memory/` — project boundary (docker-compose.yml)
- `docs/` — documentation area
- `pyproject.toml` — Python project manifest
- `src/` — primary source area
- `src/asgard/` — Python package root
- `src/asgard/agent/` — Python package root
- `src/asgard/agent/heimdall/` — Python package root
- `src/asgard/agent/heimdall/bifrost/` — Python package root
- `src/asgard/agent/heimdall/core/` — Python package root
- `src/asgard/agent/heimdall/trinity/` — Python package root
- `src/asgard/agent/huginn/` — Python package root
- `src/asgard/agent/repl/` — Python package root
- `src/asgard/agent/session/` — Python package root
- `src/asgard/agent/tools/` — Python package root
- `src/asgard/bragi/` — Python package root
- `src/asgard/cli/` — Python package root
- `src/asgard/commands/` — Python package root
- `src/asgard/commands/doctor/` — Python package root
- `src/asgard/commands/memory/` — Python package root
- `src/asgard/commands/memory_dashboard/` — Python package root
- `src/asgard/commands/plan_api/` — Python package root
- `src/asgard/commands/studio/` — Python package root
- `src/asgard/commands/tutor/` — Python package root
- `src/asgard/evolution/` — Python package root
- `src/asgard/hooks/` — Python package root
- `src/asgard/hooks/asgard_hooklib/` — Python package root
- `src/asgard/map_graph/` — Python package root
- `src/asgard/memory/` — Python package root
- `src/asgard/memory/norn/` — Python package root
- `src/asgard/memory/recall/` — Python package root
- `src/asgard/memory_bridge/` — Python package root
- `src/asgard/orchestration/` — Python package root
- `src/asgard/plan/` — Python package root
- `src/asgard/project_memory/` — Python package root
- `src/asgard/project_memory_backends/` — Python package root
- `src/asgard/skill_registry/` — Python package root
- `src/asgard/studio/` — Python package root
- `src/asgard/studio/tickets/` — Python package root
- `src/asgard/templates/` — Python package root
- `src/asgard/templates/roles/` — Python package root
- `src/asgard/tutor/` — Python package root
- `studio-shell/` — project boundary (package.json)
- `studio-shell/src-tauri/` — project boundary (Cargo.toml)
- `tests/` — test area
- `tests/agent/` — Python package root
- `tests/architecture/` — Python package root
- `tests/heimdall/` — Python package root
- `tests/map_graph/` — Python package root

## Detected verification

- Command: `python -m pytest` — Python test suite
- Command: `ruff check .` — Python lint
- Command: `ruff format --check .` — Python format check
- Command: `ty check` — Python type check

## Documents

- `MANUAL.md` — doc: MANUAL · sections: 오딘에게 보고하는 말투; API; Database; Naming
- `README.md` — doc: Asgard · sections: Install; Local or isolated execution; Tool Kernel; Skill and Plugin Registry; Documents (Sága); Project Map
- `docker/README.md` — doc: 컨테이너 하나 = 에이전트 하나 · sections: 먼저 — 이 폴더에 이미지가 둘 있고, 서로 다른 것이에요; 가르는 것은 두 줄이에요; 1. 호스트의 에이전트를 그대로 컨테이너에 (_asgard start_); 2. 컨테이너 전용 에이전트 여럿 (compose); 자격증명은 기본으로 안 넘어가요; 알아둘 것
- `docs/HANDOVER-command-surface-260821.md` — doc: 인수인계 — 명령 표면 점검과 수리 (2026-08-21) · sections: 지금 상태; 무엇을 잰 것인가; 고친 것 열다섯; 할 일 넷; 이 세션이 밟은 함정 다섯 — 되풀이하지 마라; 알아 둘 것 셋
- `docs/HANDOVER-large-files-260817.md` — doc: 인수인계 — 대형 파일 리팩토링 (2026-08-17) · sections: ① 끝난 것 — 릴리즈가 다시 실패하지 않게; ② 대형 파일 — churn×lines 상위 셋 완료 (26-08-17); 시작하는 법
- `docs/HANDOVER-se-baseline-260819.md` — doc: 인수인계 — 엔지니어링 기본 세팅 (2026-08-19) · sections: 지금 상태; 이번 변경이 한 것; 만진 파일 열셋; 할 일 셋; 앞 세션이 남긴 함정 둘 (되풀이하지 마라)
- `docs/HANDOVER-tutor-1on1-260820.md` — doc: 인수인계 — 튜터 1:1 학습 체계 (2026-08-20) · sections: 무엇을 만든 것인가; 설계를 정한 실측 — 이게 이 작업의 전부다; 선 것 넷; 지금 도는 모습; 판정 상태 — 여기가 인계의 핵심; 판정자가 직접 재서 통과시킨 것 (FAIL 근거가 아니다)
- `docs/MEMORY-AUDIT-260820.md` — doc: 메모리 전수 점검 — 2026-08-20 · sections: 한 줄; 1. 헤드라인 — 아무도 못 알아챈 한 주; 2. 그 위에 올라탄 결함 — 높음; 3. 중간; 4. 낮음; 5. 정상으로 확인된 것
- `docs/engineering-baseline.md` — doc: 코드 형상 문턱 — 결정표 · sections: 조사가 확인한 것 중 가장 중요한 사실; 결정표; 신설하지 않기로 한 축 셋; Lint Leakage 감사; 저장소가 값을 정하는 문; 근거
- `studio-shell/README.md` — doc: Asgard Studio native shell · sections: Run; Build; Icons
- `benchmarks/bragi-humanvoice/README.md` — doc: Bragi — human-voice bench · sections: Running; Part A — upstream labeled pairs; Part B — held-out human corpus; Part C — live A/B on a real model; Honest limits
- `benchmarks/conductor/README.md` — doc: Conductor 대조 — arXiv 2512.04388 의 평가 축을 Asgard 에 적용 · sections: 두 층; 못 재는 것
- `benchmarks/conductor/REPORT.md` — doc: Conductor 대조 + trinity-orchestrator.html §8 재검증 — 2026-08-06 · sections: 1. 정책 롤아웃 — 0-LLM (_policy_rollout.py_); 2. 결정론 마이크로벤치 — HEAD 재확인; 3. 라이브 대조 — 3아암 × 3과업 × 2반복 (18세션); 4. DIRECT 무세금 — §8 S5 재측정; 5. 하네스 레이턴시 — §8 표 재측정 (회귀); 6. 문서 §8 주장 대조표
- `benchmarks/continual-harness/REPORT.md` — doc: Continual Harness 대조 — 실측 (2026-08-12) · sections: 결과; 축별로 읽는 법; 이 벤치가 못 재는 것; 남는 경합 하나; 이 변경이 안 만들었지만 판정이 찾아 준 것; 미해결
- `benchmarks/core-loop/README.md` — doc: Asgard core loop A/B · sections: What this harness cannot measure: system-prompt size
- `benchmarks/cpu-profile/README.md` — doc: 훅 바깥 CPU·디스크 표면 — 실측 (2026-08-14) · sections: 상주 프로세스; Docker; 디스크 상태; 판정
- `benchmarks/cpu-profile/REPORT.md` — doc: Asgard CPU·메모리 소비 — 계측과 점검 (2026-08-14) · sections: 규모 — 한 턴이 태우는 값; 층별로 어디가 비싼가; 메모리; 최적화 후보; 이 계측이 못 잰 것; 정정 이력 — 판정자가 잡은 것
- `benchmarks/cpu-profile/findings-hooktax.md` — doc: 훅 프로세스 세금 — 실측 (2026-08-14) · sections: 이벤트별 합계 (웜 기준); 스크립트별 (콜드 = ___pycache___ 지운 뒤 첫 호출, 웜 = 그 뒤 반복의 중앙값); 도구 호출 1회가 띄우는 프로세스; 턴 세금 (Bash 를 대표 도구로); 아무 출력 없이 끝나는 훅; 이 하네스가 못 재는 것
- `benchmarks/cpu-profile/findings-hotpath.md` — doc: 훅 4종 지배항 — cProfile + importtime 실측 (2026-08-14) · sections: 결과 표; 훅별 상위 함수 5개 (cProfile, cumtime 기준); 4개 모두 공통 — 훅이 아니라 asgard CLI 자체가 무겁다; SQLite·파일 시스템 순회; 부록 — map-activate가 신선도 마커 없이 돌면 무엇이 잡히는가; 가장 큰 한 덩어리
- `benchmarks/cpu-profile/findings-item2-cli-lazy.md` — doc: 항목 2 — CLI 명령 그룹 지연 로딩 (2026-08-14) · sections: 무엇을 했나; 기준선과 변경 후; 지연이 실제로 먹었는가 — 직접 증거; _--help_ 대조; 재수출; 완성(completion)
- `benchmarks/cpu-profile/findings-item3-budget-cap.md` — doc: 항목 3 — budget-guard 트랜스크립트 증분 스캔 (2026-08-14) · sections: 무엇을 바꿨나; 배포본 동기화; 측정; 집계 동일성 — 이 항목의 안전 조건; 되돌아가는 조건 (전량 재스캔); 돌린 것과 exit code
- `benchmarks/cpu-profile/findings-item4-import-defer.md` — doc: 항목 4 — 기억 명령 파사드 임포트 지연 (2026-08-14) · sections: 먼저 물은 것: _scope-activate_ 가 왜 _project_memory_ 까지 타는가; 실제로 끊은 것; 줄어든 것 / 그대로인 것; 직접 증거 — 훅이 부르는 명령마다 _sys.modules_; 회수가 실제로 되는가; 검증
- `benchmarks/cpu-profile/findings-item5-tutor-fanout.md` — doc: 항목 5 — tutor 의 git 팬아웃 (2026-08-14) · sections: 무엇이 틀려 있었나; 고친 것 — 사다리 ① (필요 없는 호출을 안 한다); 실측; 출력 대조 — 설명이 얕아지지 않았나; 회귀; 남는 것 — 이 항목 밖, 다음 후보
- `benchmarks/cpu-profile/findings-item67-design.md` — doc: 항목 6·7 — 위험 분석과 설계 (2026-08-14) · sections: 항목 6 — MCP 세션 프로세스는 새지 않는다 (앞선 판단 정정); 항목 7 — 훅 디스패처 통합; 이 문서가 안 잰 것
- `benchmarks/cpu-profile/findings-item7-dispatcher.md` — doc: 항목 7 — 주입 훅 디스패처 (2026-08-14) · sections: 출력 동일성 — 배선의 선행 조건; 실측 — 구현했으므로 전후를 잰다; 도중에 드러난 것 셋; 배선 표와 다르게 한 것 하나; fail-open — 합치면 공짜가 아니다; _asgard sync_ 가 같이 깐 것 — 범위 밖으로 번졌다
- `benchmarks/cpu-profile/findings-memory.md` — doc: 메모리 실측 — Asgard 훅·프로세스 (u3-memory, cpu-profile-260814) · sections: 핵심 숫자 5줄; 1. 훅별 최대 RSS (RUSAGE_CHILDREN, macOS 바이트→MB); 2. 임포트 표면 RSS 계단 (RUSAGE_SELF, 단계마다 새 인터프리터); 3. tracemalloc 상위 할당 지점 (인프로세스, 훅 본문만); 4. 상주 프로세스 (_asgard-serve.mjs_, PID 44444); 5. 런타임 상태의 전체 로드 경로
- `benchmarks/cpu-profile/findings-semantic-lane.md` — doc: 시맨틱 레인 — 1.9GB 는 무엇을 사는가 (2026-08-14) · sections: 1. 플래그가 소스에서 무엇을 가르는가; 2. 품질 대조 — 12질의, 이 저장소의 실제 개인 기억 40페이지·벡터 40행 전수; 3. 자원 — 전/후 번갈아, _/usr/bin/time -l_; 4. 1.9GB 의 내역 — 임포트 계단 (_HF_HUB_OFFLINE=1_, 3회 최솟값); 5. 훅 경로 점검; 6. 못 잰 것
- `benchmarks/dispatch-parity/REPORT.md` — doc: 병렬 배차 실측 — worker 가 딜리버리 전문가를 부르는 길 (2026-08-12) · sections: 결과; 돌리는 법; 위임 경계 — 165조합; 실팬아웃 — 장부가 적은 것; 모드 B — 이 형상에서는 열리지 않는다; 이 벤치가 못 재는 것
- `benchmarks/engineering-principles/README.md` — doc: 엔지니어링 원칙 배터리 — 2026-08-19 실측 · sections: 이번 실행이 바꾼 것; 새로 덮은 것 — _unit-branchy_; 안 덮은 것과 그 이유; 이 배터리가 못 재는 것
- `benchmarks/grounding/REPORT.md` — doc: 근거 대조 벤치 — 어간 하한 __stem_floor_ · sections: 결과 (실측 26-08-01); 읽는 법; 권고; 이 벤치가 못 재는 것
- `benchmarks/hybrid-search/REPORT.md` — doc: 하이브리드 검색 벤치 — 2경로 vs 3경로 · sections: 검색 품질 (hit@k · MRR); 지연 (query() 벽시계)
- `benchmarks/latency/README.md` — doc: 회수 지연 — k6 부하 시험 · sections: 실행; 실측 (26-07-28 · Apple Silicon · 시맨틱 ON · 100페이지); 읽는 법; 한계
- `benchmarks/longmemeval/REPORT.md` — doc: LongMemEval — asgard 회수 벤치 · sections: 결과; 유형별 (R@5); 외부 대조 (각 저장소 공개값); 읽는 법; 후속: temporal-reasoning 4-암 실험 (n=133); 구절 리랭크 도입 후 (최종)
- `benchmarks/map-shortcut/REPORT.md` — doc: map 숏컷 벤치 — 주입면이 명령으로 라우팅하는가 (26-08-01 측정 · 26-08-13 회귀 수리) · sections: 질문; 방법 (harness.py); 고치기 전 (같은 저장소, 26-08-01 실측); 고친 뒤 (results.jsonl); 게이트가 한 번 빨간불이 됐다 — 번역 표에 맡긴 도움말 (26-08-12 발견, 26-08-13 수리); 남은 미스 — 닫힌 사전의 한계가 그 자리다
- `benchmarks/memory-graph/REPORT.md` — doc: 기억 그래프 벤치 — 명시 링크만 vs 파생 간선까지 (26-08-06) · sections: 질문; 방법; 결과; 읽는 법; 이 벤치가 못 재는 것; 대조 — 무엇을 가져왔고 무엇을 안 가져왔나
- `benchmarks/memory-title/REPORT.md` — doc: 제목 벤치 — 기억 한 장의 제목을 무엇으로 삼을 것인가 (26-08-19) · sections: 질문; 방법; 결과 (계기 5판, 모델 팔은 3회 실행); 판정; 실제 기억에 적용한 결과; 계기가 세 번 거짓말했고, 그 검사가 네 번째를 찾았다
- `benchmarks/project-memory/REPORT.md` — doc: 2차(프로젝트) 메모리 회수 벤치 · sections: 레인 1 · 로컬 문서 레인 hit@k (실측 26-08-01); 레인 2 · 관계 1홉 확장은 회수를 **올린다** (깎지 않는다); 레인 3 · 동언어 렉시컬 기권 정밀도; 제품 코드를 고쳐야만 잴 수 있는 것 (안 고쳤다)
- `benchmarks/roundtable/REPORT.md` — doc: 원탁 대조 벤치 — 좌석 여럿이 모델 하나보다 결함을 더 짚는가 (2026-08-14) · sections: 결과 — 중립 좌석으로 돌린 24짝; 첫 회차는 무효다 — 좌석이 답을 알고 있었다; 이 벤치가 찾아낸 제품 결함 둘; 기능 점검 — 실물로 확인한 것; 어떻게 쟀나; 이 벤치를 만들며 잡힌 것
- `benchmarks/shortcut-recall/REPORT.md` — doc: 숏컷 벤치 — recall 주입 on/off A/B (26-07-16, 36런) · sections: 질문; 방법 (harness.py); 결과 (results-36runs.jsonl — 런당 1행 append, 원본 그대로); 판정기 주의 (jsonl 의 _success_ 필드를 그대로 믿지 말 것); 한계
- `benchmarks/skill-uptake/REPORT.md` — doc: 스킬 도달 실측 — 배차가 새 스킬에 닿는가 (2026-08-13) · sections: 결과; 돌리는 법; 이 실측이 찾아낸 것; 이 벤치가 못 재는 것

## Public surfaces

- `src/asgard/providers.py` — public surface: class ProviderProfile; class ResolvedProvider; def cred_path(); def normalize_model_id(value); def is_agent_model_id(model_id)
- `benchmarks/bragi-humanvoice/build_corpus.py` — public surface: def korean_skills(base); def blader(base); def vietnamese(base); def japanese(base); def main()
- `benchmarks/conductor/aggregate.py` — public surface: def med(xs); def fmt(v, spec); def main()
- `benchmarks/continual-harness/harness.py` — public surface: def axis_mining_yield(); def axis_retry_diagnosis(); def axis_decision_survival(); def axis_remine_after_archive(); def main()
- `benchmarks/core-loop/harness.py` — public surface: def main()
- `benchmarks/cpu-profile/dispatch_check.py` — public surface: def payload_for(name); def channels(text); def run(argv, payload); def peak_rss(argv, payload); def before_argvs(name)
- `benchmarks/dispatch-parity/collect.py` — public surface: def role_of(role, agent); def collect(db_path, run); def main()
- `benchmarks/engineering-principles/run.py` — public surface: class Case; class Result; def measure(); def controls_missed(results); def report(results)
- `benchmarks/grounding/harness.py` — public surface: def floor_default(word); def floor_min(n); def floor_ratio(r); def floor_suffix(n); def floor_script(latin_suffix)
- `benchmarks/hybrid-search/harness.py` — public surface: def build_wiki(d, extra_distractors); def score_mode(d, semantic_on); def latency_mode(d, semantic_on, iters); def main(); def print_summary(rec)
- `benchmarks/latency/server.py` — public surface: def build(profile, pages); def main()
- `benchmarks/longmemeval/calibrate_dispersion.py` — public surface: def calibrate(rows); def main()
- `benchmarks/map-shortcut/ab_harness.py` — public surface: def build_sandbox(); def build_map(); def precheck(); def run_one(fid, task, judge, arm, rep); def report(rows)
- `benchmarks/memory-graph/harness.py` — public surface: def build_wiki(d, extra); def score_arm(d, mode); def graph_shape(d); def main()
- `benchmarks/memory-title/harness.py` — public surface: def starts_with_speaker(title); def corpus(limit); def legacy_derive_title(body); def title_for(arm, body); def title_terms(title); uses `src/asgard/memory/manager.py`
- `benchmarks/norn-evolution/harness.py` — public surface: def build_wiki(d); def run_norn(d, truth); def evaluate(d, truth, insight_slugs); def run_replicate(rep); def main()
- `benchmarks/project-memory/corpus.py` — public surface: def build(root)
- `benchmarks/project_memory_projection.py` — public surface: def local_benchmark(files); def live_benchmark(); def main(); uses `src/asgard/memory_context.py`
- `benchmarks/roundtable/harness.py` — public surface: def seat_root(); def deterministic_hit(text, keys); def solo(case, provider, model); def table(case, backends, rounds); def judge(root, case, answer, provider, model, …)
- `benchmarks/shortcut-recall/harness.py` — public surface: def build_sandbox(); def build_memory(); def precheck(); def run_one(fid, task, judge, arm, rep); def main()
- `benchmarks/skill-uptake/harness.py` — public surface: def measure_reach(root); def measure_specialists(root); def measure_semantic(root); def measure_shape(root); def measure_load(root)
- `studio-shell/src-tauri/icons/build_icons.py` — public surface: def superellipse(box, n, steps); def body_mask(size); def night(size); def master(); def main()
- `tests/agent/agent_base.py` — public surface: class Base
- `tests/architecture/test_layered.py` — public surface: class TestLayeredArchitecture
- `tests/cli_boundary.py` — public surface: def strip_ansi(text); class Outcome; def run_cli(*argv, stdin)
- `tests/heimdall/harness.py` — public surface: class FakeSession; class FakeHeimdall; def worker(files, root, text); def verifier(verdict, observed, structural, sig, why, …); def thinker(plan, commands); uses `src/asgard/i18n.py`, `src/asgard/providers.py`
- `tests/hookscaffold.py` — public surface: def deploy_library(hooks_dir); def deploy_cli(bin_dir); def isolated_home_env(home, **extra); def until(predicate, timeout, step)
- `tests/map_graph/map_base.py` — public surface: class Base
- `tests/memory/memory_base.py` — public surface: def memory_semantic_env(); class MemoryBase
- `tests/test_activity.py` — public surface: class ActivityEmitCase; class ActivityReadCase; class StudioAbsorbCase; class SessionEmitCase; class StudioLiveRunCase
- `tests/test_adversarial_gate.py` — public surface: def run(script, args, stdin, cwd, env_extra); class AdversarialBase; class TestAdversarialVectors; class TestEncodingDisarm; class TestSessionIdentityDisarm
- `tests/test_agent_cli_config.py` — public surface: class AgentCliConfigTest
- `tests/test_agent_env_propagation.py` — public surface: class EnvPropagationTest
- `tests/test_agent_hook.py` — public surface: class AgentHookBase; class TestRenderIsSingleSource; class TestPlacementIsSingleSource; class TestContainerHome; class TestClientSchemas
- `tests/test_agent_open_cli.py` — public surface: class AgentOpenCliTest
- `tests/test_agent_picker_cli.py` — public surface: class AgentPickerCliTest
- `tests/test_automations.py` — public surface: class TestDueComputation; class TestStoreAndOutcome; class TestAutomationCLI
- `tests/test_bragi.py` — public surface: class TestLanguageDetection; class TestDetection; class TestFalsePositiveGuards; class TestStatisticalFeatures; class TestKoreanSentenceCompletion
- `tests/test_bridge.py` — public surface: class TestScaffold; class TestSkillBody
- `tests/test_budget_guard.py` — public surface: class TestLedger; class TestIncrementalScan; class TestCostUnits; class TestVerdict; class TestWarnThresholdIsAShareOfTheCeiling; uses `src/asgard/commands/budget.py`
- `tests/test_cancellation.py` — public surface: class TestBashCancel; class TestSessionCancel
- `tests/test_charter.py` — public surface: class TestLoadCharter; class TestNote; uses `src/asgard/charter.py`
- `tests/test_charter_hook.py` — public surface: class CharterHookBase; class TestCharterHook; uses `src/asgard/charter.py`
- `tests/test_claude_native.py` — public surface: def tearDownModule(); class TestProfile; class TestNativeClient; class TestTransport; class TestStreaming; uses `src/asgard/providers.py`
- `tests/test_cli_surface.py` — public surface: class TestMachineOutputNeedsAFlag; class TestQuietOwnsDashQ; class TestJsonCoverage; class TestShortFlagMeansOneThing; class TestOneNamePerBehaviour
- `tests/test_code_map.py` — public surface: class CodeMapBase; class TestProjectMap; class TestMapCLI; class TestLanguageSurfaceCoverage
- `tests/test_code_style.py` — public surface: class Detection; class Declaration; class Ownership; class Parsing; class Attribution
- `tests/test_color_capability.py` — public surface: def test_windows_console_is_color_capable(monkeypatch, _clean_env); def test_windows_console_without_vt_stays_plain(monkeypatch, _clean_env); def test_no_color_wins_on_windows_without_touching_the_console(monkeypatch, _clean_env); def test_redirected_stdout_is_never_colored(monkeypatch, _clean_env); def test_posix_still_treats_unset_term_as_dumb(monkeypatch, _clean_env)

## Navigation contract

- Read `PROJECT.md` first, then the matching human-authored area map if present.
- A `## Documents` row lists a document's own title and sections — open it before re-deriving what it already records.
- Verify target definitions and usages from source before planning or editing.
- Structural changes refresh this managed map before Verifier hashing; use `asgard map check` in CI.
