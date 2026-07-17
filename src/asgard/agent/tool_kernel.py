"""Canonical Asgard tool registry, capability policy, and execution contract.

The kernel is deliberately transport-neutral.  Anthropic/OpenAI/Claude Code are
adapters over the same session-scoped registry; registration never implies that
a tool is visible or callable for every role.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from typing import Callable, Mapping

from ..hooks.readonly_guard import is_readonly_bash_safe
from . import tools as T

ToolHandler = Callable[["ToolContext", dict], "ToolResult | str"]
CapabilityResolver = Callable[[dict], str]
AvailabilityCheck = Callable[["ToolContext"], bool]
EnabledCheck = bool | Callable[["ToolContext"], bool]


ROLE_CAPABILITIES: Mapping[str, frozenset[str]] = {
    # Public AgentSession callers that do not opt into a role retain the legacy
    # injected-tool behavior. Heimdall always supplies an explicit role.
    "legacy": frozenset({"inspect", "mutate", "execute", "coordinate", "verify"}),
    "direct": frozenset({"inspect", "execute"}),
    "readonly": frozenset({"inspect", "execute"}),
    "thinker": frozenset({"inspect", "execute"}),
    "thinker_alt": frozenset({"inspect", "execute"}),
    "worker": frozenset({"inspect", "mutate", "execute", "coordinate"}),
    "verifier": frozenset({"inspect", "execute", "verify"}),
    "freyja": frozenset({"inspect", "mutate", "execute"}),
    # 시각 편대장 — coordinate 를 가진 유일한 딜리버리 (서브 프레이야 편성, 깊이 1)
    "freyja-lead": frozenset({"inspect", "mutate", "execute", "coordinate"}),
    "thor": frozenset({"inspect", "mutate", "execute"}),
    # 백엔드 편대장 — freyja-lead 와 같은 유일 예외 계층 (서브 토르 편성, 깊이 1)
    "thor-lead": frozenset({"inspect", "mutate", "execute", "coordinate"}),
    "eitri": frozenset({"inspect", "mutate", "execute"}),
    "loki": frozenset({"inspect", "execute"}),
    "ullr": frozenset({"inspect", "execute"}),
    "mimir": frozenset({"inspect", "execute"}),
}

# Claude Code's Agent tool is intentionally role-specific: Thinker may delegate
# reconnaissance, Worker delivery work, and Verifier adversarial search only.
_CC_ROLE_TOOLS: Mapping[str, tuple[str, ...]] = {
    "thinker": ("Read", "Grep", "Glob", "Bash", "Agent"),
    "worker": ("Read", "Grep", "Glob", "Bash", "Write", "Edit", "NotebookEdit", "Agent"),
    "verifier": ("Read", "Grep", "Glob", "Bash", "Agent"),
    "freyja": ("Read", "Grep", "Glob", "Bash", "Write", "Edit", "NotebookEdit"),
    "freyja-lead": ("Read", "Grep", "Glob", "Bash", "Write", "Edit", "NotebookEdit", "Agent"),
    "thor": ("Read", "Grep", "Glob", "Bash", "Write", "Edit", "NotebookEdit"),
    "thor-lead": ("Read", "Grep", "Glob", "Bash", "Write", "Edit", "NotebookEdit", "Agent"),
    "eitri": ("Read", "Grep", "Glob", "Bash", "Write", "Edit", "NotebookEdit"),
    "loki": ("Read", "Grep", "Glob", "Bash"),
    "ullr": ("Read", "Grep", "Glob", "Bash"),
    "mimir": ("Read", "Grep", "Glob", "Bash"),
}


def cc_tools_for_role(role: str) -> tuple[str, ...]:
    """Return the frozen least-privilege Claude Code surface for a role."""
    try:
        return _CC_ROLE_TOOLS[role]
    except KeyError as exc:
        raise ValueError(f"unknown Asgard role: {role}") from exc


@dataclass
class ToolResult:
    content: str
    status: str = "ok"
    details: dict = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return self.status != "ok"


@dataclass
class ToolContext:
    root: str
    role: str = "worker"
    readonly: bool = False
    writes: list[str] = field(default_factory=list)
    commands: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)

    @property
    def capabilities(self) -> frozenset[str]:
        capabilities = ROLE_CAPABILITIES.get(self.role, frozenset())
        return capabilities - {"mutate"} if self.readonly else capabilities


@dataclass(frozen=True)
class ToolState:
    registered: bool
    available: bool
    enabled: bool
    visible: bool
    callable: bool


@dataclass(frozen=True)
class ToolSpec:
    name: str
    capability: str | CapabilityResolver
    schema: dict
    handler: ToolHandler
    available: AvailabilityCheck = lambda _ctx: True
    enabled: EnabledCheck = True
    source: str = "builtin"
    visible_capabilities: frozenset[str] | None = None
    validation_schema: dict | None = None

    def required_capability(self, args: dict) -> str:
        if isinstance(self.capability, str):
            return self.capability
        return self.capability(args)

    def visible_to(self, context: ToolContext) -> bool:
        if isinstance(self.capability, str):
            return self.capability in context.capabilities
        possible = self.visible_capabilities or frozenset({self.capability({})})
        return bool(possible & context.capabilities)


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool already registered: {spec.name}")
        if spec.schema.get("name") != spec.name:
            raise ValueError(f"tool schema name mismatch: {spec.name}")
        self._specs[spec.name] = replace(
            spec,
            schema=copy.deepcopy(spec.schema),
            validation_schema=copy.deepcopy(spec.validation_schema),
        )

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def available_specs(self, context: ToolContext) -> list[ToolSpec]:
        return [spec for _, spec in sorted(self._specs.items()) if self.state(spec.name, context).callable]

    def state(self, name: str, context: ToolContext) -> ToolState:
        spec = self.get(name)
        if spec is None:
            return ToolState(False, False, False, False, False)
        available = _is_available(spec, context)
        enabled = _is_enabled(spec, context)
        try:
            visible = spec.visible_to(context)
        except Exception:
            visible = False
        return ToolState(True, available, enabled, visible, available and enabled and visible)

    def schemas(self, context: ToolContext) -> list[dict]:
        return [copy.deepcopy(spec.schema) for spec in self.available_specs(context)]


def _is_available(spec: ToolSpec, context: ToolContext) -> bool:
    try:
        return bool(spec.available(context))
    except Exception:
        return False


def _is_enabled(spec: ToolSpec, context: ToolContext) -> bool:
    try:
        return bool(spec.enabled(context) if callable(spec.enabled) else spec.enabled)
    except Exception:
        return False


def _validate_input(schema: dict, value, path: str = "input") -> str | None:
    """Validate the JSON-Schema subset used by Asgard tools.

    Providers validate model calls too, but the executor is the security boundary:
    MCP and programmatic callers must receive the same fail-closed contract.
    """
    kind = schema.get("type")
    valid = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }
    if kind in valid and not valid[kind](value):
        return f"{path} must be {kind}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} must be one of {schema['enum']}"
    if kind == "object" and isinstance(value, dict):
        for required in schema.get("required", []):
            if required not in value:
                return f"{path}.{required} is required"
        for key, item in value.items():
            child = (schema.get("properties") or {}).get(key)
            if child:
                error = _validate_input(child, item, f"{path}.{key}")
                if error:
                    return error
    if kind == "array" and isinstance(value, list) and schema.get("items"):
        for index, item in enumerate(value):
            error = _validate_input(schema["items"], item, f"{path}[{index}]")
            if error:
                return error
    return None


def _editor_capability(args: dict) -> str:
    return "inspect" if args.get("command") == "view" else "mutate"


def _run_bash(context: ToolContext, args: dict) -> ToolResult:
    cmd = str(args.get("command") or "restart")
    if "mutate" not in context.capabilities and not is_readonly_bash_safe(cmd, context.root):
        return ToolResult(f"read-only role command escapes project policy: {cmd[:160]}", status="blocked")
    out, code = T.run_bash(context.root, args)
    context.commands.append({"cmd": cmd[:200], "exit_code": code})
    return ToolResult(out, details={"command": cmd, "exit_code": code})


def _run_editor(context: ToolContext, args: dict) -> ToolResult:
    out = T.run_editor(context.root, args, context.writes)
    return ToolResult(out, details={"path": str(args.get("path", "")), "command": args.get("command")})


def build_session_registry(
    extra_tools: list[dict] | None = None,
    handlers: Mapping[str, Callable[[dict], str]] | None = None,
) -> ToolRegistry:
    """Build a session-scoped registry while preserving the legacy injection API."""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "bash",
            lambda args: "execute" if is_readonly_bash_safe(str(args.get("command") or "")) else "mutate",
            T.BASH_TOOL,
            _run_bash,
            visible_capabilities=frozenset({"execute", "mutate"}),
            validation_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}, "restart": {"type": "boolean"}},
            },
        )
    )
    registry.register(
        ToolSpec(
            "str_replace_based_edit_tool",
            _editor_capability,
            T.EDITOR_TOOL,
            _run_editor,
            visible_capabilities=frozenset({"inspect", "mutate"}),
            validation_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "enum": ["view", "create", "str_replace", "insert"]},
                    "path": {"type": "string"},
                },
                "required": ["command", "path"],
            },
        )
    )
    handlers = handlers or {}
    for schema in extra_tools or []:
        name = schema["name"]
        handler = handlers.get(name)
        if handler is None:
            # Keep an invalid injection out of the model-visible surface instead
            # of advertising a tool that can only fail at dispatch time.
            continue
        schema_copy = copy.deepcopy(schema)
        declared = str(schema_copy.pop("x-asgard-capability", "") or "")
        capability = {"dispatch": "coordinate", "verdict": "verify"}.get(
            name,
            declared if declared in {"inspect", "mutate", "execute", "coordinate", "verify"} else "mutate",
        )

        def call(context: ToolContext, args: dict, *, _name=name, _handler=handler) -> ToolResult:
            context.tool_calls.append({"name": _name, "input": dict(args)})
            return ToolResult(str(_handler(dict(args))))

        registry.register(ToolSpec(name, capability, schema_copy, call, source="session"))
    return registry


def execute_tool(registry: ToolRegistry, name: str, args: dict, context: ToolContext) -> ToolResult:
    """Authorize, execute, and normalize one tool call without leaking exceptions."""
    spec = registry.get(name)
    if spec is None:
        return ToolResult(f"unknown tool {name}", status="not_found")
    state = registry.state(name, context)
    if not state.enabled:
        return ToolResult(f"tool disabled for this session: {name}", status="disabled")
    if not state.visible or not state.available:
        return ToolResult(f"tool unavailable for role {context.role}: {name}", status="blocked")
    try:
        required = spec.required_capability(args)
    except Exception as exc:
        return ToolResult(f"tool policy failed: {exc}", status="policy_error")
    if required not in context.capabilities:
        return ToolResult(
            f"role {context.role} lacks capability '{required}' for tool {name}",
            status="blocked",
        )
    input_schema = spec.validation_schema or spec.schema.get("input_schema")
    if input_schema:
        invalid = _validate_input(input_schema, args)
        if invalid:
            return ToolResult(f"invalid tool input: {invalid}", status="invalid_input")
    try:
        result = spec.handler(context, dict(args))
        return result if isinstance(result, ToolResult) else ToolResult(str(result))
    except T.ToolError as exc:
        return ToolResult(str(exc), status="error")
    except Exception as exc:
        return ToolResult(f"tool crashed: {exc}", status="error")


def to_openai_tool(schema: dict) -> dict:
    """Convert a canonical/Anthropic schema to OpenAI function format."""
    if schema.get("type", "").startswith("bash"):
        parameters = {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }
        description = "Run a bash command in the project root."
    elif schema.get("type", "").startswith("text_editor"):
        parameters = {
            "type": "object",
            "properties": {
                "command": {"type": "string", "enum": ["view", "create", "str_replace", "insert"]},
                "path": {"type": "string"},
                "file_text": {"type": "string"},
                "old_str": {"type": "string"},
                "new_str": {"type": "string"},
                "insert_line": {"type": "integer"},
                "insert_text": {"type": "string"},
                "view_range": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["command", "path"],
        }
        description = "View/create/edit files. command: view|create|str_replace|insert."
    else:
        parameters = schema["input_schema"]
        description = schema.get("description", "")
    return {
        "type": "function",
        "function": {
            "name": schema["name"],
            "description": description,
            "parameters": parameters,
        },
    }
