from __future__ import annotations

import asyncio
from pathlib import Path

from mycodingagent.llm_runtime.providers import StreamRoundResult
from mycodingagent.skill_runtime.discovery import discover_skill_records
from mycodingagent.skill_runtime.dynamic_summary import DynamicSkillSummary
from mycodingagent.skill_runtime.runtime import SkillRuntime
from mycodingagent.tool_runtime import ToolRegistry


class FakeVectorStore:
    needs_full_sync = False
    last_cache_hits = 0
    last_cache_misses = 0

    def upsert(self, records):
        return None

    def delete_missing(self, existing_tool_names):
        return None

    def stale_records(self, records):
        return []

    def search(self, query, *, records, top_k, preferred_names=None):
        return None


class FakeSummaryProvider:
    def __init__(self) -> None:
        self.calls = []

    async def stream_chat(self, request):
        self.calls.append(request)
        return StreamRoundResult(
            text="代码工程：审查、前后端开发；内容创作：图文、音视频与发布",
            tool_calls=[],
        )


class FailingSummaryProvider:
    async def stream_chat(self, request):
        raise RuntimeError("summary unavailable")


def test_discovery_marks_fixed_and_dynamic_tiers(tmp_path: Path):
    base = tmp_path / "skills"
    _write_skill(base / "fixed" / "standards" / "SKILL.md", "Standards", "Stable coding rules", "FIXED BODY")
    _write_skill(base / "Dynamic" / "review" / "SKILL.md", "Review", "Review code changes", "DYNAMIC BODY")

    fixed = discover_skill_records(base / "fixed", tier="fixed")
    dynamic = discover_skill_records(base / "Dynamic", tier="dynamic")

    assert [(record.tool_name, record.metadata["tier"]) for record in fixed] == [("skill_standards", "fixed")]
    assert [(record.tool_name, record.metadata["tier"]) for record in dynamic] == [("skill_review", "dynamic")]


def test_fixed_skills_are_prompted_but_excluded_from_dynamic_routing(tmp_path: Path, monkeypatch):
    base = tmp_path / "skills"
    _write_skill(
        base / "fixed" / "shared" / "SKILL.md",
        "Shared Workflow",
        "Fixed description",
        "SECRET FIXED BODY",
    )
    _write_skill(
        base / "Dynamic" / "shared" / "SKILL.md",
        "Shared Workflow",
        "Conflicting dynamic description",
        "CONFLICTING BODY",
    )
    _write_skill(
        base / "Dynamic" / "review" / "SKILL.md",
        "Review",
        "Review code changes",
        "REVIEW BODY",
    )
    runtime = _runtime(base, monkeypatch)

    report = asyncio.run(runtime.sync())

    assert runtime.fixed_records["skill_shared_workflow"].description == "Fixed description"
    assert set(runtime.dynamic_records) == {"skill_review"}
    assert any("与 fixed Skill 工具名冲突" in item for item in report.rejected)

    fixed_hint = runtime.fixed_skill_hint(max_tokens=500)
    assert "skill_name: skill_shared_workflow" in fixed_hint
    assert "Fixed description" in fixed_hint
    assert "SECRET FIXED BODY" not in fixed_hint
    system_hint = runtime.system_hint()
    assert "Skill 分为 fixed 和 Dynamic 两类" in system_hint
    assert "保持固定前缀稳定" in system_hint
    assert "先用能力摘要判断" in system_hint
    management_names = {schema["name"] for schema in runtime._skill_management_schemas()}
    assert "search_skill" in management_names
    assert "search_tool" not in management_names
    assert "Get_tool_by_name" not in management_names

    search = asyncio.run(runtime.search_skill_schemas(query="review code", max_results=5))
    listing = asyncio.run(runtime.list_dynamic_skills())
    assert [item["skill_name"] for item in search["skills"]] == ["skill_review"]
    assert [item["name"] for item in listing["tools"]] == ["skill_review"]

    runtime.record_skill_invocation("skill_shared_workflow")
    assert runtime.session_skill_call_round == 0
    runtime.record_skill_invocation("skill_review")
    assert runtime.session_skill_call_round == 1


def test_fixed_skill_hint_is_stable_and_budgeted(tmp_path: Path, monkeypatch):
    base = tmp_path / "skills"
    _write_skill(base / "fixed" / "zeta" / "SKILL.md", "Zeta", "Zeta description", "ZETA BODY")
    _write_skill(base / "fixed" / "alpha" / "SKILL.md", "Alpha", "Alpha description", "ALPHA BODY")
    runtime = _runtime(base, monkeypatch)
    asyncio.run(runtime.sync())

    full = runtime.fixed_skill_hint(max_tokens=500)
    limited = runtime.fixed_skill_hint(max_tokens=45)

    assert full.index("skill_alpha") < full.index("skill_zeta")
    assert "ALPHA BODY" not in full
    assert "fixed Skill 因固定卡片预算未展示" in limited


