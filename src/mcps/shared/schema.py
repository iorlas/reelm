from typing import Any

from fastmcp import FastMCP
from fastmcp.tools import Tool


def strip_nullable_anyof(schema: Any) -> Any:
    """Replace {"anyOf": [T, {"type":"null"}]} with just T, recursively."""
    if isinstance(schema, dict):
        if "anyOf" in schema:
            branches = schema["anyOf"]
            non_null = [b for b in branches if b != {"type": "null"}]
            if len(non_null) == 1 and len(branches) == 2:
                result = {k: v for k, v in schema.items() if k != "anyOf"}
                result.update(non_null[0])
                return strip_nullable_anyof(result)

        return {k: strip_nullable_anyof(v) for k, v in schema.items()}

    if isinstance(schema, list):
        return [strip_nullable_anyof(item) for item in schema]

    return schema


def optimize_tool_schemas(mcp: FastMCP) -> None:
    """Post-process all tool schemas on a FastMCP instance to reduce token usage."""
    provider = mcp.providers[0]
    for component in provider._components.values():  # noqa: SLF001  # type: ignore[unresolved-attribute]
        if isinstance(component, Tool):
            component.parameters = strip_nullable_anyof(component.parameters)
