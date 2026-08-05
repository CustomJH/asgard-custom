<!-- asgard:project-map schema=3 -->
# Project Map — asgard

> Asgard managed orientation map. Regenerate with `asgard map update`; do not hand-edit this file.
> It is a navigation hint, not completion evidence: re-read every path used by a plan.

## Orientation

- Project root: `./`
- Languages by observed source files: Python (566), JavaScript (6), Rust (2)
- Evidence scan: 778 files; 36 landmarks

## Landmarks

- `README.md` — project overview and operating guide
- `docker/` — container and deployment area
- `docker/asgard-k6/` — project boundary (docker-compose.yml)
- `docker/asgard-project-memory/` — project boundary (docker-compose.yml)
- `pyproject.toml` — Python project manifest
- `src/` — primary source area
- `src/asgard/` — Python package root
- `src/asgard/agent/` — Python package root
- `src/asgard/agent/heimdall/` — Python package root
- `src/asgard/agent/heimdall/core/` — Python package root
- `src/asgard/agent/heimdall/trinity/` — Python package root
- `src/asgard/agent/repl/` — Python package root
- `src/asgard/agent/tools/` — Python package root
- `src/asgard/cli/` — Python package root
- `src/asgard/commands/` — Python package root
- `src/asgard/commands/doctor/` — Python package root
- `src/asgard/commands/memory/` — Python package root
- `src/asgard/commands/memory_dashboard/` — Python package root
- `src/asgard/commands/plan_api/` — Python package root
- `src/asgard/commands/studio/` — Python package root
- `src/asgard/hooks/` — Python package root
- `src/asgard/hooks/asgard_hooklib/` — Python package root
- `src/asgard/map_graph/` — Python package root
- `src/asgard/memory/` — Python package root
- `src/asgard/memory_bridge/` — Python package root
- `src/asgard/orchestration/` — Python package root
- `src/asgard/plan/` — Python package root
- `src/asgard/project_memory/` — Python package root
- `src/asgard/project_memory_backends/` — Python package root
- `src/asgard/studio/` — Python package root
- `src/asgard/studio/tickets/` — Python package root
- `src/asgard/templates/` — Python package root
- `src/asgard/templates/roles/` — Python package root
- `studio-shell/` — project boundary (package.json)
- `studio-shell/src-tauri/` — project boundary (Cargo.toml)
- `tests/` — test area

## Detected verification

- Command: `python -m pytest` — Python test suite
- Command: `ruff check .` — Python lint
- Command: `ruff format --check .` — Python format check
- Command: `ty check` — Python type check

## Documents

