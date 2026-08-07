from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import sys

import pytest

from mycodingagent.capability_discovery import CapabilityRouter
from mycodingagent.capability_discovery.models import CapabilityRecommendation, CapabilityResult
from mycodingagent.mcp_integration.hooks import CLIApprovalHook, MCPToolApprovalHook, USER_DENIED_MESSAGE
from mycodingagent.mcp_integration import MCPClientManager, MCPConfigLoader
from mycodingagent.mcp_integration.manager import _validate_playwright_output_arguments
from mycodingagent.mcp_integration.config import MCPServerConfig
from mycodingagent.mcp_integration.cache import MCPMetadataCache
from mycodingagent.mcp_integration.execution import normalize_mcp_result
from mycodingagent.network_access import NetworkAccessRuntime
from mycodingagent.mcp_integration.models import MCPExecutionResult, MCPItemSummary
from mycodingagent.mcp_integration.policy import MCPApprovalDecision, MCPToolPermissionPolicy
from mycodingagent.llm_runtime.context import PromptRenderer, RuntimeContextBuilder
from mycodingagent.tool_runtime import ToolRegistry
from mycodingagent.tool_runtime.mcp_discovery import register_mcp_discovery_tools
from mycodingagent.tool_runtime.mcp_execution import register_mcp_execution_tools
from mycodingagent.tool_runtime.playwright_direct import register_discovered_playwright_tools
from mycodingagent.tool_runtime.skill_tools import SearchSkillTool
from mycodingagent.skill_runtime.models import SearchResult, SkillRecord


def test_discovered_playwright_tools_are_registered_with_remote_names(tmp_path):
    class FakeManager:
        server_configs = {}

        @staticmethod
        def cached_tools(_server):
            return [
                MCPItemSummary(
                    name="browser_take_screenshot",
                    description="Capture page screenshot",
                    metadata={
                        "inputSchema": {
                            "type": "object",
                            "properties": {"fullPage": {"type": "boolean"}},
                        }
                    },
                )
            ]

    registry = ToolRegistry()
    count = register_discovered_playwright_tools(
        registry,
        manager=FakeManager(),
        policy=MCPToolPermissionPolicy(),
        approval_hook=MCPToolApprovalHook(),
    )
    schema = registry.get("browser_take_screenshot").get_schema()["input_schema"]

    assert count == 1
    assert "browser_take_screenshot" in {item["name"] for item in registry.get_all_schemas("openai")}
    assert "fullPage" in schema["properties"]
    assert "intent" in schema["required"]


def test_discovered_mcp_tool_count_is_reflected_in_server_summary():
    config = MCPServerConfig(name="playwright")
    cache = MCPMetadataCache()
    cache.sync_configs({"playwright": config})
    cache.update_discovery(
        "playwright",
        tools=[
            MCPItemSummary(name="browser_navigate"),
            MCPItemSummary(name="browser_snapshot"),
        ],
    )

    summary = cache.servers()[0]

    assert summary.tools_count == 2


def test_playwright_is_hidden_from_model_facing_mcp_server_list():
    manager = MCPClientManager(metadata_cache=MCPMetadataCache())
    manager.server_configs = {"playwright": MCPServerConfig(name="playwright")}
    manager.metadata_cache.sync_configs(manager.server_configs)

    assert manager.list_servers() == []
    assert manager.server_count() == 0


def test_runtime_context_skill_recommendation_points_to_invoke_skill():
    result = CapabilityResult(
        recommendations=(
            CapabilityRecommendation(
                kind="skill",
                name="skill_review",
                description="Review code changes",
                score=0.91,
            ),
        )
    )

    runtime_context = RuntimeContextBuilder(capabilities=result).build()
    payload = runtime_context.capabilities

    assert payload is not None
    assert "调用 invoke_skill" in payload["skill_recommendation_usage"]
    recommendation = payload["recommendations"][0]
    assert recommendation["skill_name"] == "skill_review"
    assert recommendation["recommended_action"] == "invoke_skill"
    assert recommendation["invoke_tool"] == "invoke_skill"


