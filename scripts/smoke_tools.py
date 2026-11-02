"""Smoke test: does a model make a tool call through the Meta Model API?

Usage: python scripts/smoke_tools.py [model]    (default: muse-wonder-1.0)
"""

import json
import sys

from telltale.config import client

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_fact",
            "description": "Return one evidence fact by id.",
            "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        },
    }
]


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "muse-wonder-1.0"
    response = client().chat.completions.create(
        model=model,
        tools=TOOLS,
        messages=[{"role": "user", "content": "Call get_fact with id VID:lane_entry_t."}],
    )
    calls = response.choices[0].message.tool_calls or []
    print(model, "tool calls:", json.dumps([c.model_dump() for c in calls], indent=2))
    if not calls:
        sys.exit(f"FAIL: {model} made no tool call")


if __name__ == "__main__":
    main()
