<!-- asgard:project-map schema=2 -->
# Project Map — asgard

> Asgard managed orientation map. Regenerate with `asgard map update`; do not hand-edit this file.
> It is a navigation hint, not completion evidence: re-read every path used by a plan.

## Orientation

- Project root: `./`
- Languages by observed source files: Python (260), Rust (2), JavaScript (1)
- Evidence scan: 1219 files; 25 landmarks

## Landmarks

- `README.md` — project overview and operating guide
- `archive/asgard-studio/src/asgard/commands/studio_dashboard/` — Python package root
- `desktop/` — project boundary (package.json)
- `desktop/src-tauri/` — project boundary (Cargo.toml)
- `docker/` — container and deployment area
- `docker/asgard-common-memory/` — project boundary (docker-compose.yml)
- `docker/asgard-common-memory2/` — project boundary (docker-compose.yml)
- `pyproject.toml` — Python project manifest
- `src/` — primary source area
- `src/asgard/` — Python package root
- `src/asgard/agent/` — Python package root
- `src/asgard/agent/heimdall/` — Python package root
- `src/asgard/cli.py` — CLI entrypoint `asgard`
- `src/asgard/commands/` — Python package root
- `src/asgard/commands/memory_dashboard/` — Python package root
- `src/asgard/commands/plan_dashboard/` — Python package root
- `src/asgard/hooks/` — Python package root
- `src/asgard/map_graph/` — Python package root
- `src/asgard/memory/` — Python package root
- `src/asgard/memory_bridge/` — Python package root
- `src/asgard/project_memory/` — Python package root
- `src/asgard/project_memory_backends/` — Python package root
- `src/asgard/templates/` — Python package root
- `src/asgard/templates/roles/` — Python package root
- `tests/` — test area

## Detected verification

- Command: `python -m pytest` — Python test suite
- Command: `ruff check .` — Python lint
- Command: `ruff format --check .` — Python format check
- Command: `ty check` — Python type check

## Public surfaces

