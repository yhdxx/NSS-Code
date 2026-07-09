from __future__ import annotations

import asyncio
import json
import sys

from capabilities import CapabilityRouter
from mcp_client.hooks import MCPToolApprovalHook, USER_DENIED_MESSAGE
from mcp_client import MCPClientManager, MCPConfigLoader
from mcp_client.models import MCPItemSummary
from mcp_client.policy import MCPApprovalDecision, MCPToolPermissionPolicy
from runtime_context import PromptRenderer, RuntimeContextBuilder
from tools import ToolRegistry
from tools.mcp_discovery import register_mcp_discovery_tools
from tools.mcp_execution import register_mcp_execution_tools


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
    assert "list_tools" in initial_names
    assert "search_servers" in initial_names
    assert len(initial_names) == 8


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


def test_mcp_discovery_retries_after_cached_error(tmp_path):
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
    assert result["tools"][0]["name"] == "fresh_tool"


def test_search_tools_uses_cached_discovery_metadata(tmp_path):
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
    tool = registry.get("search_tools")
    result = asyncio.run(tool.execute(tool.params_model(server="github", query="pull request")))
    payload = json.loads(result.output)

    assert payload["count"] == 1
    assert payload["offset"] == 0
    assert payload["limit"] == 20
    assert payload["has_more"] is False
    assert payload["tools"][0]["name"] == "create_pull_request"


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
    tool = registry.get("list_tools")
    result = asyncio.run(tool.execute(tool.params_model(server="github", offset=1, limit=1)))
    payload = json.loads(result.output)

    assert payload["count"] == 1
    assert payload["total"] == 3
    assert payload["offset"] == 1
    assert payload["limit"] == 1
    assert payload["has_more"] is True
    assert payload["next_offset"] == 2
    assert [item["name"] for item in payload["tools"]] == ["b_read_tool"]


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

    assert tools["server"]["connected"] is True
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
        register_mcp_execution_tools(
            registry,
            manager=manager,
            policy=MCPToolPermissionPolicy(),
            approval_hook=FailOnApprovalHook(),
        )
        call_tool = registry.get("call_tool")
        read_resource = registry.get("read_resource")
        get_prompt = registry.get("get_prompt")
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


def test_mcp_write_tool_requires_approval_and_returns_user_denied(tmp_path):
    class DenyHook(MCPToolApprovalHook):
        async def approve(self, request):
            return MCPApprovalDecision(allowed=False, reason="user_denied")

    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"github": {"command": "gh-mcp"}}}), encoding="utf-8")
    manager = MCPClientManager(config_loader=MCPConfigLoader(project_path=config, user_path=tmp_path / "missing.json"))
    asyncio.run(manager.initialize())
    registry = ToolRegistry()
    register_mcp_execution_tools(
        registry,
        manager=manager,
        policy=MCPToolPermissionPolicy(),
        approval_hook=DenyHook(),
    )

    tool = registry.get("call_tool")
    result = asyncio.run(
        tool.execute(
            tool.params_model(
                server="github",
                tool="create_issue",
                arguments={"title": "blocked"},
                intent="尝试创建 issue",
            )
        )
    )

    assert result.is_error is True
    assert result.output == USER_DENIED_MESSAGE
