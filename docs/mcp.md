# myCodingAgent MCP 配置说明

首次启动 `myAgent` 时会自动创建：

- 用户级配置：`~/.mycodingagent/mcp.json`
- 本说明文件：`~/.mycodingagent/MCP.md`

已有且格式有效的 `mcp.json` 不会被覆盖；每次启动只会追加模板中缺失的内置 Server。同名 Server 和所有用户自定义
Server 均原样保留。配置文件不是合法 JSON 对象时，启动引导会先生成带时间戳的备份，再恢复模板。

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

## Playwright MCP + Headless Chromium

Playwright MCP 已包含 Headless Chromium，不需要再配置第二个 Chromium MCP。先安装网页能力：

启动时会先从当前 Playwright 镜像获取 `tools/list`，把全部工具以原始名称（例如 `browser_navigate`、
`browser_snapshot`、`browser_take_screenshot`）直接注册进模型 Tool Schema，并打印实际数量。模型不需要再走
Playwright 的 MCP discovery；容器仅是本地的 Playwright 协议实现，模型侧只看到普通 Tool。

```bash
bash scripts/install.sh --with-web-tools
```

`playwright` 是默认启用的内置 Server；若你的既有 `mcp.json` 缺少它，下一次启动会自动追加。关键配置如下：

```json
{
  "servers": {
    "playwright": {
      "disabled": false,
      "transport": "stdio",
      "sandbox": true,
      "image": "mcr.microsoft.com/playwright/mcp",
      "image_entrypoint": true,
      "args": [
        "--headless",
        "--browser", "chromium",
        "--isolated",
        "--no-sandbox"
      ],
      "network": true,
      "workspace_access": "none",
      "init": true,
      "shm_size": "1g",
      "cpus": "2",
      "memory": "2g",
      "pids_limit": "512",
      "container_user": "image"
    }
  }
}
```

`image_entrypoint=true` 表示使用官方镜像自带的启动入口，`args` 只传 Playwright MCP 参数。该容器不挂载
工作区，且处于当前会话的 internal 网络，公网只能经过 Runtime 托管代理。验证当前项目 UI 时可直接访问
`http://localhost:<port>`，Runtime 会映射到当前会话工作区容器；也兼容
`http://mycodingagent-devserver:<port>`。`browser_file_upload`、
`browser_evaluate` 等高风险工具仍按 MCP 审批策略处理。

执行 `/search` 并关闭智能搜索后，Runtime 会拒绝 GitHub 和其他公网 MCP，并取消活动公网隧道。Playwright 保持
可用，但其公网请求会被代理拒绝，只能访问当前会话的 `localhost:<port>` 开发服务。指向本机回环地址的
Streamable HTTP MCP 也仍允许连接。

Playwright 截图、PDF 等输出会写入当前工作区
`.mycodingagent/artifacts/playwright/<runtime-id>/`，工具结果返回工作区相对路径，可继续交给 `AnalyzeImage` 做图片
理解或多图比较。每个 Runtime 只挂载自己的输出目录，绝对路径和包含 `..` 的路径会被拒绝，避免跨会话取错文件。
其他 MCP 图片仍保存在 `.mycodingagent/artifacts/mcp/<server>/`。这些目录属于运行 artifact，默认被 Git 忽略，
也不进入项目图谱。

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
| `image` | 沙箱 Server 使用的 Docker 镜像 |
| `image_entrypoint` | 是否直接使用镜像 ENTRYPOINT；为 `true` 时不追加 `command` |
| `auto_start` | `true` 时跳过 MCP Server 启动审批；Playwright 未显式设置该字段时默认启用，写为 `false` 可恢复每次审批 |
| `workspace_access` | `none`、`read` 或 `write` |
| `network` | 沙箱 Server 是否允许网络访问 |
| `init` | 是否向 `docker run` 传入 `--init` |
| `shm_size` | 容器共享内存大小，例如 Chromium 推荐的 `1g` |
| `cpus` / `memory` / `pids_limit` | Server 级 CPU、内存和进程数限制；为空时使用全局 Docker 默认值 |
| `container_user` | `host` 使用宿主 UID:GID；`image` 使用镜像默认用户；其他值原样传给 `--user` |
| `extra_hosts` | 追加 Docker `--add-host` 的高级配置；默认 Playwright 不需要主机映射 |
| `permissions` | read/write/dangerous 工具分级 |

远程 Server 示例和完整权限字段可以直接查看 `~/.mycodingagent/mcp.json` 中保留的禁用模板。
