from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import pytest


REAL_API_EVAL_ENABLED = os.getenv("RUN_REAL_API_EVAL") == "1"
pytestmark = [
    pytest.mark.skipif(
        not REAL_API_EVAL_ENABLED,
        reason="real API evaluation is disabled; set RUN_REAL_API_EVAL=1 to run",
    )
]


if REAL_API_EVAL_ENABLED:
    os.environ.setdefault("STEP_TOKEN", "0")
    os.environ.setdefault("ROUND_TOKEN", "0")
    os.environ.setdefault("CONVERSATION_TOKEN", "0")
    os.environ.setdefault("MYCODINGAGENT_LONG_TERM_MEMORY_STARTUP_BACKFILL_ENABLED", "0")

pytest.importorskip("openai")

from openai import AsyncOpenAI

from mycodingagent.multi_agent.context import run_summary_for_main_context
from mycodingagent.multi_agent.orchestrator import MultiAgentOrchestrator
from mycodingagent.multi_agent.store import MultiAgentStore
from mycodingagent.capability_discovery.router import CapabilityRouter
from mycodingagent.llm_runtime import client as agent_client
from mycodingagent.long_term_memory.runtime import LongTermMemoryRuntime
from mycodingagent.long_term_memory.store import SQLiteLongTermMemoryStore
from mycodingagent.memory import ContextCompressor, MemoryRuntime, SQLiteMemoryStore
from mycodingagent.skill_runtime.models import SearchResult, SkillRecord
from mycodingagent.tool_runtime import ToolRegistry
from mycodingagent.tool_runtime.bash import Bash, get_docker_image
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
from mycodingagent.tool_runtime.skill_tools import InvokeSkillTool
from mycodingagent.tool_runtime.write_file import WriteFile
from mycodingagent.workspace.file_cache import FileCache


RESULTS_PATH = Path(os.getenv("MYCODINGAGENT_REAL_API_EVAL_RESULTS", ".pytest_cache/real_api_eval.jsonl"))


@dataclass
class EvalHarness:
    workspace: Path
    state_dir: Path
    registry: ToolRegistry
    memory_runtime: MemoryRuntime
    multi_agent_store: MultiAgentStore
    api_client: AsyncOpenAI

    @property
    def tools(self) -> list[dict[str, Any]]:
        return agent_client.format_openai_tools(self.registry.get_all_schemas("openai"))

    async def close(self) -> None:
        await self.memory_runtime.close()
        await self.api_client.close()


class StaticSkillSource:
    def __init__(self, record: SkillRecord) -> None:
        self.records = {record.tool_name: record}
        self.router_retrieval_top_k = 5
        self.invocations: list[str] = []

    def recommend_records_for_capability(self, _query: str, *, top_k: int) -> list[SearchResult]:
        record = next(iter(self.records.values()))
        return [SearchResult(record=record, score=1.0, keyword_score=1.0, semantic_score=0.0)][:top_k]

    def search_records_for_capability(self, query: str, *, top_k: int) -> list[SearchResult]:
        return self.recommend_records_for_capability(query, top_k=top_k)

    def get_record(self, tool_name: str) -> SkillRecord | None:
        return self.records.get(tool_name)

    def record_skill_invocation(self, tool_name: str) -> None:
        self.invocations.append(tool_name)

    def list_references_for_skill(self, _tool_name: str) -> list[dict[str, Any]]:
        return []


def test_real_api_runtime_development_loop(tmp_path: Path):
    _require_docker_image()
    result = _run_case("runtime_development_loop", tmp_path, _case_runtime_development_loop)
    assert result["success"], result["failure_reason"]


def test_real_api_capability_routing_uses_recommended_skill(tmp_path: Path):
    result = _run_case("capability_routing_skill", tmp_path, _case_capability_routing_skill)
    assert result["success"], result["failure_reason"]


def test_real_api_context_virtualization_recovers_omitted_output(tmp_path: Path):
    result = _run_case("context_virtualization_recovery", tmp_path, _case_context_virtualization_recovery)
    assert result["success"], result["failure_reason"]


def test_real_api_long_term_memory_cross_session(tmp_path: Path):
    result = _run_case("long_term_memory_cross_session", tmp_path, _case_long_term_memory_cross_session)
    assert result["success"], result["failure_reason"]


def test_real_api_multi_agent_minimal_workflow(tmp_path: Path):
    _require_docker_image()
    result = _run_case("multi_agent_minimal_workflow", tmp_path, _case_multi_agent_minimal_workflow)
    assert result["success"], result["failure_reason"]