- `AGENTS.md` — doc: asgard-custom — Agent Guide · sections: Asgard — Identity (Worldview); Asgard — Canon (Common Laws); Asgard — Trinity Loop (Heimdall Orchestration); Asgard — Codebase Map (.asgard/map/); Asgard — Lagom (Minimalism Contract); Asgard — Bragi (Human Voice)
- `MANUAL.md` — doc: MANUAL · sections: API; Database; Naming
- `README.md` — doc: Asgard · sections: Install; Local or isolated execution; Tool Kernel; Skill and Plugin Registry; Documents (Sága); Project Map
- `docker/README.md` — doc: 컨테이너 하나 = 에이전트 하나 · sections: 먼저 — 이 폴더에 이미지가 둘 있고, 서로 다른 것이에요; 가르는 것은 두 줄이에요; 1. 호스트의 에이전트를 그대로 컨테이너에 (_asgard start_); 2. 컨테이너 전용 에이전트 여럿 (compose); 자격증명은 기본으로 안 넘어가요; 알아둘 것
- `studio-shell/README.md` — doc: Asgard Studio native shell · sections: Run; Build; Icons
- `benchmarks/bragi-humanvoice/README.md` — doc: Bragi — human-voice bench · sections: Running; Part A — upstream labeled pairs; Part B — held-out human corpus; Part C — live A/B on a real model; Honest limits
- `benchmarks/conductor/README.md` — doc: Conductor 대조 — arXiv 2512.04388 의 평가 축을 Asgard 에 적용 · sections: 두 층; 못 재는 것
- `benchmarks/conductor/REPORT.md` — doc: Conductor 대조 + trinity-orchestrator.html §8 재검증 — 2026-08-06 · sections: 1. 정책 롤아웃 — 0-LLM (_policy_rollout.py_); 2. 결정론 마이크로벤치 — HEAD 재확인; 3. 라이브 대조 — 3아암 × 3과업 × 2반복 (18세션); 4. DIRECT 무세금 — §8 S5 재측정; 5. 하네스 레이턴시 — §8 표 재측정 (회귀); 6. 문서 §8 주장 대조표
- `benchmarks/core-loop/README.md` — doc: Asgard core loop A/B · sections: What this harness cannot measure: system-prompt size
- `benchmarks/grounding/REPORT.md` — doc: 근거 대조 벤치 — 어간 하한 __stem_floor_ · sections: 결과 (실측 26-08-01); 읽는 법; 권고; 이 벤치가 못 재는 것
- `benchmarks/hybrid-search/REPORT.md` — doc: 하이브리드 검색 벤치 — 2경로 vs 3경로 · sections: 검색 품질 (hit@k · MRR); 지연 (query() 벽시계)
- `benchmarks/latency/README.md` — doc: 회수 지연 — k6 부하 시험 · sections: 실행; 실측 (26-07-28 · Apple Silicon · 시맨틱 ON · 100페이지); 읽는 법; 한계
- `benchmarks/longmemeval/REPORT.md` — doc: LongMemEval — asgard 회수 벤치 · sections: 결과; 유형별 (R@5); 외부 대조 (각 저장소 공개값); 읽는 법; 후속: temporal-reasoning 4-암 실험 (n=133); 구절 리랭크 도입 후 (최종)
- `benchmarks/map-shortcut/REPORT.md` — doc: map 숏컷 벤치 — 주입면이 명령으로 라우팅하는가 (26-08-01) · sections: 질문; 방법 (harness.py); 고치기 전 (같은 저장소, 26-08-01 실측); 고친 뒤 (results.jsonl); 남은 미스 — 닫힌 사전의 한계가 그 자리다; 정직성 기록 — 사전을 사후에 늘렸다
- `benchmarks/memory-graph/REPORT.md` — doc: 기억 그래프 벤치 — 명시 링크만 vs 파생 간선까지 (26-08-06) · sections: 질문; 방법; 결과; 읽는 법; 이 벤치가 못 재는 것; 대조 — 무엇을 가져왔고 무엇을 안 가져왔나
- `benchmarks/project-memory/REPORT.md` — doc: 2차(프로젝트) 메모리 회수 벤치 · sections: 레인 1 · 로컬 문서 레인 hit@k (실측 26-08-01); 레인 2 · 관계 1홉 확장은 회수를 **올린다** (깎지 않는다); 레인 3 · 동언어 렉시컬 기권 정밀도; 제품 코드를 고쳐야만 잴 수 있는 것 (안 고쳤다)
- `benchmarks/shortcut-recall/REPORT.md` — doc: 숏컷 벤치 — recall 주입 on/off A/B (26-07-16, 36런) · sections: 질문; 방법 (harness.py); 결과 (results-36runs.jsonl — 런당 1행 append, 원본 그대로); 판정기 주의 (jsonl 의 _success_ 필드를 그대로 믿지 말 것); 한계
- `docker/asgard-k6/README.md` — doc: asgard-k6 — 부하 시험 러너 이미지 · sections: 왜 우리 이름의 이미지인가; 볼륨은 프로젝트 것이다; 수동 스택
- `docker/asgard-project-memory/README.md` — doc: asgard-project-memory — 2차 메모리(프로젝트 메모리) Hindsight 서버 · sections: 기본 구성 (2026-07-23 확정); 백엔드 제약 — 이 구성의 모든 상한이 여기서 나온다; 기동; 뱅크 단위 설정 — compose 가 못 닿는 층; 클라이언트; 설계 결정
- `tests/load/README.md` — doc: Project memory load harness (k6, Docker) — 실측 기록 · sections: 실행; 실측 (Hindsight 0.8.3 · Docker · M-series · 2026-07-28); 정정 — 원인은 링크 밀도가 아니었다 (26-07-28 3차, 실서버 계측)
- `src/asgard/assets/k6_kit/README.md` — doc: asgard-k6 · sections: 왜 selftest 가 먼저인가; 시나리오; 표면 뒤의 것들; 도커 쪽 집
- `src/asgard/templates/roles/asgard-eitri.md` — doc: asgard-eitri — ⚒️ Build/CI/packaging specialist (Delivery)
- `src/asgard/templates/roles/asgard-freyja.md` — doc: asgard-freyja — UI/UX specialist (Delivery)
- `src/asgard/templates/roles/asgard-loki.md` — doc: asgard-loki — 🐍 Adversarial specialist (Delivery)
- `src/asgard/templates/roles/asgard-mimir.md` — doc: asgard-mimir — 🧭 Code-guide specialist (Delivery)
- `src/asgard/templates/roles/asgard-planner.md` — doc: asgard-planner — 제품 기획 에이전트 · sections: 기본 계약; 진행 방식; 판단 경계
- `src/asgard/templates/roles/asgard-thinker.md` — doc: asgard-thinker — 🧠 Strategy (Trinity)
- `src/asgard/templates/roles/asgard-thor-lead.md` — doc: asgard-thor-lead — 🛡 Backend squad lead (Delivery orchestration)
- `src/asgard/templates/roles/asgard-thor.md` — doc: asgard-thor — ⚡ Backend specialist (Delivery)
- `src/asgard/templates/roles/asgard-ullr.md` — doc: asgard-ullr — 🏹 Exploration specialist (Delivery)
- `src/asgard/templates/roles/asgard-verifier.md` — doc: asgard-verifier — ⚖️ Verdict (Trinity) · sections: What PASS costs; Reporting a defect; This repository's rules
- `src/asgard/templates/roles/asgard-worker.md` — doc: asgard-worker — 🔨 Execution (Trinity)

