<!-- asgard:project-map schema=2 -->
# Project Map — asgard

> Asgard managed orientation map. Regenerate with `asgard map update`; do not hand-edit this file.
> It is a navigation hint, not completion evidence: re-read every path used by a plan.

## Orientation

- Project root: `./`
- Languages by observed source files: Python (261), TypeScript (243), Rust (2), JavaScript (1)
- Evidence scan: 3363 files; 31 landmarks

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
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/` — project boundary (package.json)
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/packages/mcp/` — project boundary (package.json)
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/skills/vanadis-lab-02-design-harness/runs/v4-self-test/fixtures/junior-designer/` — project boundary (package.json)
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/skills/vanadis-lab-02-design-harness/runs/v4-self-test/fixtures/senior-dev/` — project boundary (package.json)
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/skills/vanadis-lab-02-design-harness/runs/v4-self-test/fixtures/vibe-coder/` — project boundary (package.json)
- `src/asgard/assets/skill_plugins/freyja-design/skills/asgard-freyja-design/references/vanadis/web/` — project boundary (package.json)
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
- `src/asgard/settings.py` — public surface: def global_dir(); def global_path(); def project_path(root); def load_global(); def load_project(root)
- `src/asgard/templates/eitri.py` — public surface: def resolve_eitri_skills(task)
- `src/asgard/templates/freyja.py` — public surface: def resolve_freyja_skills(_task); def freyja_core_skill()
- `src/asgard/templates/lagom.py` — public surface: def render_lagom(mode)
- `src/asgard/templates/mimir.py` — public surface: def resolve_mimir_skills(task); def mimir_note(task); def mimir_core_skill()
- `src/asgard/templates/thor.py` — public surface: def resolve_thor_skills(task); def thor_core_skill(); def eitri_core_skill()
- `src/asgard/templates/worker.py` — public surface: def resolve_worker_skills(task)
- `archive/asgard-studio/src/asgard/commands/studio.py` — public surface: def slugify(text, d); def create_project(brief, name, d); def set_engine(name, d); def use_template(name, brief, d); def append_instruction(slug, text, d)
- `archive/asgard-studio/src/asgard/commands/studio_dashboard/data.py` — public surface: def studio_dir(); def ensure_home(d); def slug_ok(slug); def read_settings(d); def engine(d)
- `archive/asgard-studio/src/asgard/commands/studio_dashboard/ops.py` — public surface: def run_list(json_out); def run_path()
- `archive/asgard-studio/src/asgard/commands/studio_dashboard/server.py` — public surface: def host_allowed(host_header); def origin_allowed(origin); def dispatch(method, path, params, d); def dispatch_post(path, payload, d); def run_dashboard(port, host, open_browser, focus)
- `archive/asgard-studio/tests/test_studio_dashboard.py` — public surface: class StudioBase; class TestDataAssembly; class TestArtifactBoundary; class TestDispatch; class TestTemplatesAndEngine
- `archive/freyja-before-rebuild-20260722/skill_plugins/21st-dev/skills/21st-cli-use/scripts/21st.py` — public surface: def main(argv)
- `archive/freyja-before-rebuild-20260722/skill_plugins/aceternity-ui/skills/aceternity-ui/scripts/aceternity.py` — public surface: def main(argv)
- `archive/freyja-before-rebuild-20260722/skill_plugins/google-design-md/skills/design-md-review/scripts/design_md.py` — public surface: class UniqueLoader; def lint(content); def main(argv)
- `archive/freyja-before-rebuild-20260722/skill_plugins/iart-web-animation-skills/skills/gsap-web/examples/hero-timeline.js` — public surface: playHeroIntro
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/brand/scripts/tests/test_sync_brand_to_tokens.py` — public surface: def test_sync_parses_bundled_starter_template(tmp_path)
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design-system/scripts/fetch-background.py` — public surface: def resolve_token_reference(ref, tokens); def load_brand_colors(); def load_backgrounds_config(); def get_overlay_css(style, brand_colors); def get_curated_images(slide_type)
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design-system/scripts/generate-slide.py` — public surface: def generate_title_slide(data); def generate_problem_slide(data); def generate_solution_slide(data); def generate_metrics_slide(data); def generate_chart_slide(data)
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design-system/scripts/html-token-validator.py` — public surface: class ValidationResult; def load_css_variables(); def is_inside_block(content, match_pos, open_tag, close_tag); def is_allowed_exception(context); def is_allowed_rgba(match_text)
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design-system/scripts/search-slides.py` — public surface: def format_result(result, domain); def format_context(context); def main()
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design-system/scripts/slide-token-validator.py` — public surface: def main()
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design-system/scripts/slide_search_core.py` — public surface: class BM25; def detect_domain(query); def search(query, domain, max_results); def search_all(query, max_results); def get_layout_for_goal(goal, previous_emotion)
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design-system/scripts/tests/test_validate_tokens.py` — public surface: def test_flags_hardcoded_hex_sharing_line_with_token(tmp_path); def test_token_only_line_reports_no_violation(tmp_path)
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design/scripts/cip/core.py` — public surface: class BM25; def detect_domain(query); def search(query, domain, max_results); def search_all(query, max_results); def get_cip_brief(brand_name, industry_query, style_query)
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design/scripts/cip/generate.py` — public surface: def load_logo_image(logo_path); def load_env(); def build_cip_prompt(deliverable, brand_name, style, industry, mockup, …); def generate_with_nano_banana(prompt_data, output_dir, model_key, aspect_ratio, logo_image); def generate_cip_set(brand_name, industry, style, deliverables, output_dir, …)
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design/scripts/cip/render-html.py` — public surface: def get_image_base64(image_path); def get_deliverable_info(filename); def generate_html(brand_name, industry, images_dir, output_path, style); def main()
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design/scripts/cip/search.py` — public surface: def format_results(results, domain); def format_brief(brief); def main()
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design/scripts/icon/generate.py` — public surface: def load_env(); def extract_svgs(text); def apply_color(svg_code, color); def apply_viewbox_size(svg_code, size); def generate_icon(prompt, style, category, name, color, …)
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design/scripts/logo/core.py` — public surface: class BM25; def detect_domain(query); def search(query, domain, max_results); def search_all(query, max_results)
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design/scripts/logo/generate.py` — public surface: def load_env(); def enhance_prompt(base_prompt, style, industry, brand_name); def generate_logo(prompt, style, industry, brand_name, output_path, …); def generate_batch(prompt, brand_name, count, output_dir, use_pro, …); def main()
- `archive/freyja-before-rebuild-20260722/skill_plugins/ui-ux-pro-max/skills/design/scripts/logo/search.py` — public surface: def format_output(result); def generate_design_brief(query, brand_name)

## Navigation contract

- Read `PROJECT.md` first, then the matching human-authored area map if present.
- Verify target definitions and usages from source before planning or editing.
- Structural changes refresh this managed map before Verifier hashing; use `asgard map check` in CI.