def test_capability_router_uses_skill_runtime_recommendations():
    class FakeSkillRuntime:
        router_retrieval_top_k = 10

        def __init__(self):
            self.called = False
            self.record = SkillRecord(
                name="Review",
                tool_name="skill_review",
                description="Review code changes",
                content="",
                source_path=Path("skills/review/SKILL.md"),
                content_hash="hash",
                updated_at=0.0,
            )
            self.records = {self.record.tool_name: self.record}

        def recommend_records_for_capability(self, query, *, top_k):
            self.called = True
            return [
                SearchResult(
                    record=self.record,
                    score=0.8,
                    keyword_score=0.0,
                    semantic_score=0.0,
                    metadata={"router_source": "skill_router"},
                )
            ]

        def search_records_for_capability(self, query, *, top_k):
            raise AssertionError("CapabilityRouter should prefer recommend_records_for_capability")

    runtime = FakeSkillRuntime()
    result = asyncio.run(CapabilityRouter(skill_runtime=runtime).route("review this patch"))

    assert runtime.called is True
    recommendation = result.recommendations[0]
    assert recommendation.kind == "skill"
    assert recommendation.name == "skill_review"
    assert recommendation.reasons == ("Skill 路由匹配",)
    assert recommendation.metadata["router_source"] == "skill_router"


