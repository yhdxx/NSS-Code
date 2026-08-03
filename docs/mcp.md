# myCodingAgent MCP 配置说明

首次启动 `myAgent` 时会自动创建：

- 用户级配置：`~/.mycodingagent/mcp.json`
- 本说明文件：`~/.mycodingagent/MCP.md`

已有且格式有效的 `mcp.json` 不会被覆盖。配置文件不是合法 JSON 对象时，启动引导会先生成带时间戳的备份，再恢复模板。

## 配置加载顺序

```text
~/.mycodingagent/mcp.json
  -> 当前工作目录/.mycodingagent/mcp.json
  -> MYCODINGAGENT_MCP_CONFIG 指定的文件
```

后加载的同名 Server 覆盖先加载的配置。所有配置都可以使用顶层 `servers` 对象：

```json
{
  "servers": {
    "server-name": {
      "disabled": false,
      "transport": "stdio",
      "command": "executable",
      "args": [],
      "env": {}
    }
  }
}
```

## GitHub MCP

模板使用 GitHub 官方 MCP Server Docker 镜像。先创建 GitHub Personal Access Token，然后在启动 `myAgent` 的同一个 shell 中设置：

```bash
export GITHUB_PERSONAL_ACCESS_TOKEN="github_pat_..."
```

编辑 `~/.mycodingagent/mcp.json`，把 `servers.github.disabled` 改为 `false`：

```json
{
  "servers": {
    "github": {
      "disabled": false,
      "transport": "stdio",
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "-e",
        "GITHUB_TOOLSETS=repos,issues,pull_requests",
        "ghcr.io/github/github-mcp-server"
      ],
      "description": "GitHub 仓库、Issue、PR 和代码搜索操作",
      "tags": ["github", "git", "repo"],
      "startup_timeout": 30,
      "call_timeout": 60
    }
  }
}
```

重新启动后，启动日志应显示 `已配置 MCP Server：1 个`。首次连接 Server 时仍会显示启动审批。

不要把真实 Token 提交到项目仓库。用户级配置支持 `env` 字段，但敏感值更适合通过 shell 环境变量提供。

## Server 字段

| 字段 | 说明 |
|------|------|
| `disabled` | `true` 时忽略该 Server |
| `transport` | `stdio` 或 `streamable_http` |
| `command` / `args` | `stdio` Server 的启动命令和参数 |
| `env` | 追加到 Server 进程的环境变量 |
| `url` / `headers` | Streamable HTTP 地址和请求头 |
| `startup_timeout` | 初始化超时秒数 |
| `call_timeout` | 单次 MCP 调用超时秒数 |
| `description` | 能力发现使用的说明 |
| `tags` / `aliases` / `keywords` | 能力检索关键词 |
| `sandbox` | 是否把 stdio Server 放进 Docker 沙箱 |
| `workspace_access` | `none`、`read` 或 `write` |
| `network` | 沙箱 Server 是否允许网络访问 |
| `permissions` | read/write/dangerous 工具分级 |

远程 Server 示例和完整权限字段可以直接查看 `~/.mycodingagent/mcp.json` 中保留的禁用模板。
