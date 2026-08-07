from __future__ import annotations


MAX_TOOL_INTENT_CHARS = 240
COLD_ARGUMENT_VIRTUALIZED = "<COLD_ARGUMENT_VIRTUALIZED>"

TOOL_INTENT_DESCRIPTION = (
    "本次工具调用的紧凑意图。首次调用说明通过什么工具或命令执行什么操作及其目的；"
    "后续调用先概括上一轮工具结果，再说明本次操作、方法和目的。"
)


def apply_tool_intent_schema(schema: dict) -> dict:
    properties = schema.setdefault("properties", {})
    if isinstance(properties, dict):
        intent_schema = properties.setdefault("intent", {})
        if isinstance(intent_schema, dict):
            intent_schema.update(
                {
                    "type": "string",
                    "description": TOOL_INTENT_DESCRIPTION,
                    "minLength": 1,
                    "maxLength": MAX_TOOL_INTENT_CHARS,
                }
            )
    required = schema.setdefault("required", [])
    if isinstance(required, list) and "intent" not in required:
        required.append("intent")
    return schema