def _run_case(
    case_id: str,
    tmp_path: Path,
    case: Callable[[Path], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    started = time.time()
    try:
        result = asyncio.run(case(tmp_path))
    except Exception as exc:
        result = {
            "case_id": case_id,
            "success": False,
            "duration_seconds": round(time.time() - started, 3),
            "failure_reason": f"{type(exc).__name__}: {exc}",
        }
        _append_result(result)
        raise
    result.setdefault("case_id", case_id)
    result.setdefault("success", False)
    result.setdefault("duration_seconds", round(time.time() - started, 3))
    result.setdefault("failure_reason", "")
    _append_result(result)
    return result


async def _case_runtime_development_loop(tmp_path: Path) -> dict[str, Any]:
    harness = _make_harness(tmp_path / "workspace", tmp_path / "state", context_window=64_000)
    try:
        _write_runtime_bug_project(harness.workspace)
        prompt = (
            "当前 /workspace 下有一个最小 Python 项目。请修复 pytest 失败，只做必要修改，"
            "完成后运行 `python -m pytest -q` 验证，并在最终回答中说明测试是否通过。"
        )
        text, messages = await agent_client.ask_deepseek(
            harness.api_client,
            prompt,
            harness.registry,
            harness.tools,
            messages=None,
            memory_runtime=harness.memory_runtime,
            core_tool_schemas=harness.registry.get_all_schemas("openai"),
        )
        verify = _run_pytest(harness.workspace)
        tool_names = _tool_call_names(messages)
        success = verify.returncode == 0 and "passed" in verify.stdout
        return {
            "success": success,
            "failure_reason": "" if success else f"pytest failed: {verify.stdout[-1000:]} {verify.stderr[-1000:]}",
            "final_answer": text[-1000:],
            "tool_calls": len(tool_names),
            "tool_names": tool_names,
            "test_passed": verify.returncode == 0,
            "human_intervention_count": tool_names.count("ask_user"),
            "tokens": _token_summary(harness.memory_runtime),
        }
    finally:
        await harness.close()


async def _case_capability_routing_skill(tmp_path: Path) -> dict[str, Any]:
    harness = _make_harness(tmp_path / "workspace", tmp_path / "state", context_window=64_000)
    skill_record = SkillRecord(
        name="Resume Responsibility Writer",
        tool_name="skill_resume_responsibility",
        description="将 Coding Agent 项目经历改写为简历责任描述。",
        content=(
            "你是简历责任描述工作流。输出必须包含标记 EVAL_SKILL_USED，"
            "并给出 3 条以“责任描述：”开头的中文项目责任。"
        ),
        source_path=tmp_path / "skills" / "resume" / "SKILL.md",
        content_hash="eval",
        updated_at=time.time(),
    )
    skill_source = StaticSkillSource(skill_record)
    harness.registry.register(InvokeSkillTool(skill_source))
    capability_router = CapabilityRouter(skill_runtime=skill_source)
    try:
        text, messages = await agent_client.ask_deepseek(
            harness.api_client,
            "帮我把 Coding Agent 项目经历改成简历责任描述。",
            harness.registry,
            harness.tools,
            messages=None,
            memory_runtime=harness.memory_runtime,
            capability_router=capability_router,
            core_tool_schemas=harness.registry.get_all_schemas("openai"),
        )
        tool_names = _tool_call_names(messages)
        success = "invoke_skill" in tool_names and "EVAL_SKILL_USED" in text
        route = await capability_router.route("简历责任描述")
        return {
            "success": success,
            "failure_reason": "" if success else "model did not invoke the routed skill or did not use its output",
            "final_answer": text[-1000:],
            "tool_calls": len(tool_names),
            "tool_names": tool_names,
            "routing_top_names": [item.name for item in route.recommendations],
            "routing_top1_hit": bool(route.recommendations and route.recommendations[0].name == skill_record.tool_name),
            "skill_invoked": "invoke_skill" in tool_names,
            "tokens": _token_summary(harness.memory_runtime),
        }
    finally:
        await harness.close()


async def _case_context_virtualization_recovery(tmp_path: Path) -> dict[str, Any]:
    harness = _make_harness(tmp_path / "workspace", tmp_path / "state", context_window=32_000)
    try:
        secret = "MIDDLE_SECRET_CODE=ZX-9142"
        _write_large_context_file(harness.workspace / "big_context.txt", secret)
        messages: list[dict[str, Any]] | None = None
        first_text, messages = await agent_client.ask_deepseek(
            harness.api_client,
            "请读取 /workspace/big_context.txt。只确认已经读取，不要总结文件内容。",
            harness.registry,
            harness.tools,
            messages=messages,
            memory_runtime=harness.memory_runtime,
            core_tool_schemas=harness.registry.get_all_schemas("openai"),
        )
        preview_seen = any("[Tool output preview]" in str(message.get("content", "")) for message in messages)
        second_text, messages = await agent_client.ask_deepseek(
            harness.api_client,
            "刚才读取的文件中 MIDDLE_SECRET_CODE 的完整值是什么？如果当前上下文不可见，请使用恢复工具读取后回答。",
            harness.registry,
            harness.tools,
            messages=messages,
            memory_runtime=harness.memory_runtime,
            core_tool_schemas=harness.registry.get_all_schemas("openai"),
        )
        tool_names = _tool_call_names(messages)
        success = secret in second_text and "BatchRecoverContext" in tool_names
        raw_size = len((harness.workspace / "big_context.txt").read_text(encoding="utf-8"))
        return {
            "success": success,
            "failure_reason": "" if success else "model did not recover omitted middle content correctly",
            "first_answer": first_text[-500:],
            "final_answer": second_text[-1000:],
            "tool_calls": len(tool_names),
            "tool_names": tool_names,
            "preview_seen": preview_seen,
            "recovery_tool_used": "BatchRecoverContext" in tool_names,
            "raw_file_chars": raw_size,
            "tokens": _token_summary(harness.memory_runtime),
        }
    finally:
        await harness.close()


async def _case_long_term_memory_cross_session(tmp_path: Path) -> dict[str, Any]:
    harness = _make_harness(tmp_path / "workspace", tmp_path / "state", context_window=64_000)
    long_term = LongTermMemoryRuntime(
        memory_runtime=harness.memory_runtime,
        registry=harness.registry,
        api_client=harness.api_client,
        user_id="eval_user",
        storage_model=agent_client.MODEL,
        query_model=agent_client.MODEL,
        store=SQLiteLongTermMemoryStore(tmp_path / "state" / "long_term_memory.sqlite3"),
    )
    try:
        session_id = harness.memory_runtime.start_session(agent_client.MODEL)
        messages = [
            {"role": "user", "content": "请记住：我偏好中文回答。项目事实：myCodingAgent 使用 Capability Router + Skill Router 双层能力路由。"},
            {"role": "assistant", "content": "已记录你的中文回答偏好，以及项目使用双层能力路由这一事实。"},
        ]
        harness.memory_runtime.save_messages_now(session_id, messages)
        await harness.memory_runtime.drain()
        extraction = await long_term.extract_session_now(session_id, timeout_seconds=120)
        context = await long_term.retrieve_for_turn(
            current_query="你记得我对回答语言和 agent 项目能力路由的偏好吗？",
            recent_messages=[],
        )
        payload = context.to_runtime_payload() if context is not None else {}
        payload_text = json.dumps(payload, ensure_ascii=False)
        has_preference = "中文" in payload_text
        has_project_fact = "Capability Router" in payload_text and "Skill Router" in payload_text
        success = extraction.status == "committed" and has_preference and has_project_fact
        return {
            "success": success,
            "failure_reason": "" if success else f"memory extraction/query miss: extraction={extraction}",
            "extraction_status": extraction.status,
            "version_id": extraction.version_id,
            "memory_hit": context is not None,
            "memory_payload": payload,
            "memory_accuracy": {
                "preference_hit": has_preference,
                "project_fact_hit": has_project_fact,
            },
            "tokens": _token_summary(harness.memory_runtime),
        }
    finally:
        await long_term.close()
        await harness.close()


async def _case_multi_agent_minimal_workflow(tmp_path: Path) -> dict[str, Any]:
    harness = _make_harness(tmp_path / "workspace", tmp_path / "state", context_window=96_000)
    try:
        _write_multi_agent_project(harness.workspace)
        orchestrator = MultiAgentOrchestrator(
            store=harness.multi_agent_store,
            registry=harness.registry,
            api_client=harness.api_client,
            memory_runtime=harness.memory_runtime,
            model=agent_client.MODEL,
        )
        run = await orchestrator.start(
            task=(
                "修复 /workspace 中的小型 Python 项目。当前 test_app.py 失败，"
                "需要让 app.user_label(user) 使用 user['name'] 和 user['role']，"
                "最终返回形如 'User: Ada (admin)'，并运行 python -m pytest -q 验证。"
            ),
            main_messages=[],
        )
        payload = json.loads(run_summary_for_main_context(run))
        run_id = payload.get("run_id", "")
        run = harness.multi_agent_store.load_run(run_id)
        verify = _run_pytest(harness.workspace)
        success = (
            payload.get("status") == "completed"
            and run is not None
            and verify.returncode == 0
            and bool(run.approved_plan)
            and bool(run.step_submissions)
            and run.test_result.get("status") == "approved"
            and run.review_result.get("status") == "approved"
        )
        return {
            "success": success,
            "failure_reason": "" if success else f"multi-agent failed: {payload}, pytest={verify.stdout[-1000:]} {verify.stderr[-1000:]}",
            "multi_agent_result": payload,
            "run_id": run_id,
            "plan_approved": bool(run and run.approved_plan),
            "submitted_steps": len(run.step_submissions) if run else 0,
            "test_result": run.test_result if run else {},
            "execute_review_result": run.review_result if run else {},
            "test_passed": verify.returncode == 0,
            "subagent_rounds": run.subagent_rounds_used if run else {},
            "subagent_tool_calls": run.subagent_tool_calls_used if run else {},
            "tokens": _token_summary(harness.memory_runtime),
        }
    finally:
        await harness.close()


def _make_harness(workspace: Path, state_dir: Path, *, context_window: int) -> EvalHarness:
    workspace.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    file_cache = FileCache()
    file_state_cache = FileStateCache()
    registry = ToolRegistry()
    registry.register(ReadFile(file_cache=file_cache, file_state_cache=file_state_cache, sandbox_root=workspace))
    registry.register(
        WriteFile(
            file_cache=file_cache,
            file_state_cache=file_state_cache,
            workspace_tracker=None,
            sandbox_root=workspace,
        )
    )
    registry.register(
        EditFile(
            file_cache=file_cache,
            file_state_cache=file_state_cache,
            workspace_tracker=None,
            sandbox_root=workspace,
        )
    )
    registry.register(Bash(sandbox_root=workspace))
    registry.register(Glob(sandbox_root=workspace))
    registry.register(Grep(sandbox_root=workspace))

    memory_runtime = MemoryRuntime(
        store=SQLiteMemoryStore(state_dir / "sessions.sqlite3"),
        compressor=ContextCompressor(context_window=context_window),
        model=agent_client.MODEL,
        workspace_root=str(workspace),
    )
    registry.register(CommitWorkingContext(memory_runtime))
    registry.register(BatchRecoverContext(memory_runtime))
    registry.register(RestoreSession(memory_runtime))
    registry.register(SearchRecoverableContext(memory_runtime))
    registry.register(SearchSessionHistory(memory_runtime))
    registry.register(GetRecentConversationTurns(memory_runtime))
    registry.register(SummarizeCurrentTurnMessage(memory_runtime))

    api_client = AsyncOpenAI(api_key=agent_client.DEEPSEEK_API_KEY, base_url=agent_client.BASE_URL)
    multi_agent_store = MultiAgentStore(state_dir / "multi_agent.sqlite3")
    return EvalHarness(
        workspace=workspace,
        state_dir=state_dir,
        registry=registry,
        memory_runtime=memory_runtime,
        multi_agent_store=multi_agent_store,
        api_client=api_client,
    )


def _write_runtime_bug_project(workspace: Path) -> None:
    (workspace / "calculator.py").write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (workspace / "test_calculator.py").write_text(
        "from calculator import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )


def _write_large_context_file(path: Path, secret: str) -> None:
    lines = [f"head filler line {index:03d}: not the answer" for index in range(90)]
    lines.append(secret)
    lines.extend(f"tail filler line {index:03d}: not the answer" for index in range(90, 260))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_multi_agent_project(workspace: Path) -> None:
    (workspace / "service.py").write_text(
        "def format_user(name, role):\n    return f\"User: {name} ({role})\"\n",
        encoding="utf-8",
    )
    (workspace / "app.py").write_text(
        "from service import format_user\n\n\n"
        "def user_label(user):\n"
        "    return format_user(user[\"name\"])\n",
        encoding="utf-8",
    )
    (workspace / "test_app.py").write_text(
        "from app import user_label\n\n\n"
        "def test_user_label():\n"
        "    assert user_label({\"name\": \"Ada\", \"role\": \"admin\"}) == \"User: Ada (admin)\"\n",
        encoding="utf-8",
    )


def _run_pytest(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )


def _tool_call_names(messages: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for message in messages:
        for call in message.get("tool_calls") or []:
            function = call.get("function") if isinstance(call, dict) else {}
            name = function.get("name") if isinstance(function, dict) else ""
            if name:
                names.append(str(name))
    return names


def _token_summary(memory_runtime: MemoryRuntime) -> dict[str, int]:
    session_id = memory_runtime.get_current_session_id()
    if not session_id:
        return {}
    summary = memory_runtime.load_token_usage_summary(session_id)
    return {
        "request_count": summary.request_count,
        "prompt_tokens": summary.prompt_tokens,
        "completion_tokens": summary.completion_tokens,
        "total_tokens": summary.total_tokens,
    }


def _append_result(result: dict[str, Any]) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": time.time(), **result}
    with RESULTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _require_docker_image() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for real API coding eval cases")
    image = get_docker_image()
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"Docker image {image!r} is required for real API coding eval cases")
