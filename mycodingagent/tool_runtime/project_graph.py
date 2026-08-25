from __future__ import annotations

import json

from pydantic import BaseModel, Field

from mycodingagent.code_intelligence.dynamic_dependency import DynamicDependencyRuntime
from mycodingagent.tool_runtime.base import Tool, ToolResult


class UnitDescriptionParams(BaseModel):
    unit_name: str = Field(description="规范单位名称，例如 src/service.py::Service.run")
    description: str = Field(description="单位功能描述；传入空字符串会删除描述")


class UnitDependencyParams(BaseModel):
    unit_name: str = Field(description="规范单位名称，例如 src/service.py::Service.run")


class UpdateUnitDescriptionTool(Tool):
    name = "UpdateUnitDescription"
    description = "提交一个最小代码单位的功能 description；空字符串删除描述，成功返回修改成功。"
    category = "state"
    params_model = UnitDescriptionParams

    def __init__(self, runtime: DynamicDependencyRuntime) -> None:
        self._runtime = runtime

    async def execute(self, params: UnitDescriptionParams) -> ToolResult:
        payload = self._runtime.update_description(params.unit_name, params.description)
        if "error_code" in payload:
            return ToolResult(json.dumps(payload, ensure_ascii=False), is_error=True)
        return ToolResult("修改成功")


class QueryUnitDependencyTool(Tool):
    name = "QueryUnitDependency"
    description = "查询哪些代码单位调用了当前单位，返回调用方单位名称、文件路径及非空 description，帮助定位代码修改可能影响的范围。"
    category = "read"
    is_concurrency_safe = True
    params_model = UnitDependencyParams

    def __init__(self, runtime: DynamicDependencyRuntime) -> None:
        self._runtime = runtime

    async def execute(self, params: UnitDependencyParams) -> ToolResult:
        payload = self._runtime.query(params.unit_name)
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error="error_code" in payload)
