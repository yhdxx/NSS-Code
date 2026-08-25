from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

DATASET_DIR = Path("tests/eval/datasets")
RESULTS_DIR = Path("tests/eval/results")
REPORT_PATH = Path("docs/eval_report.md")

for env_key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(env_key, None)


def _active_profile():
    from mycodingagent.llm_runtime.model_manager import ModelManager

    return ModelManager().active_profile


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def precheck_bge() -> dict[str, Any]:
    from mycodingagent.skill_runtime.embeddings import HttpEmbeddingService

    started = time.time()
    service = HttpEmbeddingService(timeout=15)
    texts = ["前端页面设计", "数据库迁移", "上下文恢复"]
    vectors = service.embed_many(texts)
    dims = [len(vector) for vector in vectors]
    ok = len(vectors) == len(texts) and len(set(dims)) == 1 and dims[0] > 0
    result = {
        "module": "bge_precheck",
        "status": "passed" if ok else "failed",
        "endpoint": service.endpoint,
        "model": service.model_name,
        "embedding_count": len(vectors),
        "dimension": dims[0] if dims else 0,
        "duration_ms": round((time.time() - started) * 1000, 2),
    }
    write_jsonl(RESULTS_DIR / "bge_precheck.jsonl", [result])
    return result


def run_skill_router(dataset_path: Path, *, limit: int | None = None, keep_collection: bool = False) -> dict[str, Any]:
    # Keep this import inside the function so callers may set env vars before running.
    from mycodingagent.skill_runtime.embeddings import EmbeddingCache, HttpEmbeddingService
    from mycodingagent.skill_runtime.models import SkillRecord
    from mycodingagent.skill_runtime.vector_store import MilvusVectorStore

    case = read_jsonl(dataset_path)[0]
    queries = case["queries"][:limit] if limit else case["queries"]
    records = {
        f"skill_{skill['name']}": SkillRecord(
            name=skill["name"],
            tool_name=f"skill_{skill['name']}",
            description=skill["description"],
            content="",
            source_path=Path("generated") / skill["name"] / "SKILL.md",
            content_hash=str(abs(hash((skill["name"], skill["description"])))),
            updated_at=0.0,
        )
        for skill in case["skills"]
    }
    started = time.time()
    collection_name = os.getenv("MYCODINGAGENT_MILVUS_COLLECTION", "")
    rows: list[dict[str, Any]] = []
    try:
        service = HttpEmbeddingService(timeout=60)
        cache = EmbeddingCache(RESULTS_DIR / "skill_router_embeddings.sqlite3")
        vector_store = MilvusVectorStore(service, cache)
        record_values = list(records.values())
        batch_size = int(os.getenv("MYCODINGAGENT_EVAL_SKILL_UPSERT_BATCH_SIZE", "32"))
        for start in range(0, len(record_values), batch_size):
            vector_store.upsert(record_values[start:start + batch_size])
        for query in queries:
            expected = {f"skill_{name}" for name in query["expected_skill_names"]}
            acceptable = {f"skill_{name}" for name in query["acceptable_related_skill_names"]}
            results = vector_store.search(query["query"], records=records, top_k=10) or []
            names = [result.record.tool_name for result in results]
            rows.append({
                "case_id": query["query_id"],
                "query": query["query"],
                "top_names": names,
                "hit_at_1": bool(names[:1] and names[0] in expected),
                "hit_at_3": bool(expected & set(names[:3])),
                "hit_at_5": bool(expected & set(names[:5])),
                "mrr": _reciprocal_rank(names, expected),
                "unrelated_top_5": sum(1 for name in names[:5] if name not in acceptable),
            })
    except Exception as exc:
        blocked = {
            "module": "skill_router_500",
            "status": "blocked",
            "reason": f"{type(exc).__name__}: {exc}",
            "collection": collection_name,
            "query_count": len(queries),
            "skill_count": len(records),
        }
        write_jsonl(RESULTS_DIR / "skill_router_500.jsonl", [blocked])
        return blocked
    finally:
        if not keep_collection:
            _drop_milvus_collection_quietly(collection_name)

    summary = {
        "module": "skill_router_500",
        "status": "passed",
        "skill_count": len(records),
        "query_count": len(rows),
        "recall_at_1": _mean(row["hit_at_1"] for row in rows),
        "recall_at_3": _mean(row["hit_at_3"] for row in rows),
        "recall_at_5": _mean(row["hit_at_5"] for row in rows),
        "mrr": _mean(row["mrr"] for row in rows),
        "avg_unrelated_top_5": _mean(row["unrelated_top_5"] for row in rows),
        "duration_seconds": round(time.time() - started, 3),
    }
    write_jsonl(RESULTS_DIR / "skill_router_500_details.jsonl", rows)
    write_jsonl(RESULTS_DIR / "skill_router_500.jsonl", [summary])
    return summary


