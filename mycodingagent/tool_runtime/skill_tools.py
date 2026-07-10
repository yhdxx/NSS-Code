from __future__ import annotations

import json

from pydantic import BaseModel, Field

from mycodingagent.skill_runtime.contracts import SkillService
from mycodingagent.tool_runtime.base import Tool, ToolResult


class SearchSkillParams(BaseModel):
    query: str = Field(
        description=(
            "Chinese capability, task, or description to search for. If the user request is English or mixed, "
            "translate/summarize it into Chinese before searching. Repeated searches should broaden the query."
        )
    )
    max_results: int = Field(default=5, description="Maximum number of skill tool schemas to return")
    tool_names: list[str] = Field(default_factory=list, description="Optional exact or partial tool names to prefer")


class SearchSkillTool(Tool):
    name = "search_tool"
    description = (
        "Search developer-provided SKILL tools by tool name or description using hybrid retrieval "
        "(keyword + semantic over SKILL descriptions). Use this instead of Bash/Glob/ReadFile when looking "
        "for a skill by capability. Returns matching tool schemas that may be useful for the current task. "
        "Use this when no highly matching Business Skill is already available in the current prompt, but the "
        "task may have a developer-provided expert workflow. Query must be Chinese; if retrying, broaden from "
        "specific task to synonyms/capability category to upper-level domain."
    )
    params_model = SearchSkillParams
    category = "read"
    is_concurrency_safe = True
    is_system_tool = True

    def __init__(self, runtime: SkillService) -> None:
        self._runtime = runtime

    async def execute(self, params: SearchSkillParams) -> ToolResult:
        result = await self._runtime.search_skill_schemas(
            query=params.query,
            max_results=params.max_results,
            tool_names=params.tool_names,
        )
        return ToolResult(output=json.dumps(result, ensure_ascii=False, indent=2))


class GetAllToolParams(BaseModel):
    pass


class GetAllTool(Tool):
    name = "Get_all_tool"
    description = (
        "List all currently registered SKILL tools with names and short descriptions. Use this first when "
        "the user asks what skills are available, asks to view all skills, or asks about the agent's skill "
        "capabilities. For task-solving, use this only when the global Skill capability summary clearly says "
        "the needed capability exists and up to three broadened Chinese search_tool queries failed. If the "
        "summary does not clearly cover the needed capability, do not call this tool. Do not inspect the "
        "skills directory or SQLite database with Bash/Glob for this."
    )
    params_model = GetAllToolParams
    category = "read"
    is_concurrency_safe = True
    is_system_tool = True

    def __init__(self, runtime: SkillService) -> None:
        self._runtime = runtime

    async def execute(self, params: GetAllToolParams) -> ToolResult:
        result = await self._runtime.list_skill_tools()
        return ToolResult(output=json.dumps(result, ensure_ascii=False, indent=2))


class GetToolByNameParams(BaseModel):
    tool_name: str = Field(description="Exact SKILL tool name returned by Get_all_tool")


class GetToolByNameTool(Tool):
    name = "Get_tool_by_name"
    description = (
        "Return the full schema for a SKILL tool by exact name from Get_all_tool, and make it available "
        "in the next model round. Use this after Get_all_tool/search_tool identifies a Business Skill that "
        "matches the task but is not currently callable."
    )
    params_model = GetToolByNameParams
    category = "read"
    is_concurrency_safe = True
    is_system_tool = True

    def __init__(self, runtime: SkillService) -> None:
        self._runtime = runtime

    async def execute(self, params: GetToolByNameParams) -> ToolResult:
        result = await self._runtime.get_tool_schema_by_name(params.tool_name)
        return ToolResult(output=json.dumps(result, ensure_ascii=False, indent=2), is_error=bool(result.get("error")))


class SearchSkillReferencesParams(BaseModel):
    query: str = Field(default="", description="Reference content, filename, or topic to search for. Optional when skill_name is provided to list that skill's references.")
    skill_name: str = Field(default="", description="Optional exact SKILL tool name, e.g. skill_infinitetalk. Provide only skill_name and no query to list references for that skill.")
    max_results: int = Field(default=5, description="Maximum number of reference files to return")