def test_mcp_config_loader_merges_user_project_and_env(tmp_path, monkeypatch):
    user_config = tmp_path / "user.json"
    project_config = tmp_path / "project.json"
    env_config = tmp_path / "env.json"
    user_config.write_text(
        json.dumps(
            {
                "servers": {
                    "github": {
                        "command": "user-gh",
                        "description": "user github",
                        "aliases": ["gh"],
                    },
                    "slack": {"command": "slack"},
                }
            }
        ),
        encoding="utf-8",
    )
    project_config.write_text(
        json.dumps({"servers": {"github": {"command": "project-gh", "tags": ["repo"]}}}),
        encoding="utf-8",
    )
    env_config.write_text(
        json.dumps({"servers": {"notion": {"command": "notion", "keywords": ["文档"]}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MYCODINGAGENT_MCP_CONFIG", str(env_config))

    loader = MCPConfigLoader(project_path=project_config, user_path=user_config)
    servers = loader.load()

    assert sorted(servers) == ["github", "notion", "slack"]
    assert servers["github"].command == "project-gh"
    assert servers["github"].tags == ("repo",)
    assert servers["notion"].keywords == ("文档",)


def test_mcp_config_supports_streamable_http_and_fail_closed_defaults(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "servers": {
                    "remote": {
                        "transport": "streamable_http",
                        "url": "https://example.test/mcp",
                        "headers": {"Authorization": "Bearer secret"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    server = MCPConfigLoader(project_path=config, user_path=tmp_path / "missing").load()["remote"]

    assert server.transport == "streamable_http"
    assert server.url.endswith("/mcp")
    assert server.permissions.readonly_by_default is False


def test_mcp_config_loads_browser_container_options(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "servers": {
                    "playwright": {
                        "sandbox": True,
                        "image": "mcr.microsoft.com/playwright/mcp",
                        "image_entrypoint": True,
                        "auto_start": True,
                        "network": True,
                        "init": True,
                        "shm_size": "1g",
                        "cpus": "2",
                        "memory": "2g",
                        "pids_limit": "512",
                        "container_user": "image",
                        "extra_hosts": ["host.docker.internal:host-gateway"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    server = MCPConfigLoader(project_path=config, user_path=tmp_path / "missing").load()["playwright"]

    assert server.init is True
    assert server.shm_size == "1g"
    assert server.memory == "2g"
    assert server.image_entrypoint is True
    assert server.auto_start is True
    assert server.container_user == "image"
    assert server.extra_hosts == ("host.docker.internal:host-gateway",)


def test_mcp_sandbox_args_include_browser_resources_and_no_forced_user():
    manager = MCPClientManager()
    config = MCPServerConfig(
        name="playwright",
        args=("--headless",),
        sandbox=True,
        image="mcr.microsoft.com/playwright/mcp",
        image_entrypoint=True,
        network=True,
        init=True,
        shm_size="1g",
        cpus="3",
        memory="2g",
        pids_limit="512",
        container_user="image",
        extra_hosts=("host.docker.internal:host-gateway",),
    )

    args = manager._sandboxed_stdio_args(config)

    assert args[:3] == ["run", "--rm", "-i"]
    assert args[args.index("--network"):args.index("--network") + 2] == ["--network", "none"]
    assert "--init" in args
    assert args[args.index("--shm-size"):args.index("--shm-size") + 2] == ["--shm-size", "1g"]
    assert args[args.index("--memory"):args.index("--memory") + 2] == ["--memory", "2g"]
    assert args[args.index("--add-host"):args.index("--add-host") + 2] == [
        "--add-host",
        "host.docker.internal:host-gateway",
    ]
    assert "--user" not in args
    assert args[-2:] == ["mcr.microsoft.com/playwright/mcp", "--headless"]


def test_playwright_output_mount_is_runtime_specific_and_forces_output_dir(tmp_path):
    output_dir = tmp_path / ".mycodingagent" / "artifacts" / "playwright" / "runtime-a"
    output_dir.mkdir(parents=True)
    manager = MCPClientManager(playwright_output_dir=output_dir, workspace_root=tmp_path)
    config = MCPServerConfig(
        name="playwright",
        args=("--headless",),
        sandbox=True,
        image="mcr.microsoft.com/playwright/mcp",
        image_entrypoint=True,
        network=True,
        container_user="image",
    )

    args = manager._sandboxed_stdio_args(config)

    assert ["--volume", f"{output_dir.resolve()}:/mycodingagent-output:rw"] == args[
        args.index("--volume"):args.index("--volume") + 2
    ]
    assert ["--workdir", "/mycodingagent-output"] == args[
        args.index("--workdir"):args.index("--workdir") + 2
    ]
    assert args[-3:] == ["--headless", "--output-dir", "/mycodingagent-output"]


def test_playwright_outputs_only_include_current_runtime_and_call(tmp_path):
    first_dir = tmp_path / ".mycodingagent" / "artifacts" / "playwright" / "runtime-a"
    second_dir = tmp_path / ".mycodingagent" / "artifacts" / "playwright" / "runtime-b"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    (first_dir / "existing.png").write_bytes(b"old")
    (second_dir / "foreign.png").write_bytes(b"foreign")
    manager = MCPClientManager(playwright_output_dir=first_dir, workspace_root=tmp_path)
    before = manager._playwright_output_snapshot()
    (first_dir / "current.png").write_bytes(b"new")
    result = MCPExecutionResult(
        server="playwright",
        operation="tool",
        name="browser_take_screenshot",
        content_text="done",
    )

    attached = manager._attach_playwright_outputs(result, before)

    outputs = attached.metadata["runtime_outputs"]
    assert [item["path"] for item in outputs] == [
        ".mycodingagent/artifacts/playwright/runtime-a/current.png"
    ]
    assert "existing.png" not in attached.content_text
    assert "foreign.png" not in attached.content_text


@pytest.mark.parametrize("value", ["/tmp/out.png", "../out.png", "nested/../../out.png"])
def test_playwright_rejects_outputs_outside_runtime_directory(value):
    assert _validate_playwright_output_arguments({"filename": value})


def test_playwright_accepts_relative_output_paths():
    assert _validate_playwright_output_arguments({"filename": "screens/current.png"}) == ""


def test_playwright_creates_nested_output_parent_inside_runtime_directory(tmp_path):
    output_dir = tmp_path / ".mycodingagent" / "artifacts" / "playwright" / "runtime-a"
    output_dir.mkdir(parents=True)
    manager = MCPClientManager(playwright_output_dir=output_dir, workspace_root=tmp_path)

    manager._prepare_playwright_output_parents({"filename": "screens/current.png"})

    assert (output_dir / "screens").is_dir()


def test_network_policy_blocks_github_but_keeps_browser_for_localhost():
    access = NetworkAccessRuntime(enabled=False)

    assert not access.allows_mcp(MCPServerConfig(name="github", command="docker"))
    assert access.allows_mcp(
        MCPServerConfig(name="playwright", command="node", network=True)
    )
    assert access.allows_mcp(
        MCPServerConfig(
            name="local",
            transport="streamable_http",
            url="http://localhost:9000/mcp",
        )
    )


def test_manager_rejects_external_mcp_before_connecting():
    manager = MCPClientManager(network_access=NetworkAccessRuntime(enabled=False))
    manager.server_configs["github"] = MCPServerConfig(name="github", command="docker")

    with pytest.raises(PermissionError, match="智能搜索已关闭"):
        asyncio.run(manager._ensure_session("github"))


def test_public_streamable_http_mcp_requires_managed_network():
    manager = MCPClientManager(network_access=NetworkAccessRuntime(enabled=True))
    manager.server_configs["remote"] = MCPServerConfig(
        name="remote",
        transport="streamable_http",
        url="https://example.test/mcp",
        auto_start=True,
    )

    with pytest.raises(RuntimeError, match="远程 MCP 缺少 Runtime 托管网络"):
        asyncio.run(manager._ensure_session("remote"))


def test_local_streamable_http_mcp_does_not_require_managed_network():
    class DenyLaunch:
        async def approve(self, _request):
            return type("Decision", (), {"allowed": False})()

    manager = MCPClientManager(
        network_access=NetworkAccessRuntime(enabled=True),
        launch_hook=DenyLaunch(),
    )
    manager.server_configs["local"] = MCPServerConfig(
        name="local",
        transport="streamable_http",
        url="http://localhost:9000/mcp",
    )

    with pytest.raises(PermissionError, match="MCP Server 启动被拒绝"):
        asyncio.run(manager._ensure_session("local"))


def test_mcp_image_content_is_saved_as_workspace_artifact(tmp_path):
    png = b"\x89PNG\r\n\x1a\nimage"
    item = type(
        "Image",
        (),
        {
            "type": "image",
            "mimeType": "image/png",
            "data": base64.b64encode(png).decode("ascii"),
        },
    )()
    result = type("Result", (), {"isError": False, "content": [item]})()

    normalized = normalize_mcp_result(
        server="playwright",
        operation="tool",
        name="browser_take_screenshot",
        result=result,
        artifact_root=tmp_path / ".mycodingagent" / "artifacts" / "mcp",
        workspace_root=tmp_path,
    )

    artifact = normalized.metadata["artifacts"][0]
    saved = tmp_path / artifact["path"]
    assert saved.read_bytes() == png
    assert artifact["mime_type"] == "image/png"
    assert artifact["path"] in normalized.content_text


def test_invalid_mcp_image_is_not_written(tmp_path):
    item = type(
        "Image",
        (),
        {
            "type": "image",
            "mimeType": "image/png",
            "data": base64.b64encode(b"not-a-png").decode("ascii"),
        },
    )()
    result = type("Result", (), {"isError": False, "content": [item]})()

    normalized = normalize_mcp_result(
        server="playwright",
        operation="tool",
        name="browser_take_screenshot",
        result=result,
        artifact_root=tmp_path / ".mycodingagent" / "artifacts" / "mcp",
        workspace_root=tmp_path,
    )

    assert normalized.metadata["non_text_content"][0]["type"] == "image"
    assert not (tmp_path / ".mycodingagent").exists()


def test_mcp_annotation_overrides_name_heuristic_and_unknown_is_closed():
    policy = MCPToolPermissionPolicy()

    assert policy.classify(
        server_config=None,
        tool_name="get_and_delete",
        tool_metadata={"annotations": {"destructiveHint": True}},
    ) == "destructive"
    assert policy.classify(
        server_config=None,
        tool_name="send_message",
        tool_metadata={"annotations": {"openWorldHint": True}},
    ) == "network"
    assert policy.classify(server_config=None, tool_name="rotate_token") == "admin"
    assert policy.classify(server_config=None, tool_name="delete_repository") == "destructive"
    assert policy.classify(server_config=None, tool_name="custom_action") == "unknown"
    assert policy.requires_approval("unknown") is True


class _Coordinator:
    def __init__(self, answers: list[str]) -> None:
        self.answers = answers
        self.prompts = 0
        self.last_prompt = ""

    async def read_choice(self, prompt: str, *, allowed: set[str]) -> str:
        self.prompts += 1
        self.last_prompt = prompt
        answer = self.answers.pop(0)
        return answer if answer in allowed else ""


def test_mcp_cli_tool_approval_supports_session_always(capsys):
    coordinator = _Coordinator(["a"])
    hook = CLIApprovalHook(coordinator)
    request = type(
        "_Req",
        (),
        {
            "server": "github",
            "tool": "create_issue",
            "risk": "write",
            "intent": "创建 issue",
            "arguments": {"title": "bug"},
        },
    )()

    first = asyncio.run(hook.approve(request))
    second = asyncio.run(hook.approve(request))

    output = capsys.readouterr().out
    assert first.allowed is True
    assert first.reason == "本会话已批准该 MCP 工具"
    assert second.allowed is True
    assert second.reason == "本会话已批准该 MCP 工具"
    assert coordinator.prompts == 1
    assert coordinator.last_prompt == "允许本次 MCP 工具调用吗？[y/N/a]："
    assert "风险：write" in output
    assert hook._always_allowed == {("github", "create_issue", "write")}


def test_capability_router_recommends_mcp_server_by_alias_and_keyword(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "servers": {
                    "github": {
                        "command": "gh-mcp",
                        "description": "GitHub repository operations",
                        "aliases": ["gh"],
                        "keywords": ["代码仓库", "PR"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    router = CapabilityRouter(mcp_manager=manager)

    result = asyncio.run(router.route("帮我看一下 gh 的 PR"))

    assert result.mcp_server_total_count == 1
    assert result.discovery_tools_available is True
    assert [item.name for item in result.recommendations if item.kind == "mcp_server"] == ["github"]


def test_runtime_context_includes_capability_payload(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps({"servers": {"github": {"command": "gh-mcp", "keywords": ["repo"]}}}),
        encoding="utf-8",
    )
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    result = asyncio.run(CapabilityRouter(mcp_manager=manager).route("repo status"))

    runtime_context = RuntimeContextBuilder(capabilities=result).build()
    rendered = PromptRenderer.render_current_user_message(runtime_context, "repo status")

    assert runtime_context.capabilities is not None
    assert runtime_context.capabilities["mcp_server_total_count"] == 1
    assert '"recommendations_are_restrictions": false' in rendered.runtime_context_json
    assert '"mcp_tool_intent_required": true' in rendered.runtime_context_json
    assert '"mcp_read_tool_calls_auto_allowed": true' in rendered.runtime_context_json
    assert '"mcp_write_tool_calls_require_approval": true' in rendered.runtime_context_json
    assert '"mcp_approval_required_for_non_read": true' in rendered.runtime_context_json


def test_discovery_tool_schema_is_stable_when_servers_change(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    second.write_text(
        json.dumps({"servers": {"github": {"command": "gh-mcp"}, "slack": {"command": "slack-mcp"}}}),
        encoding="utf-8",
    )

    registry = ToolRegistry()
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=first, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    router = CapabilityRouter(mcp_manager=manager)
    register_mcp_discovery_tools(registry, manager=manager, router=router)
    initial_names = [schema["name"] for schema in registry.get_all_schemas("openai")]

    manager.config_loader = MCPConfigLoader(project_path=second, user_path=tmp_path / "missing.json")
    manager.reload_config()
    later_names = [schema["name"] for schema in registry.get_all_schemas("openai")]

    assert initial_names == later_names
    assert "list_mcp_tools" in initial_names
    assert "search_mcp_servers" in initial_names
    assert "search_tools" not in initial_names
    assert len(initial_names) == 8


def test_skill_and_mcp_search_tool_names_are_unambiguous(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    registry = ToolRegistry()
    registry.register(SearchSkillTool(object()))
    register_mcp_discovery_tools(
        registry,
        manager=manager,
        router=CapabilityRouter(mcp_manager=manager),
    )

    names = {schema["name"] for schema in registry.get_all_schemas("openai")}

    assert "search_skill" in names
    assert "search_mcp_tools" in names
    assert "search_tools" not in names


def test_mcp_metadata_cache_invalidates_when_server_config_changes(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps({"servers": {"github": {"command": "gh-v1"}}}), encoding="utf-8")
    second.write_text(json.dumps({"servers": {"github": {"command": "gh-v2"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=first, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    manager.metadata_cache.update_discovery(
        "github",
        tools=[MCPItemSummary(name="old_tool")],
        connected=True,
    )

    manager.config_loader = MCPConfigLoader(project_path=second, user_path=tmp_path / "missing.json")
    manager.reload_config()
    entry = manager.metadata_cache.get("github")

    assert entry is not None
    assert entry.config.command == "gh-v2"
    assert entry.tools == []
    assert entry.updated_at == 0.0


def test_mcp_discovery_retries_unavailable_server_on_model_probe(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    manager.metadata_cache.mark_error("github", "temporary failure")

    calls = 0

    async def fake_refresh(server):
        nonlocal calls
        calls += 1
        manager.metadata_cache.update_discovery(
            server,
            tools=[MCPItemSummary(name="fresh_tool")],
            connected=True,
            error="",
        )
        return manager.metadata_cache.get(server).summary()

    manager.refresh_server = fake_refresh
    result = asyncio.run(manager.list_tools("github"))

    assert calls == 1
    assert result["server"]["available"] is True
    assert result["tools"][0]["name"] == "fresh_tool"


def test_mcp_discovery_keeps_server_unavailable_after_failed_model_probe(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    manager.metadata_cache.mark_error("github", "temporary failure")
    calls = 0

    async def fake_refresh(server):
        nonlocal calls
        calls += 1
        manager.metadata_cache.mark_error(server, "still unavailable")
        return manager.metadata_cache.get(server).summary()

    manager.refresh_server = fake_refresh
    result = asyncio.run(manager.list_tools("github"))

    assert calls == 1
    assert result["error"] == "MCP Server 不可用：still unavailable"
    assert result["server"]["available"] is False
    assert result["tools"] == []


def test_mcp_reconnect_unavailable_servers_restores_available_state(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    manager.metadata_cache.mark_error("github", "temporary failure")
    calls = 0

    async def fake_refresh(server):
        nonlocal calls
        calls += 1
        manager.metadata_cache.update_discovery(
            server,
            tools=[MCPItemSummary(name="fresh_tool")],
            connected=True,
            error="",
        )
        return manager.metadata_cache.get(server).summary()

    manager.refresh_server = fake_refresh
    restored = asyncio.run(manager.reconnect_unavailable_servers())
    result = asyncio.run(manager.list_tools("github"))

    assert calls == 1
    assert [item.name for item in restored] == ["github"]
    assert result["server"]["available"] is True
    assert result["tools"][0]["name"] == "fresh_tool"


def test_mcp_execution_does_not_probe_unavailable_server(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    manager.metadata_cache.mark_error("github", "temporary failure")

    async def fail_if_called(server):
        raise AssertionError("execution should not reconnect unavailable servers directly")

    manager._ensure_session = fail_if_called
    result = asyncio.run(manager.call_tool("github", "get_status", {}))

    assert result.is_error is True
    assert result.content_text == "MCP Server 不可用：temporary failure"


def test_search_mcp_tools_uses_cached_discovery_metadata(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    manager.metadata_cache.update_discovery(
        "github",
        tools=[MCPItemSummary(name="create_pull_request", description="Create a GitHub pull request")],
        connected=True,
    )

    registry = ToolRegistry()
    router = CapabilityRouter(mcp_manager=manager)
    register_mcp_discovery_tools(registry, manager=manager, router=router)
    tool = registry.get("search_mcp_tools")
    result = asyncio.run(tool.execute(tool.params_model(server="github", query="pull request")))
    payload = json.loads(result.output)

    assert payload["count"] == 1
    assert payload["offset"] == 0
    assert payload["limit"] == 20
    assert payload["has_more"] is False
    assert payload["tools"][0]["name"] == "create_pull_request"
    assert manager.discovery_gate.allows(
        "github", "create_pull_request", manager.cached_tool_payload("github", "create_pull_request")
    )


def test_mcp_discovery_tools_use_offset_limit_pagination(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    manager.metadata_cache.update_discovery(
        "github",
        tools=[
            MCPItemSummary(name="a_read_tool"),
            MCPItemSummary(name="b_read_tool"),
            MCPItemSummary(name="c_read_tool"),
        ],
        connected=True,
    )

    registry = ToolRegistry()
    router = CapabilityRouter(mcp_manager=manager)
    register_mcp_discovery_tools(registry, manager=manager, router=router)
    tool = registry.get("list_mcp_tools")
    result = asyncio.run(tool.execute(tool.params_model(server="github", offset=1, limit=1)))
    payload = json.loads(result.output)

    assert payload["count"] == 1
    assert payload["total"] == 3
    assert payload["offset"] == 1
    assert payload["limit"] == 1
    assert payload["has_more"] is True
    assert payload["next_offset"] == 2
    assert [item["name"] for item in payload["tools"]] == ["b_read_tool"]
    assert manager.discovery_gate.allows(
        "github", "b_read_tool", manager.cached_tool_payload("github", "b_read_tool")
    )
    assert not manager.discovery_gate.allows(
        "github", "a_read_tool", manager.cached_tool_payload("github", "a_read_tool")
    )


def test_mcp_client_discovers_real_stdio_server_metadata(tmp_path):
    server_script = tmp_path / "fake_mcp_server.py"
    server_script.write_text(
        """
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fake")

@mcp.tool(description="Create a fake issue")
def create_issue(title: str) -> str:
    return title

@mcp.resource("fake://status", description="Fake status resource")
def fake_status() -> str:
    return "ok"

@mcp.prompt(description="Fake review prompt")
def review_prompt(topic: str) -> str:
    return f"Review {topic}"

if __name__ == "__main__":
    mcp.run("stdio")
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "servers": {
                    "fake": {
                        "command": sys.executable,
                        "args": [str(server_script)],
                        "description": "Fake MCP server",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))

    async def scenario():
        await manager.initialize()
        tools = await manager.list_tools("fake")
        resources = await manager.list_resources("fake")
        prompts = await manager.list_prompts("fake")
        await manager.close()
        return tools, resources, prompts

    tools, resources, prompts = asyncio.run(scenario())

    assert tools["server"]["available"] is True
    assert "connected" not in tools["server"]
    assert [item["name"] for item in tools["tools"]] == ["create_issue"]
    assert [item["name"] for item in resources["resources"]] == ["fake://status"]
    assert [item["name"] for item in prompts["prompts"]] == ["review_prompt"]


def test_mcp_execution_tools_call_real_stdio_server_and_include_intent(tmp_path):
    class FailOnApprovalHook(MCPToolApprovalHook):
        async def approve(self, request):
            raise AssertionError("read MCP tools should not require approval")

    server_script = tmp_path / "fake_mcp_server.py"
    server_script.write_text(
        """
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fake")

@mcp.tool(description="Read fake status")
def get_status() -> str:
    return "ok"

@mcp.resource("fake://status", description="Fake status resource")
def fake_status() -> str:
    return "resource-ok"

@mcp.prompt(description="Fake review prompt")
def review_prompt(topic: str) -> str:
    return f"Review {topic}"

if __name__ == "__main__":
    mcp.run("stdio")
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps({"servers": {"fake": {"command": sys.executable, "args": [str(server_script)]}}}),
        encoding="utf-8",
    )
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    registry = ToolRegistry()

    async def scenario():
        await manager.initialize()
        register_mcp_discovery_tools(
            registry,
            manager=manager,
            router=CapabilityRouter(mcp_manager=manager),
        )
        register_mcp_execution_tools(
            registry,
            manager=manager,
            policy=MCPToolPermissionPolicy(),
            approval_hook=FailOnApprovalHook(),
        )
        call_tool = registry.get("call_mcp_tool")
        list_tools = registry.get("list_mcp_tools")
        read_resource = registry.get("read_mcp_resource")
        get_prompt = registry.get("get_mcp_prompt")
        await list_tools.execute(list_tools.params_model(server="fake"))
        call_result = await call_tool.execute(
            call_tool.params_model(server="fake", tool="get_status", arguments={}, intent="检查 fake 状态")
        )
        resource_result = await read_resource.execute(
            read_resource.params_model(server="fake", uri="fake://status", intent="读取 fake 资源")
        )
        prompt_result = await get_prompt.execute(
            get_prompt.params_model(server="fake", prompt="review_prompt", arguments={"topic": "MCP"}, intent="获取 review prompt")
        )
        await manager.close()
        return call_result, resource_result, prompt_result

    call_result, resource_result, prompt_result = asyncio.run(scenario())
    call_payload = json.loads(call_result.output)
    resource_payload = json.loads(resource_result.output)
    prompt_payload = json.loads(prompt_result.output)

    assert call_result.is_error is False
    assert call_payload["intent"] == "检查 fake 状态"
    assert call_payload["risk"] == "read"
    assert call_payload["approval"] == "auto_allowed_read"
    assert "ok" in call_payload["content_text"]
    assert resource_result.is_error is False
    assert resource_payload["mcp_resource"] == "fake://status"
    assert "resource-ok" in resource_payload["content_text"]
    assert prompt_result.is_error is False
    assert prompt_payload["mcp_prompt"] == "review_prompt"
    assert "MCP" in prompt_payload["content_text"]


def test_mcp_tool_argument_error_does_not_mark_server_unavailable(tmp_path):
    server_script = tmp_path / "fake_mcp_server.py"
    server_script.write_text(
        """
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fake")

@mcp.tool(description="Search fake repositories")
def search_repositories(query: str) -> str:
    return f"result:{query}"

if __name__ == "__main__":
    mcp.run("stdio")
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps({"servers": {"fake": {"command": sys.executable, "args": [str(server_script)]}}}),
        encoding="utf-8",
    )
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))

    async def scenario():
        await manager.initialize()
        bad_result = await manager.call_tool("fake", "search_repositories", {})
        after_bad = next(server for server in manager.list_servers() if server.name == "fake")
        good_result = await manager.call_tool("fake", "search_repositories", {"query": "react"})
        after_good = next(server for server in manager.list_servers() if server.name == "fake")
        await manager.close()
        return bad_result, after_bad, good_result, after_good

    bad_result, after_bad, good_result, after_good = asyncio.run(scenario())

    assert bad_result.is_error is True
    assert "query" in bad_result.content_text
    assert after_bad.available is True
    assert after_bad.error == ""
    assert good_result.is_error is False
    assert "result:react" in good_result.content_text
    assert after_good.available is True


def test_mcp_write_tool_requires_approval_and_returns_user_denied(tmp_path):
    class DenyHook(MCPToolApprovalHook):
        async def approve(self, request):
            return MCPApprovalDecision(allowed=False, reason="user_denied")

    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    manager.metadata_cache.update_discovery(
        "github",
        tools=[MCPItemSummary(name="create_issue", description="Create an issue")],
        connected=True,
    )
    registry = ToolRegistry()
    register_mcp_discovery_tools(
        registry,
        manager=manager,
        router=CapabilityRouter(mcp_manager=manager),
    )
    register_mcp_execution_tools(
        registry,
        manager=manager,
        policy=MCPToolPermissionPolicy(),
        approval_hook=DenyHook(),
    )

    async def scenario():
        list_tools = registry.get("list_mcp_tools")
        await list_tools.execute(list_tools.params_model(server="github"))
        tool = registry.get("call_mcp_tool")
        return await tool.execute(
            tool.params_model(
                server="github",
                tool="create_issue",
                arguments={"title": "blocked"},
                intent="尝试创建 issue",
            )
        )

    result = asyncio.run(scenario())

    assert result.is_error is True
    assert result.output == USER_DENIED_MESSAGE


def test_mcp_tool_call_requires_model_visible_discovery(tmp_path):
    class FailOnApprovalHook(MCPToolApprovalHook):
        async def approve(self, request):
            raise AssertionError("发现门禁失败时不应进入审批")

    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    manager.metadata_cache.update_discovery(
        "github",
        tools=[MCPItemSummary(name="get_status", description="Read status")],
        connected=True,
    )
    registry = ToolRegistry()
    register_mcp_execution_tools(
        registry,
        manager=manager,
        policy=MCPToolPermissionPolicy(),
        approval_hook=FailOnApprovalHook(),
    )
    tool = registry.get("call_mcp_tool")

    result = asyncio.run(
        tool.execute(
            tool.params_model(server="github", tool="get_status", arguments={}, intent="读取状态")
        )
    )
    payload = json.loads(result.output)

    assert result.is_error is True
    assert payload["error_code"] == "mcp_tool_not_discovered"
    assert payload["required_discovery"][0]["tool"] == "search_mcp_tools"
    assert payload["required_discovery"][0]["arguments"] == {"server": "github", "query": "get_status"}


def test_mcp_discovery_gate_invalidates_changed_metadata_and_config_reload(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    original = MCPItemSummary(name="get_status", description="Read status").to_payload()
    changed = MCPItemSummary(name="get_status", description="Read detailed status").to_payload()

    manager.discovery_gate.record_tools("github", [original])

    assert manager.discovery_gate.allows("github", "get_status", original)
    assert not manager.discovery_gate.allows("github", "get_status", changed)

    manager.reload_config()

    assert not manager.discovery_gate.allows("github", "get_status", original)


def test_mcp_tool_call_requires_rediscovery_when_live_metadata_changes(tmp_path, monkeypatch):
    class FailOnApprovalHook(MCPToolApprovalHook):
        async def approve(self, request):
            raise AssertionError("metadata 变化时不应进入审批")

    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    original = MCPItemSummary(name="get_status", description="Read status")
    changed = MCPItemSummary(name="get_status", description="Read detailed status")
    manager.metadata_cache.update_discovery("github", tools=[original], connected=True)
    manager.discovery_gate.record_tools("github", [original.to_payload()])

    async def change_live_metadata(server, tool):
        manager.metadata_cache.update_discovery("github", tools=[changed], connected=True)
        return dict(changed.metadata)

    monkeypatch.setattr(manager, "live_tool_metadata", change_live_metadata)
    registry = ToolRegistry()
    register_mcp_execution_tools(
        registry,
        manager=manager,
        policy=MCPToolPermissionPolicy(),
        approval_hook=FailOnApprovalHook(),
    )
    tool = registry.get("call_mcp_tool")

    result = asyncio.run(
        tool.execute(tool.params_model(server="github", tool="get_status", arguments={}, intent="读取状态"))
    )
    payload = json.loads(result.output)

    assert result.is_error is True
    assert payload["error_code"] == "mcp_tool_metadata_changed"