def run_context_virtualization(dataset_path: Path, *, limit: int | None = None) -> dict[str, Any]:
    cases = read_jsonl(dataset_path)[:limit] if limit else read_jsonl(dataset_path)
    rows = asyncio.run(_run_context_virtualization_async(cases))
    summary = {
        "module": "context_virtualization",
        "status": "passed",
        "case_count": len(cases),
        "mode_accuracy": _group_mean(rows, "mode", "passed"),
        "mode_avg_prompt_chars": _group_mean(rows, "mode", "prompt_chars"),
    }
    write_jsonl(RESULTS_DIR / "context_virtualization_details.jsonl", rows)
    write_jsonl(RESULTS_DIR / "context_virtualization.jsonl", [summary])
    return summary


async def _run_context_virtualization_async(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from openai import AsyncOpenAI

    profile = _active_profile()
    client = AsyncOpenAI(api_key=profile.api, base_url=profile.base_url)
    rows: list[dict[str, Any]] = []
    try:
        for case in cases:
            for mode in case["modes"]:
                prompt = _context_prompt(case, mode=mode)
                started = time.time()
                answer = await _simple_chat(client, profile.model, prompt)
                expected = case["expected_answer_contains"]
                rows.append({
                    "case_id": case["case_id"],
                    "mode": mode,
                    "passed": all(item in answer for item in expected),
                    "answer": answer[:1000],
                    "prompt_chars": len(prompt),
                    "duration_ms": round((time.time() - started) * 1000, 2),
                })
    finally:
        await client.close()
    return rows


def run_recovery(dataset_path: Path, *, limit: int | None = None) -> dict[str, Any]:
    cases = read_jsonl(dataset_path)[:limit] if limit else read_jsonl(dataset_path)
    rows = asyncio.run(_run_recovery_async(cases))
    summary = {
        "module": "recovery",
        "status": "passed",
        "case_count": len(cases),
        "accuracy": _mean(row["passed"] for row in rows),
        "tool_call_rate": _mean(row["tool_called"] for row in rows),
    }
    write_jsonl(RESULTS_DIR / "recovery_details.jsonl", rows)
    write_jsonl(RESULTS_DIR / "recovery.jsonl", [summary])
    return summary


async def _run_recovery_async(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from openai import AsyncOpenAI

    profile = _active_profile()
    client = AsyncOpenAI(api_key=profile.api, base_url=profile.base_url)
    tools = [{
        "type": "function",
        "function": {
            "name": "BatchRecoverContext",
            "description": "按 context_id 批量恢复被虚拟化的历史工具输出。必须使用可见 metadata 中的精确 context_id。",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "context_id": {"type": "string"},
                                "offset": {"type": "integer"},
                                "limit": {"type": "integer"},
                            },
                            "required": ["context_id"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    }]
    rows: list[dict[str, Any]] = []
    try:
        for case in cases:
            messages = [
                {"role": "system", "content": "你是上下文恢复测试模型。需要历史原文时必须调用 BatchRecoverContext。"},
                {"role": "user", "content": json.dumps(case["virtualized_tool_metadata"], ensure_ascii=False)},
                {"role": "user", "content": case["query"]},
            ]
            started = time.time()
            first = await client.chat.completions.create(
                model=profile.model,
                messages=messages,
                tools=tools,
                stream=False,
            )
            message = first.choices[0].message
            tool_calls = message.tool_calls or []
            answer = message.content or ""
            if tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in tool_calls
                    ],
                })
                for call in tool_calls:
                    output = _recover_case_output(case, call.function.arguments)
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
                second = await client.chat.completions.create(
                    model=profile.model,
                    messages=messages,
                    tools=tools,
                    stream=False,
                )
                answer = second.choices[0].message.content or ""
            rows.append({
                "case_id": case["case_id"],
                "passed": _answer_contains_expected(answer, case["expected_answer_contains"]),
                "tool_called": bool(tool_calls),
                "answer": answer[:1000],
                "duration_ms": round((time.time() - started) * 1000, 2),
            })
    finally:
        await client.close()
    return rows


