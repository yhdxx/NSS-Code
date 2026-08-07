from __future__ import annotations

import json

from pydantic import BaseModel, Field

from mycodingagent.skill_runtime.contracts import SkillService
from mycodingagent.tool_runtime.base import Tool, ToolResult
from mycodingagent.tool_contracts import apply_tool_intent_schema


class SearchSkillParams(BaseModel):
    query: str = Field(
        description=(
            "用于检索的中文能力、任务或描述。用户请求为英文或中英混合时，先翻译或概括为中文。"
            "重复检索时应逐步放宽 query。"
        )
    )
    max_results: int = Field(default=5, description="最多返回的匹配 SKILL 工作流数量")
    tool_names: list[str] = Field(default_factory=list, description="可选的优先工具准确名称或部分名称")


class SearchSkillTool(Tool):
    name = "search_tool"
    description = (
        "通过工具名称和描述进行关键词与语义混合检索，查找开发者提供的 SKILL。按能力查找 Skill 时，"
        "应使用本工具，不要使用 Bash、Glob 或 ReadFile。结果包含可供 invoke_skill 使用的 Skill 名称和元数据。"
        "当前 Prompt 中没有高匹配 Business Skill，但任务可能存在专家工作流时使用。query 必须为中文；"
        "重试时按具体任务、同义词或能力类别、上位领域逐步放宽。"
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
        "列出当前注册的全部 SKILL 工具及其名称和简短描述。用户询问有哪些 Skill、要求查看全部 Skill，"
        "或询问 Agent 的 Skill 能力时优先使用。解决任务时，仅当全局 Skill 能力摘要明确包含所需能力，"
        "并且最多三次逐步放宽的中文 search_tool 查询均失败时使用。摘要未明确覆盖所需能力时不要调用。"
        "禁止使用 Bash 或 Glob 检查 skills 目录或 SQLite 数据库来替代本工具。"
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
    tool_name: str = Field(description="Get_all_tool 返回的准确 SKILL 工具名称")


class GetToolByNameTool(Tool):
    name = "Get_tool_by_name"
    description = (
        "根据 Get_all_tool 或 search_tool 返回的准确名称获取 SKILL 工作流详情。识别出与任务匹配的 "
        "Business Skill 后使用；需要应用该工作流时，再以对应 skill_name 调用 invoke_skill。"
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
    query: str = Field(default="", description="要搜索的引用内容、文件名或主题；按 skill_name 列出引用时可留空")
    skill_name: str = Field(default="", description="可选的准确 SKILL 工具名称，例如 skill_infinitetalk；只提供 skill_name 可列出该 Skill 的引用")
    max_results: int = Field(default=5, description="最多返回的引用文件数量")


class SearchSkillReferencesTool(Tool):
    name = "search_skill_references"
    description = (
        "搜索 SKILL 的 references/ 目录中已建立索引的文件。Skill 提到引用文件但准确路径未知、"
        "需要补充引用材料，或需要仅通过 skill_name 列出该 Skill 的引用时使用。"
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
    skill_name: str = Field(description="准确的 SKILL 工具名称，例如 skill_infinitetalk")
    reference_path: str = Field(description="Skill 目录下的引用路径，例如 references/model_config.md；也接受 model_config.md 等短文件名并归一化到 references/ 下")


class GetSkillReferenceTool(Tool):
    name = "Get_skill_reference"
    description = (
        "返回 SKILL 的 references/ 目录下某个文件的完整内容。仅使用 Skill 调用或 "
        "search_skill_references 返回的 reference_path。"
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
    instruction: str = Field(description="如何将该 Business Skill 的专家工作流应用到当前任务")
    context: str = Field(default="", description="应用该 Skill 时可选的任务特定上下文")


class InvokeSkillParams(SkillInvocationParams):
    skill_name: str = Field(description="要调用的准确 SKILL 工具名称，例如 skill_frontend_design")


def execute_skill_workflow(runtime: SkillService, tool_name: str, instruction: str, context: str = "") -> ToolResult:
    record = runtime.get_record(tool_name)
    if record is None:
        return ToolResult(output=f"错误：未找到 Skill：{tool_name}", is_error=True)
    runtime.record_skill_invocation(tool_name)
    output = (
        f"SKILL：{record.name}\n"
        f"描述：\n{record.description}\n\n"
        f"指令：\n{record.content}\n\n"
        f"用户指令：\n{instruction}"
    )
    references = runtime.list_references_for_skill(tool_name)
    if references:
        reference_lines = "\n".join(f"- {item['reference_path']}" for item in references)
        first_reference = references[0]["reference_path"]
        example = json.dumps(
            {
                "skill_name": tool_name,
                "reference_path": first_reference,
            },
            ensure_ascii=False,
        )
        output += (
            "\n\n可用引用：\n"
            f"{reference_lines}\n\n"
            "需要引用内容时，使用当前 Skill 工具名称和其中一个 reference_path 调用 Get_skill_reference。\n"
            f"Get_skill_reference 参数示例：{example}"
        )
    if context:
        output += f"\n\n上下文：\n{context}"
    return ToolResult(output=output)


class InvokeSkillTool(Tool):
    name = "invoke_skill"
    description = (
        "根据准确的 skill_name 调用一个开发者提供的 Business Skill 工作流。当 Runtime Context 推荐、"
        "search_tool、Get_all_tool 或 Get_tool_by_name 识别出匹配的 SKILL 时使用。"
        "本固定工具用于替代每个 Skill 各自的动态函数 schema。"
    )
    params_model = InvokeSkillParams
    category = "read"
    is_concurrency_safe = True
    is_system_tool = True

    def __init__(self, runtime: SkillService) -> None:
        self._runtime = runtime

    async def execute(self, params: InvokeSkillParams) -> ToolResult:
        return execute_skill_workflow(
            self._runtime,
            params.skill_name,
            params.instruction,
            params.context,
        )


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
                f"Business Skill 专家工作流。用户任务匹配该 Skill 时，应在使用 Core Tool 或仅依赖模型知识前调用。"
                f"Skill 描述：{record.description}"
            )
        else:
            self.description = f"开发者提供的 Business Skill 专家工作流：{tool_name}"

    async def execute(self, params: SkillInvocationParams) -> ToolResult:
        return execute_skill_workflow(self._runtime, self._tool_name, params.instruction, params.context)


def skill_schema_from_record(record) -> dict:
    input_schema = SkillInvocationParams.model_json_schema()
    apply_tool_intent_schema(input_schema)
    return {
        "name": record.tool_name,
        "description": record.description,
        "input_schema": input_schema,
        "parameters": input_schema,
    }
