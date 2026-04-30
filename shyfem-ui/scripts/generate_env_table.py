"""Introspect Config and emit the env-var table in markdown.

Use as a regression guard: run this script and diff against README.md
to confirm the table is up to date.

Usage:
    /opt/micromamba/envs/shiny/bin/python shyfem-ui/scripts/generate_env_table.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic_core import PydanticUndefinedType

from shyfem_ui.config import Config


def _format_default(field) -> str:
    """Return a human-readable default string for a FieldInfo."""
    if field.default_factory is not None:
        # Evaluate the factory to get the runtime default
        try:
            value = field.default_factory()
            if isinstance(value, Path):
                return str(value)
            if isinstance(value, list) and len(value) == 0:
                return "[]"
            return repr(value)
        except Exception:
            return "(factory)"
    default = field.default
    if isinstance(default, PydanticUndefinedType):
        return "(required)"
    if default is None:
        return "auto"
    if isinstance(default, bool):
        return str(default).lower()
    if default == "":
        return "(unset)"
    return str(default)


def main() -> None:
    print("| Env var | Default | Description |")
    print("| --- | --- | --- |")
    for name, field in Config.model_fields.items():
        env_name = f"SHYFEM_UI_{name.upper()}"
        default = _format_default(field)
        desc = field.description or ""
        print(f"| `{env_name}` | `{default}` | {desc} |")


if __name__ == "__main__":
    main()