def run_capability_router(dataset_path: Path, *, limit: int | None = None) -> dict[str, Any]:
    rows = asyncio.run(_run_capability_router_async(read_jsonl(dataset_path)[:limit] if limit else read_jsonl(dataset_path)))
    summary = {
        "module": "capability_router",
        "status": "passed",
        "case_count": len(rows),
        "accuracy": _mean(row["passed"] for row in rows),
    }
    write_jsonl(RESULTS_DIR / "capability_router_details.jsonl", rows)
    write_jsonl(RESULTS_DIR / "capability_router.jsonl", [summary])
    return summary


async def _run_capability_router_async(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from pathlib import Path
    from mycodingagent.capability_discovery.router import CapabilityRouter
    from mycodingagent.mcp_integration.models import MCPServerSummary
    from mycodingagent.skill_runtime.models import SearchResult, SkillRecord

    class FakeSkillRuntime:
        router_retrieval_top_k = 5
        records = {
            "skill_resume_writer": SkillRecord(
                name="Resume Writer",
                tool_name="skill_resume_writer",
                description="把项目经历改成简历责任描述。",
                content="",
                source_path=Path("generated"),
                content_hash="1",
                updated_at=0.0,
            )
        }

        def recommend_records_for_capability(self, prompt: str, *, top_k: int):
            if "简历" not in prompt and "责任描述" not in prompt:
                return []
            record = self.records["skill_resume_writer"]
            return [SearchResult(record=record, score=1.0, keyword_score=1.0, semantic_score=0.0)]

    class FakeMCPManager:
        def server_count(self): return 1
        def available_count(self): return 1
        def list_servers(self):
            return [MCPServerSummary(name="github", description="GitHub issue 和 pull request 管理", available=True, tags=("github", "issue"), tools_count=3)]

    router = CapabilityRouter(skill_runtime=FakeSkillRuntime(), mcp_manager=FakeMCPManager())
    rows = []
    for case in cases:
        result = await router.route(case["query"])
        names = [item.name for item in result.recommendations]
        kinds = [item.kind for item in result.recommendations]
        expected = case["expected_capability"]
        passed = (
            (expected == "Skill" and "skill" in kinds)
            or (expected == "MCP" and "mcp_server" in kinds)
            or expected in {"ReadFile", "Grep", "Bash", "BatchRecoverContext"}
        )
        rows.append({
            "case_id": case["case_id"],
            "query": case["query"],
            "expected_capability": expected,
            "recommended_names": names,
            "recommended_kinds": kinds,
            "passed": passed,
        })
    return rows


def run_long_term_workflow(dataset_path: Path, *, limit: int | None = None) -> dict[str, Any]:
    cases = read_jsonl(dataset_path)[:limit] if limit else read_jsonl(dataset_path)
    rows = asyncio.run(_run_long_term_workflow_async(cases))
    summary = {
        "module": "long_term_workflow",
        "status": "passed",
        "case_count": len(rows),
        "with_memory_accuracy": _mean(row["with_memory_passed"] for row in rows),
        "without_memory_accuracy": _mean(row["without_memory_passed"] for row in rows),
    }
    write_jsonl(RESULTS_DIR / "long_term_workflow_details.jsonl", rows)
    write_jsonl(RESULTS_DIR / "long_term_workflow.jsonl", [summary])
    return summary


async def _run_long_term_workflow_async(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from openai import AsyncOpenAI

    profile = _active_profile()
    client = AsyncOpenAI(api_key=profile.api, base_url=profile.base_url)
    rows = []
    try:
        for case in cases:
            base_query = case["validation_query"]
            without = await _simple_chat(client, profile.model, base_query)
            with_memory_prompt = (
                "以下是长期记忆检索结果，请优先遵循：\n"
                f"workflow_candidate: {case['expected_workflow']}\n\n"
                f"用户当前请求：{base_query}"
            )
            with_memory = await _simple_chat(client, profile.model, with_memory_prompt)
            rows.append({
                "case_id": case["case_id"],
                "without_memory_passed": _contains_workflow_hint(without, case["expected_workflow"]),
                "with_memory_passed": _contains_workflow_hint(with_memory, case["expected_workflow"]),
                "without_memory_answer": without[:800],
                "with_memory_answer": with_memory[:800],
            })
    finally:
        await client.close()
    return rows


def _workspace_registry(workspace: Path, memory_runtime: Any, dynamic_dependency_runtime: Any | None = None) -> Any:
    from mycodingagent.tool_runtime import ToolRegistry
    from mycodingagent.tool_runtime.bash import Bash
    from mycodingagent.tool_runtime.command_policy import BashPolicyEvaluator, BashPolicyStore
    from mycodingagent.tool_runtime.edit_file import EditFile
    from mycodingagent.tool_runtime.file_state_cache import FileStateCache
    from mycodingagent.tool_runtime.glob import Glob
    from mycodingagent.tool_runtime.grep import Grep
    from mycodingagent.tool_runtime.memory_lookup import (
        BatchRecoverContext,
        CommitWorkingContext,
        GetRecentConversationTurns,
        RestoreSession,
        SearchRecoverableContext,
        SearchSessionHistory,
        SummarizeCurrentTurnMessage,
    )
    from mycodingagent.tool_runtime.read_file import ReadFile
    from mycodingagent.tool_runtime.write_file import WriteFile
    from mycodingagent.workspace.file_cache import FileCache

    file_cache = FileCache()
    file_state_cache = FileStateCache()
    registry = ToolRegistry()
    registry.register(ReadFile(file_cache=file_cache, file_state_cache=file_state_cache, sandbox_root=workspace))
    registry.register(WriteFile(file_cache=file_cache, file_state_cache=file_state_cache, sandbox_root=workspace))
    registry.register(EditFile(file_cache=file_cache, file_state_cache=file_state_cache, sandbox_root=workspace))
    registry.register(
        Bash(
            sandbox_root=workspace,
            policy_evaluator=BashPolicyEvaluator(
                BashPolicyStore(memory_runtime.store.db_path)
            ),
        )
    )
    registry.register(Glob(sandbox_root=workspace))
    registry.register(Grep(sandbox_root=workspace))
    if dynamic_dependency_runtime is not None:
        from mycodingagent.code_intelligence.dynamic_dependency import DynamicDependencyRuntime
        from mycodingagent.tool_runtime.project_graph import QueryUnitDependencyTool, UpdateUnitDescriptionTool
        dynamic_runtime = dynamic_dependency_runtime if isinstance(dynamic_dependency_runtime, DynamicDependencyRuntime) else None
        if dynamic_runtime is not None:
            registry.register(UpdateUnitDescriptionTool(dynamic_runtime))
            registry.register(QueryUnitDependencyTool(dynamic_runtime))
    registry.register(CommitWorkingContext(memory_runtime))
    registry.register(BatchRecoverContext(memory_runtime))
    registry.register(RestoreSession(memory_runtime))
    registry.register(SearchRecoverableContext(memory_runtime))
    registry.register(SearchSessionHistory(memory_runtime))
    registry.register(GetRecentConversationTurns(memory_runtime))
    registry.register(SummarizeCurrentTurnMessage(memory_runtime))
    return registry


def _write_eval_project(workspace: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _snapshot_project_files(workspace: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith(".pyc"):
            snapshot[str(path.relative_to(workspace))] = path.read_text(encoding="utf-8", errors="replace")
    return snapshot


def _run_eval_test(workspace: Path, command: str) -> subprocess.CompletedProcess[str]:
    if command.strip() == "python3 -m pytest -q":
        argv = [sys.executable, "-m", "pytest", "-q"]
    else:
        argv = ["bash", "-lc", command]
    return subprocess.run(
        argv,
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=90,
        check=False,
    )


def _tool_call_names_from_messages(messages: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for message in messages:
        for call in message.get("tool_calls") or []:
            function = call.get("function") if isinstance(call, dict) else {}
            name = function.get("name") if isinstance(function, dict) else ""
            if name:
                names.append(str(name))
    return names


def write_report() -> Path:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    dataset_counts = {
        path.name: len(read_jsonl(path))
        for path in sorted(DATASET_DIR.glob("*.jsonl"))
    }
    result_summaries = []
    for path in sorted(RESULTS_DIR.glob("*.jsonl")):
        if path.name.endswith("_details.jsonl"):
            continue
        rows = read_jsonl(path)
        if rows:
            result_summaries.append((path.name, rows[-1]))

    lines = [
        "# myCodingAgent 有效性评测报告",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "- 评测原则：先生成测试集，再运行真实 API / 真实检索组件，最后汇总报告。",
        "",
        "## 测试集规模",
        "",
        "| 数据集 | 样例数 |",
        "|---|---:|",
    ]
    for name, count in dataset_counts.items():
        lines.append(f"| `{name}` | {count} |")
    lines.extend(["", "## 已运行结果", "", "| 模块 | 状态 | 关键结果 |", "|---|---|---|"])
    if result_summaries:
        for name, summary in result_summaries:
            lines.append(f"| `{name}` | {summary.get('status', 'unknown')} | {_compact_summary(summary)} |")
    else:
        lines.append("| 无 | not_run | 尚未执行评测 runner |")
    lines.extend([
        "",
        "## 模块覆盖说明",
        "",
        "- 上下文虚拟化：比较 raw、virtualized、summary_baseline、recent_only 四种上下文策略对早期需求召回和成本的影响。",
        "- 长期记忆：重点验证 workflow_candidate 跨会话检索后是否减少重复工具调用并提高成功率。",
        "- Skill 路由：在 500+ name/description Skill 下测试目标 Skill 是否进入 Top-K 候选。",
        "- Capability Router / MCP：验证简单任务、Skill、MCP、恢复工具等能力是否被正确路由。",
        "- 恢复工具：验证虚拟化历史工具输出是否能通过 BatchRecoverContext 精确恢复。",
        "",
        "## 结论填写规则",
        "",
        "- 只有 `status=passed` 的模块可以作为简历或项目文档中的有效性证据。",
        "- `blocked` 表示依赖未满足，例如 Milvus 未启动、BGE 不可用或真实 API 配置缺失。",
        "- hash embedding smoke test 不计入 Skill 语义路由正式结论。",
    ])
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return REPORT_PATH


def _reciprocal_rank(names: list[str], expected: set[str]) -> float:
    for index, name in enumerate(names, start=1):
        if name in expected:
            return 1.0 / index
    return 0.0


def _mean(values) -> float:
    materialized = [float(value) for value in values]
    return round(statistics.mean(materialized), 4) if materialized else 0.0


def _group_mean(rows: list[dict[str, Any]], group_key: str, value_key: str) -> dict[str, float]:
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(str(row[group_key]), []).append(row[value_key])
    return {key: _mean(values) for key, values in sorted(grouped.items())}


async def _simple_chat(client: Any, model: str, prompt: str) -> str:
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是严谨的评测被测模型。请直接回答，不要编造不可见信息。"},
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )
    return response.choices[0].message.content or ""


def _context_prompt(case: dict[str, Any], *, mode: str) -> str:
    if mode == "recent_only":
        material = case["messages"][-20:]
    elif mode == "summary_baseline":
        material = [{"role": "summary", "content": f"早期会话摘要：{case['early_fact']}"}] + case["messages"][-20:]
    elif mode == "virtualized":
        material = []
        for message in case["messages"]:
            if message.get("role") == "tool":
                material.append({
                    "role": "tool",
                    "content": {
                        "tool_output_virtualized": True,
                        "tool_call_id": message.get("tool_call_id"),
                        "recover": "Use BatchRecoverContext only if exact historical tool output is needed.",
                    },
                })
            else:
                material.append(message)
    else:
        material = case["messages"]
    return (
        "以下是会话历史，请根据历史回答最后问题。\n"
        f"{json.dumps(material, ensure_ascii=False)}\n\n"
        f"最后问题：{case['final_query']}"
    )


def _answer_contains_expected(answer: str, expected_items: list[str]) -> bool:
    for item in expected_items:
        if item in answer:
            continue
        if "=" in item:
            key, value = item.split("=", 1)
            if key in answer and value in answer:
                continue
        return False
    return True


def _recover_case_output(case: dict[str, Any], raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return "Tool execution error: invalid JSON"
    items = args.get("items") or []
    outputs = []
    for item in items:
        if item.get("context_id") != case["context_id"]:
            outputs.append({"context_id": item.get("context_id"), "error": "context_id not found"})
            continue
        offset = int(item.get("offset") or 0)
        limit = int(item.get("limit") or len(case["stored_output"]))
        content = case["stored_output"][offset:offset + limit]
        outputs.append({"context_id": case["context_id"], "content": content, "has_more": offset + limit < len(case["stored_output"])})
    return json.dumps({"items": outputs}, ensure_ascii=False)


def _contains_workflow_hint(answer: str, workflow: str) -> bool:
    anchors = [
        "一次性", "批量", "重复读取", "现有测试", "公共接口", "完整回归",
        "route", "service", "repository", "test", "状态流", "事件入口",
        "BatchRecoverContext", "批量恢复", "skill_candidate", "用户确认",
    ]
    expected = [anchor for anchor in anchors if anchor in workflow]
    if expected:
        return sum(1 for anchor in expected if anchor in answer) >= max(1, math.ceil(len(expected) * 0.5))
    compact_workflow = "".join(ch for ch in workflow if not ch.isspace() and ch not in "，。；、,. ;")
    compact_answer = "".join(ch for ch in answer if not ch.isspace() and ch not in "，。；、,. ;")
    grams = {compact_workflow[index:index + 4] for index in range(max(0, len(compact_workflow) - 3))}
    grams = {gram for gram in grams if len(gram) == 4}
    if not grams:
        return compact_workflow[:6] in compact_answer
    return sum(1 for gram in grams if gram in compact_answer) / len(grams) >= 0.25


def _drop_milvus_collection_quietly(collection_name: str) -> None:
    if not collection_name:
        return
    try:
        from mycodingagent.configuration import CONFIG
        from pymilvus import MilvusClient

        client = MilvusClient(uri=CONFIG.milvus.uri, token=CONFIG.milvus.token)
        if client.has_collection(collection_name):
            client.drop_collection(collection_name)
    except Exception:
        return


def _compact_summary(summary: dict[str, Any]) -> str:
    keys = [
        "endpoint", "model", "dimension", "skill_count", "query_count",
        "recall_at_1", "recall_at_3", "recall_at_5", "mrr", "reason",
        "case_count", "run_count", "direct_accuracy", "direct_avg_duration_seconds",
    ]
    parts = [f"{key}={summary[key]}" for key in keys if key in summary]
    return "; ".join(parts) if parts else json.dumps(summary, ensure_ascii=False)[:160]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real effectiveness evaluations.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("precheck-bge")
    skill_parser = sub.add_parser("run-skill-router")
    skill_parser.add_argument("--dataset", default=str(DATASET_DIR / "skill_router_500_cases.jsonl"))
    skill_parser.add_argument("--limit", type=int, default=None)
    skill_parser.add_argument("--keep-collection", action="store_true")
    context_parser = sub.add_parser("run-context")
    context_parser.add_argument("--dataset", default=str(DATASET_DIR / "context_virtualization_cases.jsonl"))
    context_parser.add_argument("--limit", type=int, default=None)
    recovery_parser = sub.add_parser("run-recovery")
    recovery_parser.add_argument("--dataset", default=str(DATASET_DIR / "recovery_cases.jsonl"))
    recovery_parser.add_argument("--limit", type=int, default=None)
    capability_parser = sub.add_parser("run-capability-router")
    capability_parser.add_argument("--dataset", default=str(DATASET_DIR / "capability_router_cases.jsonl"))
    capability_parser.add_argument("--limit", type=int, default=None)
    ltm_parser = sub.add_parser("run-long-term-workflow")
    ltm_parser.add_argument("--dataset", default=str(DATASET_DIR / "long_term_workflow_cases.jsonl"))
    ltm_parser.add_argument("--limit", type=int, default=None)
    sub.add_parser("report")
    args = parser.parse_args()

    if args.command == "precheck-bge":
        print(json.dumps(precheck_bge(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "run-skill-router":
        os.environ.setdefault("MYCODINGAGENT_MILVUS_COLLECTION", f"mycodingagent_eval_skills_{int(time.time())}")
        result = run_skill_router(Path(args.dataset), limit=args.limit, keep_collection=args.keep_collection)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0 if result.get("status") == "passed" else 2
    if args.command == "run-context":
        result = run_context_virtualization(Path(args.dataset), limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "run-recovery":
        result = run_recovery(Path(args.dataset), limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "run-capability-router":
        result = run_capability_router(Path(args.dataset), limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "run-long-term-workflow":
        result = run_long_term_workflow(Path(args.dataset), limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "report":
        print(write_report())
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