def test_materialized_long_term_workflow_uses_user_dynamic_root(tmp_path: Path, monkeypatch):
    builtin_root = tmp_path / "builtin"
    user_root = tmp_path / "user"
    runtime = _runtime(builtin_root, monkeypatch, roots=[builtin_root, user_root])
    runtime.user_skills_root = user_root
    workflow = {
        "name": "Large File Split",
        "description": "Split a large source file without repeated reads.",
        "when_to_use": "Several modules must be extracted from one source file.",
        "when_not_use": ["Only one small function changes."],
    }

    first = asyncio.run(
        runtime.materialize_dynamic_skill(memory_uid="memory-1", workflow=workflow, content="Locate boundaries, then write in batch.")
    )
    updated = asyncio.run(
        runtime.materialize_dynamic_skill(memory_uid="memory-1", workflow=workflow, content="Updated workflow body.")
    )

    skill_path = user_root / "Dynamic" / "skill_large_file_split" / "SKILL.md"
    assert first["status"] == "materialized"
    assert updated["status"] == "materialized"
    assert "memory_uid: memory-1" in skill_path.read_text(encoding="utf-8")
    assert "Updated workflow body." in skill_path.read_text(encoding="utf-8")
    assert runtime.dynamic_records["skill_large_file_split"].metadata["tier"] == "dynamic"

    conflict = asyncio.run(
        runtime.materialize_dynamic_skill(memory_uid="memory-2", workflow=workflow, content="Foreign overwrite.")
    )
    assert conflict["status"] == "conflict"
    assert "Foreign overwrite." not in skill_path.read_text(encoding="utf-8")


def test_dynamic_summary_calls_model_only_when_catalog_changes(tmp_path: Path):
    dynamic_root = tmp_path / "Dynamic"
    skill_path = dynamic_root / "review" / "SKILL.md"
    _write_skill(skill_path, "Review", "Review code changes", "BODY")
    records = {record.tool_name: record for record in discover_skill_records(dynamic_root, tier="dynamic")}
    provider = FakeSummaryProvider()
    summary = DynamicSkillSummary(tmp_path / "summary.json", provider_getter=lambda: provider)

    first = asyncio.run(summary.refresh(records))
    second = asyncio.run(summary.refresh(records))
    _write_skill(skill_path, "Review", "Review code and architecture changes", "BODY")
    changed_records = {record.tool_name: record for record in discover_skill_records(dynamic_root, tier="dynamic")}
    third = asyncio.run(summary.refresh(changed_records))

    assert first == second == third
    assert len(provider.calls) == 2
    assert provider.calls[0].display is False
    assert provider.calls[0].temperature == 0

    reloaded = DynamicSkillSummary(tmp_path / "summary.json", provider_getter=lambda: provider)
    assert asyncio.run(reloaded.refresh(changed_records)) == third
    assert len(provider.calls) == 2


def test_changed_catalog_does_not_reuse_stale_summary_when_model_fails(tmp_path: Path):
    dynamic_root = tmp_path / "Dynamic"
    skill_path = dynamic_root / "review" / "SKILL.md"
    _write_skill(skill_path, "Review", "Review code changes", "BODY")
    records = {record.tool_name: record for record in discover_skill_records(dynamic_root, tier="dynamic")}
    cache_path = tmp_path / "summary.json"
    working = DynamicSkillSummary(cache_path, provider_getter=lambda: FakeSummaryProvider())
    assert asyncio.run(working.refresh(records))

    _write_skill(skill_path, "Review", "Review code and architecture changes", "BODY")
    changed_records = {record.tool_name: record for record in discover_skill_records(dynamic_root, tier="dynamic")}
    failing = DynamicSkillSummary(cache_path, provider_getter=lambda: FailingSummaryProvider())

    assert asyncio.run(failing.refresh(changed_records)) == ""
    assert failing.summary == ""


def _runtime(base: Path, monkeypatch, *, roots: list[Path] | None = None) -> SkillRuntime:
    from mycodingagent.skill_runtime import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "create_embedding_service", lambda: object())
    monkeypatch.setattr(runtime_module, "create_vector_store", lambda *_args: FakeVectorStore())
    return SkillRuntime(
        skills_root=base,
        skill_roots=roots or [base],
        registry=ToolRegistry(),
    )


def _write_skill(path: Path, name: str, description: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
