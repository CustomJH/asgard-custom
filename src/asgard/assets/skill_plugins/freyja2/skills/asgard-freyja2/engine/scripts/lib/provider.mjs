// Source scripts default to slash commands. The provider build replaces only
// this exact declaration, avoiding heuristic rewrites across executable code.
export const FREYJA2_COMMAND_PREFIX = "/";
export const FREYJA2_PROVIDER_ID = "claude-code";
export const FREYJA2_COMMAND = `${FREYJA2_COMMAND_PREFIX}freyja2`;