## Public surfaces

- `src/asgard/providers.py` — public surface: class ProviderProfile; class ResolvedProvider; def cred_path(); def normalize_model_id(value); def is_agent_model_id(model_id)
- `benchmarks/bragi-humanvoice/build_corpus.py` — public surface: def korean_skills(base); def blader(base); def vietnamese(base); def japanese(base); def main()
- `benchmarks/conductor/aggregate.py` — public surface: def med(xs); def fmt(v, spec); def main()
- `benchmarks/core-loop/harness.py` — public surface: def main()
- `benchmarks/grounding/harness.py` — public surface: def floor_default(word); def floor_min(n); def floor_ratio(r); def floor_suffix(n); def floor_script(latin_suffix)
- `benchmarks/hybrid-search/harness.py` — public surface: def build_wiki(d, extra_distractors); def score_mode(d, semantic_on); def latency_mode(d, semantic_on, iters); def main(); def print_summary(rec)
- `benchmarks/latency/server.py` — public surface: def build(profile, pages); def main()
- `benchmarks/longmemeval/calibrate_dispersion.py` — public surface: def calibrate(rows); def main()
- `benchmarks/map-shortcut/ab_harness.py` — public surface: def build_sandbox(); def build_map(); def precheck(); def run_one(fid, task, judge, arm, rep); def report(rows)
- `benchmarks/memory-graph/harness.py` — public surface: def build_wiki(d, extra); def score_arm(d, mode); def graph_shape(d); def main()
- `benchmarks/norn-evolution/harness.py` — public surface: def build_wiki(d); def run_norn(d, truth); def evaluate(d, truth, insight_slugs); def run_replicate(rep); def main()
- `benchmarks/project-memory/corpus.py` — public surface: def build(root)
- `benchmarks/project_memory_projection.py` — public surface: def local_benchmark(files); def live_benchmark(); def main(); uses `src/asgard/memory_context.py`
- `benchmarks/shortcut-recall/harness.py` — public surface: def build_sandbox(); def build_memory(); def precheck(); def run_one(fid, task, judge, arm, rep); def main()
- `studio-shell/src-tauri/icons/build_icons.py` — public surface: def superellipse(box, n, steps); def body_mask(size); def night(size); def master(); def main()
- `tests/cli_boundary.py` — public surface: def strip_ansi(text); class Outcome; def run_cli(*argv, stdin)
- `tests/hookscaffold.py` — public surface: def deploy_library(hooks_dir); def deploy_cli(bin_dir); def until(predicate, timeout, step)
- `tests/test_activity.py` — public surface: class ActivityEmitCase; class ActivityReadCase; class StudioAbsorbCase; class SessionEmitCase; class StudioLiveRunCase
- `tests/test_adversarial_gate.py` — public surface: def run(script, args, stdin, cwd, env_extra); class AdversarialBase; class TestAdversarialVectors; class TestEncodingDisarm; class TestSessionIdentityDisarm
- `tests/test_agent.py` — public surface: class Base; class TestEditor; class TestBash; class TestTruncation; class TestBashDestructiveGuard; uses `src/asgard/agent/quest_bridge.py`
- `tests/test_agent_cli_config.py` — public surface: class AgentCliConfigTest
- `tests/test_agent_env_propagation.py` — public surface: class EnvPropagationTest
- `tests/test_agent_hook.py` — public surface: class AgentHookBase; class TestRenderIsSingleSource; class TestPlacementIsSingleSource; class TestContainerHome; class TestClientSchemas
- `tests/test_agent_open_cli.py` — public surface: class AgentOpenCliTest
- `tests/test_agent_picker_cli.py` — public surface: class AgentPickerCliTest
- `tests/test_architecture.py` — public surface: class TestLayeredArchitecture; class TestRoleContract; class TestPackageInternals; class TestStudioPackage
- `tests/test_automations.py` — public surface: class TestDueComputation; class TestStoreAndOutcome; class TestAutomationCLI
- `tests/test_bragi.py` — public surface: class TestLanguageDetection; class TestDetection; class TestFalsePositiveGuards; class TestStatisticalFeatures; class TestGrading
- `tests/test_bridge.py` — public surface: class TestScaffold; class TestSkillBody
- `tests/test_budget_guard.py` — public surface: class TestLedger; class TestCostUnits; class TestVerdict; class TestHookProtocol; class TestFailOpen; uses `src/asgard/commands/budget.py`
- `tests/test_cancellation.py` — public surface: class TestBashCancel; class TestSessionCancel
- `tests/test_charter.py` — public surface: class TestLoadCharter; class TestNote; uses `src/asgard/charter.py`
- `tests/test_charter_hook.py` — public surface: class CharterHookBase; class TestCharterHook; uses `src/asgard/charter.py`
- `tests/test_claude_native.py` — public surface: class TestProfile; class TestNativeClient; class TestTransport; class TestStreaming; class TestCustomToolBridge; uses `src/asgard/agent/session.py`, `src/asgard/providers.py`
- `tests/test_cli_surface.py` — public surface: class TestMachineOutputNeedsAFlag; class TestQuietOwnsDashQ; class TestJsonCoverage; class TestShortFlagMeansOneThing; class TestOneNamePerBehaviour
- `tests/test_code_map.py` — public surface: class CodeMapBase; class TestProjectMap; class TestMapCLI; class TestLanguageSurfaceCoverage
- `tests/test_color_capability.py` — public surface: def test_windows_console_is_color_capable(monkeypatch, _clean_env); def test_windows_console_without_vt_stays_plain(monkeypatch, _clean_env); def test_no_color_wins_on_windows_without_touching_the_console(monkeypatch, _clean_env); def test_redirected_stdout_is_never_colored(monkeypatch, _clean_env); def test_posix_still_treats_unset_term_as_dumb(monkeypatch, _clean_env)
- `tests/test_completions.py` — public surface: class TestSurfaceDerivation; class TestRendererCoversTheApp; class TestOneDoorForWindows; class TestRenderAnchors; class TestBashFunctional
- `tests/test_container_agent.py` — public surface: def machine(tmp_path, monkeypatch); def test_container_gets_the_agent_home_as_a_container_path(machine, monkeypatch); def test_container_mounts_the_agent_home(machine, monkeypatch); def test_host_path_never_leaks_into_the_container_env(machine, monkeypatch); def test_profile_name_does_not_ride_along(machine, monkeypatch)
- `tests/test_craft.py` — public surface: class UnitShapeTest; class ResourceLifetimeTest; class CostTest; class RatchetTest; class MoveTest
- `tests/test_craft_fix.py` — public surface: class RepairTest; class TableTest; class NotACommentTest; class EncodingTest; class ApplyTest; uses `src/asgard/commands/craft.py`
- `tests/test_craft_gate_e2e.py` — public surface: class ShippedHookRuns; class RepairLane
- `tests/test_craft_gate_hook.py` — public surface: class WriteFilter; class MergedJudgement; class RepairLane; class Receipt; class Reason
- `tests/test_craft_lang.py` — public surface: class ScrubTest; class ExtractTest; class DepthTest; class CMemoryTest; class CBoundsAndCostTest
- `tests/test_craft_note.py` — public surface: class MetaphorTest; class JargonTest; class DocstringTest; class ExtractionTest; class RatchetTest; uses `src/asgard/craft_rules.py`
- `tests/test_doctor_shape.py` — public surface: class TestDoctorJsonShape; class TestTrinityRowNames; class TestPiecesStandAlone; class TestHookInterpreterIsExecuted; class TestConfigReading
- `tests/test_document_tools.py` — public surface: class DocumentToolTest; class BundledDocumentSkillTest; uses `src/asgard/agent/tool_kernel.py`
- `tests/test_eitri.py` — public surface: class TestScaffold; class TestSkillBodies; class TestSkillResolver; class TestWiring; uses `src/asgard/templates/eitri.py`

## Navigation contract

- Read `PROJECT.md` first, then the matching human-authored area map if present.
- A `## Documents` row lists a document's own title and sections — open it before re-deriving what it already records.
- Verify target definitions and usages from source before planning or editing.
- Structural changes refresh this managed map before Verifier hashing; use `asgard map check` in CI.
