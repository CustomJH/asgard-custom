# Single source of truth for the version. Hardcoded (not importlib.metadata) so a frozen/standalone
# build still reports a real semver instead of 0.0.0. pyproject reads this via [tool.hatch.version].
__version__ = "0.1.35"