- `src/asgard/agent/session.py` — public surface: class TurnCancelled; class ProviderRetriesExhausted; class SessionResult; def make_client(rp); class AgentSession
- `src/asgard/providers.py` — public surface: class ProviderProfile; class ResolvedProvider; def normalize_model_id(value); def is_agent_model_id(model_id); def load_credentials()
- `src/asgard/agent/tool_kernel.py` — public surface: def cc_tools_for_role(role); class ToolResult; class ToolContext; class ToolState; class ToolSpec
- `src/asgard/charter.py` — public surface: def load_charter(root); def note(root, section)
- `src/asgard/templates/freyja.py` — public surface: def resolve_freyja_skills(task); def freyja_core_skill()
- `src/asgard/agent/heimdall/classify.py` — public surface: def memory_write_intent(request); def has_write_verbs(request); def classify_heuristic(request); def classify_api_error(e)
- `src/asgard/agent/prompt_cache.py` — public surface: def cache_settings(root); def cached_request(system, messages, ttl); def openai_cache_markers_supported(base_url, model); def cached_openai_request(sys_msgs, messages, ttl)
- `src/asgard/agent/rate_limit.py` — public surface: class RpmLimiter; def effective_rpm(rp); def limiter_for(rp); def throttle(rp, cancel); def retry_after_seconds(e, attempt)
- `src/asgard/agent/unit_workspace.py` — public surface: class WorkspaceError; class UnitArtifact; class UnitPatch; class UnitWorkspace
- `src/asgard/cli.py` — public surface: def doctor(json_, quiet); def start(check, provider, model, cont, execution, …); def auth_login(provider); def auth_status(provider); def auth_logout(provider)
- `src/asgard/commands/start.py` — public surface: def preflight(root, provider, model); def run_start(check_only, provider, model, cont, execution, …); def run_prompt(prompt, provider, model, json_out, resume, …)
- `src/asgard/commands/sync.py` — public surface: def merge_agents_md(existing, new); def merge_cc_settings(existing, new); def sync_project(root, cc, cursor, codex, dry_run); def run_sync(dry_run, list_only)
- `src/asgard/hooks/readonly_guard.py` — public surface: def is_readonly_bash_safe(command, root); def main()
- `src/asgard/hooks/release_guard.py` — public surface: def blocked_reason(command); def main()
- `src/asgard/io_journal.py` — public surface: def journal_path(root); def enabled(); def call_started(root, provider, model, transport, role); def call_returned(root, call_id, duration_ms, error, counts, …)
- `src/asgard/memory_context.py` — public surface: def filter_project_hits(root, cfg, hits, max_results, query); def project_recall_note(query, start, max_results); def learned_skills_note(query, start, cap); def recall_note(query, start, personal_k, project_k, include_skills)
- `src/asgard/picker.py` — public surface: class Option; def available(); def pick(title, options, default, manual_hint)
- `src/asgard/templates/eitri.py` — public surface: def resolve_eitri_skills(task)
- `src/asgard/templates/lagom.py` — public surface: def render_lagom(mode)
- `src/asgard/templates/mimir.py` — public surface: def resolve_mimir_skills(task); def mimir_note(task); def mimir_core_skill()
- `src/asgard/templates/thor.py` — public surface: def resolve_thor_skills(task); def thor_core_skill(); def eitri_core_skill()
- `src/asgard/templates/worker.py` — public surface: def resolve_worker_skills(task)
- `archive/asgard-studio/src/asgard/commands/studio.py` — public surface: def slugify(text, d); def create_project(brief, name, d); def set_engine(name, d); def use_template(name, brief, d); def append_instruction(slug, text, d)
- `archive/asgard-studio/src/asgard/commands/studio_dashboard/data.py` — public surface: def studio_dir(); def ensure_home(d); def slug_ok(slug); def read_settings(d); def engine(d)
- `archive/asgard-studio/src/asgard/commands/studio_dashboard/ops.py` — public surface: def run_list(json_out); def run_path()
- `archive/asgard-studio/src/asgard/commands/studio_dashboard/server.py` — public surface: def host_allowed(host_header); def origin_allowed(origin); def dispatch(method, path, params, d); def dispatch_post(path, payload, d); def run_dashboard(port, host, open_browser, focus)
- `archive/asgard-studio/tests/test_studio_dashboard.py` — public surface: class StudioBase; class TestDataAssembly; class TestArtifactBoundary; class TestDispatch; class TestTemplatesAndEngine
- `docker/asgard-common-memory2/llm-benchmark.py` — public surface: def request_json(url, payload, timeout); def rate(count, duration_ns); def main()
- `docker/asgard-common-memory2/provider-readiness.py` — public surface: def get_json(url, api_key); def main()
- `src/asgard/agent/claude_native.py` — public surface: class UsageCapError; def detect_auth(); class ClaudeNativeClient; def make_native_client(); def run(sess, user_content)
- `src/asgard/agent/heimdall/core.py` — public surface: class SessionLike; class Heimdall
- `src/asgard/agent/heimdall/dispatch.py` — public surface: class DeliveryDispatch
- `src/asgard/agent/heimdall/roles.py` — public surface: def delivery_canon_note(root, task); def worker_canon_hint(root, task)
- `src/asgard/agent/heimdall/trinity.py` — public surface: class TrinityRun
- `src/asgard/agent/heimdall/waves.py` — public surface: class WaveRunner
- `src/asgard/agent/onboard.py` — public surface: def can_prompt(); def select_model(root, rp, persist); def select_model_id(root, rp, model, persist); def onboard(root, preselect)
- `src/asgard/agent/repl.py` — public surface: def is_light_bg(); def banner(rp); def statusline(root, rp, usage); def prompt(default_text, auto_submit); def slash(cmd, root, rp)
- `src/asgard/agent/tools.py` — public surface: class ToolError; def run_web_fetch(_root, tool_input); def run_document(root, tool_input); def validate_bash_command(root, command); def run_bash(root, tool_input, cancel)
- `src/asgard/agent/turn_store.py` — public surface: def append_turn(root, request, response); def load_turns(root, limit)
- `src/asgard/assets/skill_plugins/21st-dev/skills/21st-cli-use/scripts/21st.py` — public surface: def main(argv)
- `src/asgard/assets/skill_plugins/aceternity-ui/skills/aceternity-ui/scripts/aceternity.py` — public surface: def main(argv)
- `src/asgard/assets/skill_plugins/google-design-md/skills/design-md-review/scripts/design_md.py` — public surface: class UniqueLoader; def lint(content); def main(argv)
- `src/asgard/assets/skill_plugins/hwpx-skill/skills/hwpx/asgard_hwpx.py` — public surface: def main(argv)
- `src/asgard/assets/skill_plugins/hwpx-skill/skills/hwpx/scripts/analyze_template.py` — public surface: def get_text(el); def analyze_fonts(root); def analyze_borderfills(root); def analyze_charprops(root); def analyze_paraprops(root)
- `src/asgard/assets/skill_plugins/hwpx-skill/skills/hwpx/scripts/bodojaryo.py` — public surface: def build_section(meta, section); def generate(meta, output); def main()
- `src/asgard/assets/skill_plugins/hwpx-skill/skills/hwpx/scripts/build_hwpx.py` — public surface: def validate_xml(filepath); def update_metadata(content_hpf, title, creator); def pack_hwpx(input_dir, output_path); def validate_hwpx(hwpx_path); def build(template, header_override, section_override, title, creator, …)
- `src/asgard/assets/skill_plugins/hwpx-skill/skills/hwpx/scripts/build_problem_answer_sheet.py` — public surface: def pack_hwpx(work, output); def cell_xml(text, col, row, width, height, …); def make_header_table(label, subject, unit, title, subtitle); def make_one_col_table(rows, row_h, charpr, parapr); def prompt(text)
- `src/asgard/assets/skill_plugins/hwpx-skill/skills/hwpx/scripts/clone_form.py` — public surface: def extract_texts(hwpx_path); def analyze(hwpx_path); def auto_analyze(hwpx_path, output_json); def clone(src_path, dst_path, replacements, keywords, title, …); def validate_result(src_path, dst_path, replacements, keywords)

## Navigation contract

- Read `PROJECT.md` first, then the matching human-authored area map if present.
- Verify target definitions and usages from source before planning or editing.
- Structural changes refresh this managed map before Verifier hashing; use `asgard map check` in CI.