class SearchSkillReferencesTool(Tool):
    name = "search_skill_references"
    description = (
        "Search indexed files under a SKILL's references/ directory. Use this when a skill mentions "
        "a reference file but the exact path is unknown, when additional skill reference material is needed, "
        "or with only skill_name to list references for that skill."
    )
    params_model = SearchSkillReferencesParams
    category = "read"
    is_concurrency_safe = True
    is_system_tool = True

    def __init__(self, runtime: SkillService) -> None:
        self._runtime = runtime

    async def execute(self, params: SearchSkillReferencesParams) -> ToolResult:
        result = await self._runtime.search_skill_references(
            query=params.query,
            skill_name=params.skill_name,
            max_results=params.max_results,
        )
        return ToolResult(output=json.dumps(result, ensure_ascii=False, indent=2))


class GetSkillReferenceParams(BaseModel):
    skill_name: str = Field(description="Exact SKILL tool name, e.g. skill_infinitetalk")
    reference_path: str = Field(description="Reference path under the skill directory, e.g. references/model_config.md. Short filenames such as model_config.md are accepted and normalized under references/.")


class GetSkillReferenceTool(Tool):
    name = "Get_skill_reference"
    description = (
        "Return the full content of a file under a SKILL's references/ directory. Use only with a "
        "reference_path returned by a skill invocation or search_skill_references."
    )
    params_model = GetSkillReferenceParams
    category = "read"
    is_concurrency_safe = True
    is_system_tool = True

    def __init__(self, runtime: SkillService) -> None:
        self._runtime = runtime

    async def execute(self, params: GetSkillReferenceParams) -> ToolResult:
        result = await self._runtime.get_skill_reference(
            skill_name=params.skill_name,
            reference_path=params.reference_path,
        )
        return ToolResult(output=json.dumps(result, ensure_ascii=False, indent=2), is_error=bool(result.get("error")))


class SkillInvocationParams(BaseModel):
    instruction: str = Field(description="How to apply this Business Skill's expert workflow for the current task")
    context: str = Field(default="", description="Optional task-specific context for applying the skill")


class SkillTool(Tool):
    category = "read"
    is_concurrency_safe = True

    def __init__(self, runtime: SkillService, tool_name: str) -> None:
        self._runtime = runtime
        self._tool_name = tool_name
        self.name = tool_name
        self.params_model = SkillInvocationParams
        record = self._runtime.get_record(tool_name)
        if record:
            self.description = (
                f"Business Skill expert workflow. If the user's task matches this skill, call it before "
                f"using Core Tools or relying on model-only knowledge. Skill description: {record.description}"
            )
        else:
            self.description = f"Developer-provided Business Skill expert workflow: {tool_name}"

    async def execute(self, params: SkillInvocationParams) -> ToolResult:
        record = self._runtime.get_record(self._tool_name)
        if record is None:
            return ToolResult(output=f"Error: skill not found: {self._tool_name}", is_error=True)
        self._runtime.record_skill_invocation(self._tool_name)
        output = (
            f"SKILL: {record.name}\n"
            f"DESCRIPTION:\n{record.description}\n\n"
            f"INSTRUCTIONS:\n{record.content}\n\n"
            f"USER INSTRUCTION:\n{params.instruction}"
        )
        references = self._runtime.list_references_for_skill(self._tool_name)
        if references:
            reference_lines = "\n".join(f"- {item['reference_path']}" for item in references)
            first_reference = references[0]["reference_path"]
            example = json.dumps(
                {
                    "skill_name": self._tool_name,
                    "reference_path": first_reference,
                },
                ensure_ascii=False,
            )
            output += (
                "\n\nAVAILABLE REFERENCES:\n"
                f"{reference_lines}\n\n"
                "Use Get_skill_reference with this skill tool name and one of the reference_path values "
                "when the reference content is needed.\n"
                f"Example Get_skill_reference arguments: {example}"
            )
        if params.context:
            output += f"\n\nCONTEXT:\n{params.context}"
        return ToolResult(output=output)


def skill_schema_from_record(record) -> dict:
    input_schema = SkillInvocationParams.model_json_schema()
    return {
        "name": record.tool_name,
        "description": record.description,
        "input_schema": input_schema,
        "parameters": input_schema,
    }
