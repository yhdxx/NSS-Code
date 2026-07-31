from __future__ import annotations  # 延迟解析类型注解，允许在运行时更轻量地处理 `Path | None` 等注解。

import asyncio  # 使用异步子进程启动 Docker，并用事件循环等待命令完成或超时。
import os  # 读取环境变量、获取当前用户 UID/GID，保证容器内文件权限和宿主工作区一致。
import shutil  # 检查宿主机是否安装了 docker 可执行文件。
import uuid  # 为每次命令生成唯一容器名，避免并发或残留容器名称冲突。
from pathlib import Path  # 表示并保存宿主机上的沙箱根目录路径。

from pydantic import BaseModel, Field  # 定义并校验 Bash 工具对外暴露的参数 schema。

from mycodingagent.configuration import CONFIG  # 统一读取 Docker 镜像、资源限制和超时配置。
from mycodingagent.tool_runtime.base import Tool, ToolResult, get_sandbox_root  # 复用统一工具基类、返回结构和沙箱根目录解析逻辑。
from mycodingagent.tool_runtime.command_policy import (  # 高危命令分类与用户审批；沙箱之外再加一层不可逆操作保护。
    USER_DENIED_COMMAND_MESSAGE,
    CommandApprovalHook,
    CommandApprovalRequest,
    analyze_command,
)

MAX_TIMEOUT = CONFIG.docker.max_timeout  # 单次命令允许的最大运行秒数；即使调用方传入更大 timeout，也会被截断到该上限。
DEFAULT_DOCKER_IMAGE = CONFIG.docker.image  # 默认执行镜像，提供基础 Python/Bash 环境，同时保持镜像体积较小。
DOCKER_IMAGE_ENV = CONFIG.docker.image_env  # 覆盖执行镜像的环境变量，便于按项目切换到带依赖的镜像。
DOCKER_NETWORK_ENV = CONFIG.docker.network_env  # 控制容器网络模式；默认 none，避免命令随意访问外网。
DOCKER_BUILD_NETWORK_ENV = CONFIG.docker.build_network_env  # 控制 Docker build 阶段网络，便于安装系统包和 Python 依赖。
DOCKER_CPUS_ENV = CONFIG.docker.cpus_env  # 控制 Docker --cpus 参数，限制命令最多使用的 CPU 份额。
DOCKER_MEMORY_ENV = CONFIG.docker.memory_env  # 控制 Docker --memory 参数，防止命令占用过多宿主机内存。
DOCKER_PIDS_LIMIT_ENV = CONFIG.docker.pids_limit_env  # 控制 Docker --pids-limit 参数，限制容器内可创建的进程数量。
DOCKER_CHECK_TIMEOUT = CONFIG.docker.check_timeout  # Docker daemon 和镜像本地检查的最大等待秒数，避免预检阶段长时间挂起。
DOCKER_PULL_TIMEOUT_ENV = CONFIG.docker.pull_timeout_env  # 控制启动阶段拉取镜像允许等待的最长秒数。
DEFAULT_DOCKER_PULL_TIMEOUT = CONFIG.docker.pull_timeout  # 默认允许 Docker pull 等待 30 分钟，适应首次下载 Python 镜像的耗时。
DOCKER_CONFIG_DIRNAME = ".docker-cli"  # Docker CLI 需要可写配置目录；不要默认写入只读 HOME。
LOCAL_SANDBOX_IMAGE_REPOSITORY = "mycodingagent-sandbox"  # 默认本地沙箱镜像仓库名；缺失时从 Dockerfile.sandbox 构建。


def get_docker_image() -> str:  # 返回 Bash 工具统一使用的 Docker 镜像名，启动预拉取和后续执行都走同一来源。
    return CONFIG.docker.image  # 允许用户通过环境变量替换默认镜像。


def get_docker_pull_timeout() -> int:  # 解析启动阶段 Docker pull 的超时时间。
    return CONFIG.docker.pull_timeout  # 默认值足够覆盖多数首次拉取场景。


def docker_subprocess_env() -> dict[str, str]:  # 为所有 Docker CLI 子进程提供稳定、可写的配置目录。
    env = os.environ.copy()
    docker_config = Path(env.get("DOCKER_CONFIG") or get_sandbox_root() / DOCKER_CONFIG_DIRNAME)
    docker_config.mkdir(parents=True, exist_ok=True)
    env["DOCKER_CONFIG"] = str(docker_config)
    return env


class Params(BaseModel):  # Bash 工具的入参模型，会被工具注册表转成可暴露给模型的 JSON Schema。
    command: str = Field(description="Shell command to execute")  # 要交给 `bash -lc` 执行的完整命令字符串，可包含管道、重定向和多行脚本。
    timeout: int = Field(
        default=CONFIG.docker.default_timeout,
        description=f"Timeout in seconds (max {MAX_TIMEOUT})",
    )  # 调用方期望的超时时间；实际执行时会再受 MAX_TIMEOUT 限制。
    intent: str = Field(default="", description="Short intent for this command")  # 基类 schema 会强制要求 intent；这里显式声明，避免校验时被丢弃。


class Bash(Tool):  # 命令执行工具：把 shell 命令放进 Docker 容器运行，和文件读写工具一样受沙箱目录约束。
    name = "Bash"  # 工具注册表和模型 tool_call 使用的公开名称，必须和客户端历史消息中的函数名一致。
    description = (  # 传给模型的工具说明，帮助模型理解该工具适合执行命令而不是直接读写文件。
        "Execute a shell command inside a Docker sandbox and return stdout and stderr. "  # 明确命令运行位置在 Docker 沙箱内部，而非直接在宿主机执行。
        f"The sandbox mounts the agent workspace at {CONFIG.sandbox.docker_workspace_alias}."  # 告诉模型项目根目录在容器内的固定路径，方便生成正确命令。
    )  # 多段字符串在编译期自动拼接成完整描述。
    params_model = Params  # 指定参数校验模型；客户端执行工具前会用它校验模型生成的 JSON 参数。
    category = "command"  # 标记为命令类工具，区别于 ReadFile/Glob/Grep 这类只读工具和 WriteFile/EditFile 写工具。

    def __init__(
        self,
        sandbox_root: Path | None = None,
        approval_hook: CommandApprovalHook | None = None,
    ) -> None:  # 创建工具实例时确定要挂载进容器的宿主机工作区。
        self._sandbox_root = sandbox_root or get_sandbox_root()  # 未显式传入时，使用统一沙箱根目录解析逻辑，通常是启动 agent 的当前目录。
        self._approval_hook = approval_hook  # 为 None 时不做审批，保持非交互场景和既有测试行为不变。


    async def execute(self, params: Params) -> ToolResult:  # 执行一次 Bash 工具调用，并把 stdout/stderr 封装成 ToolResult 返回给模型。
        if shutil.which("docker") is None:  # 先检查宿主环境是否能找到 Docker，避免进入子进程后才得到不清晰的失败信息。
            return ToolResult(output="Error: docker executable not found", is_error=True)  # Docker 不可用时直接返回工具错误，agent 可据此向用户说明环境问题。

        timeout = min(params.timeout, MAX_TIMEOUT)  # 对调用方提供的超时时间做硬上限保护，防止长时间占用 Docker 资源。
        image = get_docker_image()  # 使用和启动预拉取一致的镜像名，确保每次 Bash 调用都进入同一个镜像族。
        docker_error = await self._check_docker_daemon()  # 在真正执行命令前确认 Docker daemon 可访问，优先暴露权限/服务状态问题。
        if docker_error:  # Docker daemon 不可访问时，不继续构造容器命令。
            return ToolResult(output=docker_error, is_error=True)  # 把预检错误直接返回给模型，避免后续 `docker run` 报错更难读。
        image_error = await self._check_image_available(image)  # 确认镜像已经存在本地，避免 `docker run` 自动拉取时卡到命令超时。
        if image_error:  # 镜像不存在或无法检查时，给出可执行的修复提示。
            return ToolResult(output=image_error, is_error=True)  # 返回工具错误，让模型或用户先处理镜像配置。
        if self._approval_hook is not None:
            risk, reason = analyze_command(params.command)
            if risk != "read":
                decision = await self._approval_hook.approve(
                    CommandApprovalRequest(
                        command=params.command,
                        risk=risk,
                        reason=reason or "Command side effects require approval.",
                        intent=str(getattr(params, "intent", "") or ""),
                    )
                )
                if not decision.allowed:
                    return ToolResult(
                        output=f"{USER_DENIED_COMMAND_MESSAGE}：{decision.reason or reason or 'user_denied'}",
                        is_error=True,
                    )
        network = CONFIG.docker.network  # 默认关闭容器网络；需要联网时必须由外部环境显式打开。
        cpus = CONFIG.docker.cpus  # 默认限制为 2 个 CPU，避免编译或测试命令压满宿主机。
        memory = CONFIG.docker.memory  # 默认限制为 1GB 内存，降低失控命令影响整个 agent 进程的风险。
        pids_limit = CONFIG.docker.pids_limit  # 默认限制 256 个进程，防止 fork 型命令耗尽系统进程表。
        container_name = f"mycodingagent-{uuid.uuid4().hex}"  # 每次调用使用独立容器名，便于超时后精准清理对应容器。

        command = [  # 用参数列表而不是拼接字符串启动 Docker，避免宿主 shell 再次解释特殊字符。
            "docker",  # 调用 Docker CLI，由它负责创建隔离容器。
            "run",  # 启动一个一次性容器执行命令。
            "--rm",  # 容器正常退出后自动删除，减少磁盘和容器列表中的残留。
            "--name",  # 显式设置容器名，方便超时场景下通过名称强制删除。
            container_name,  # 本次工具调用专属的容器名。
            "--network",  # 指定容器网络模式。
            network,  # 默认 `none`，也可通过环境变量配置为 bridge/host 等 Docker 支持的模式。
            "--cpus",  # Docker CPU 配额参数。
            cpus,  # CPU 配额值，来自环境变量或默认值。
            "--memory",  # Docker 内存上限参数。
            memory,  # 内存上限值，来自环境变量或默认值。
            "--pids-limit",  # Docker 进程数量上限参数。
            pids_limit,  # 进程数上限，限制容器内可同时存在的 PID 数量。
            "--security-opt",  # Docker 安全选项入口。
            "no-new-privileges",  # 禁止容器内进程通过 setuid 等机制获取新增权限。
            "--cap-drop",  # 移除 Linux capability，减少容器内命令可触达的内核能力。
            "ALL",  # 丢弃全部 capability，使容器权限尽量接近普通用户进程。
            "--user",  # Docker 用户参数；紧随其后的参数会被解释为容器内命令使用的用户身份。
            f"{os.getuid()}:{os.getgid()}",  # 使用宿主当前 UID/GID，避免容器写出的文件变成 root 所有。
            "--volume",  # 挂载宿主目录到容器。
            f"{self._sandbox_root}:{CONFIG.sandbox.docker_workspace_alias}:rw",  # 把 agent 沙箱根目录以读写方式挂载到容器工作区。
            "--workdir",  # 指定容器启动后的工作目录。
            str(CONFIG.sandbox.docker_workspace_alias),  # 命令默认在项目沙箱根目录下执行。
            image,  # 实际运行命令的 Docker 镜像。
            "bash",  # 容器内使用 Bash 解释命令。
            "-lc",  # 以登录 shell 执行命令字符串，支持管道、重定向、条件连接等 Bash 语法和 PATH 查找。
            params.command,  # 模型或调用方传入的原始命令字符串，只在容器内由 Bash 解释。
        ]  # Docker CLI 的完整 argv，后续直接交给 asyncio 子进程执行。

        proc: asyncio.subprocess.Process | None = None
        try:  # 子进程启动、等待和输出收集都放在保护块中，统一转换为工具错误输出。
            proc = await asyncio.create_subprocess_exec(  # 异步启动 Docker CLI，不阻塞 agent 主事件循环。
                *command,  # 将 Docker argv 逐项传入，保持参数边界清晰。
                stdout=asyncio.subprocess.PIPE,  # 捕获标准输出，稍后返回给模型和用户。
                stderr=asyncio.subprocess.PIPE,  # 捕获标准错误，保留测试失败、编译报错等诊断信息。
                env=docker_subprocess_env(),
            )  # 子进程对象保存了 PID、returncode 和 communicate 等控制接口。
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)  # 等待容器命令结束，并在超时时主动中断等待。
        except asyncio.CancelledError:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            await self._force_remove_container(container_name)
            raise
        except asyncio.TimeoutError:  # 命令超过允许时间仍未结束时进入清理路径。
            if proc is not None and proc.returncode is None:
                proc.kill()  # 先终止宿主侧 docker run 进程，避免本地子进程继续占用事件循环资源。
                await proc.wait()  # 等待 docker run 进程退出，回收子进程状态。
            await self._force_remove_container(container_name)  # 再按容器名强制删除容器，处理 Docker 侧仍在运行的情况。
            return ToolResult(output=f"Error: command timed out after {timeout}s", is_error=True)  # 把超时作为工具错误返回，便于模型调整命令。
        except FileNotFoundError:  # 即使前面检查过 docker，也保留竞态兜底，例如 PATH 被修改或二进制被移除。
            return ToolResult(output="Error: docker executable not found", is_error=True)  # 返回和预检查一致的错误文本。
        except Exception as e:  # 捕获 Docker 启动失败、权限问题等其他异常，避免异常冒泡导致 agent 崩溃。
            return ToolResult(output=f"Error executing command: {e}", is_error=True)  # 将异常信息压缩成工具输出交还给模型。

        parts: list[str] = []  # 分段保存 stdout/stderr，只有存在内容时才加入最终输出。
        if stdout:  # Docker 命令产生标准输出时，按独立区块返回。
            parts.append(f"STDOUT:\n{stdout.decode(errors='replace')}")  # 解码失败的字节用替换字符处理，避免二进制或乱码让工具报错。
        if stderr:  # Docker 命令产生标准错误时，保留为独立区块，方便区分正常输出和诊断信息。
            parts.append(f"STDERR:\n{stderr.decode(errors='replace')}")  # 同样使用容错解码，保证错误日志一定能作为文本返回。
        if not parts:  # 命令完全没有输出时，也返回一个显式占位，避免调用方误以为工具结果丢失。
            parts.append("(no output)")  # 明确表示命令执行结束但 stdout/stderr 都为空。

        output = "\n".join(parts)  # 将存在的输出区块拼成最终工具响应文本。
        return ToolResult(output=output, is_error=proc.returncode != 0)  # Docker 返回码非 0 时标记为工具错误，但仍保留 stdout/stderr 供诊断。

    async def ensure_image(self, image: str | None = None) -> ToolResult:  # 启动阶段调用：确保 Bash 执行镜像已经拉取到本地。
        if shutil.which("docker") is None:  # 启动时先确认 Docker CLI 存在。
            return ToolResult(output="Error: docker executable not found", is_error=True)  # 没有 Docker 时直接失败，避免进入对话后才发现 Bash 不可用。

        image = image or get_docker_image()  # 默认使用 Bash 工具后续执行命令时会使用的同一个镜像名。
        docker_error = await self._check_docker_daemon()  # 确认当前用户能访问 Docker daemon。
        if docker_error:  # Docker daemon 不可用或权限不足时，不尝试拉镜像。
            return ToolResult(output=docker_error, is_error=True)  # 返回明确的 Docker 环境错误。

        image_error = await self._check_image_available(image)  # 先检查本地是否已有目标镜像，避免每次启动都拉取。
        if not image_error:  # 镜像已存在，本次启动无需下载。
            bash_error = await self._check_image_supports_bash(image)  # 确认镜像能按 Bash 工具的方式执行 `bash -lc`。
            if bash_error:  # 镜像存在但没有 bash 或入口点不兼容时，启动阶段直接失败。
                return ToolResult(output=bash_error, is_error=True)  # 返回镜像不可用原因。
            return ToolResult(output=f"Docker image ready: {image}")  # 返回启动检查成功信息。

        if self._is_local_sandbox_image(image):  # 默认本地沙箱镜像不是远端镜像，缺失时应从项目 Dockerfile 构建。
            dockerfile = self._find_sandbox_dockerfile()
            if dockerfile is None:
                return ToolResult(
                    output=(
                        f"{image_error}\n"
                        f"Local sandbox image `{image}` is configured, but Dockerfile.sandbox was not found."
                    ),
                    is_error=True,
                )
            build_error = await self._build_image_from_dockerfile(image, dockerfile)
            if build_error:
                return ToolResult(output=build_error, is_error=True)
        else:
            pull_error = await self._pull_image(image)  # 非本地沙箱镜像仍按远端镜像处理，缺失时执行 docker pull。
            if pull_error:  # 拉取失败时直接返回错误，阻止程序继续进入对话。
                return ToolResult(output=pull_error, is_error=True)  # 让用户先修复网络、镜像名或 Docker 权限。

        image_error = await self._check_image_available(image)  # 拉取完成后再检查一次，确认镜像确实可用。
        if image_error:  # 理论上 pull 成功后不应再缺失；保留兜底错误。
            return ToolResult(output=image_error, is_error=True)  # 返回镜像检查失败信息。
        bash_error = await self._check_image_supports_bash(image)  # 拉取成功后验证镜像内 Bash 能正常启动。
        if bash_error:  # 默认镜像被替换成不支持 Bash 的镜像时，在启动阶段给出明确错误。
            return ToolResult(output=bash_error, is_error=True)  # 返回镜像不可执行 Bash 的原因。
        return ToolResult(output=f"Docker image ready: {image}")  # 镜像存在且可供后续 Bash 调用复用。

    def _is_local_sandbox_image(self, image: str) -> bool:  # 判断目标镜像是否应由本项目 Dockerfile.sandbox 构建。
        return image == LOCAL_SANDBOX_IMAGE_REPOSITORY or image.startswith(f"{LOCAL_SANDBOX_IMAGE_REPOSITORY}:")

    def _find_sandbox_dockerfile(self) -> Path | None:  # 优先从当前沙箱根目录查找 Dockerfile，兼容从项目根目录启动。
        candidates = [
            self._sandbox_root / "Dockerfile.sandbox",
            Path(__file__).resolve().parents[2] / "Dockerfile.sandbox",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    async def _build_image_from_dockerfile(self, image: str, dockerfile: Path) -> str:  # 用项目 Dockerfile 构建默认本地沙箱镜像。
        build_timeout = get_docker_pull_timeout()
        context_dir = dockerfile.parent
        command = [
            "docker",
            "build",
            "--progress",
            "plain",
            "--network",
            CONFIG.docker.build_network,
            "-f",
            str(dockerfile),
            "-t",
            image,
            str(context_dir),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=docker_subprocess_env(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=build_timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Error: docker build timed out after {build_timeout}s: {image}"
        except Exception as e:
            return f"Error building docker image {image}: {e}"

        detail = self._decode_output(stdout, stderr)
        if proc.returncode != 0:
            return (
                f"Error: failed to build local sandbox docker image: {image}\n"
                f"Dockerfile: {dockerfile}\n"
                f"Set `{DOCKER_BUILD_NETWORK_ENV}` to a Docker build network mode if package downloads fail.\n"
                f"Docker output:\n{detail}"
            )
        return ""

    async def _check_docker_daemon(self) -> str:  # 检查当前进程是否能访问 Docker daemon；返回空字符串表示可用。
        try:  # Docker daemon 可能未启动、socket 权限不足，或者 docker CLI 自身执行失败。
            proc = await asyncio.create_subprocess_exec(  # 使用轻量 `docker info` 验证客户端能和 daemon 通信。
                "docker",  # Docker CLI。
                "info",  # 查询 Docker daemon 信息；比真正启动容器更便宜。
                "--format",  # 只输出指定字段，减少无关信息。
                "{{.ServerVersion}}",  # 任意能从 daemon 返回的字段即可证明连接可用。
                stdout=asyncio.subprocess.PIPE,  # 捕获版本号输出。
                stderr=asyncio.subprocess.PIPE,  # 捕获权限拒绝、daemon 未启动等错误信息。
                env=docker_subprocess_env(),
            )  # 得到预检子进程对象。
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=DOCKER_CHECK_TIMEOUT)  # 限时等待 Docker 响应。
        except asyncio.TimeoutError:  # Docker daemon 无响应时，避免工具一直卡在预检阶段。
            proc.kill()  # 终止卡住的 docker info 进程。
            await proc.wait()  # 回收子进程状态。
            return f"Error: docker daemon did not respond within {DOCKER_CHECK_TIMEOUT}s"  # 返回明确的 daemon 响应超时。
        except Exception as e:  # 捕获其他预检异常，保证工具不会因为 Docker 环境问题崩溃。
            return f"Error checking docker daemon: {e}"  # 将异常转成模型可读的工具错误。

        if proc.returncode == 0:  # docker info 成功，说明当前用户可以访问 Docker daemon。
            return ""  # 空字符串表示预检通过。

        detail = self._decode_output(stdout, stderr)  # 合并 stdout/stderr，保留 Docker 原始诊断信息。
        if "permission denied" in detail.lower():  # 常见原因是当前用户不能访问 /var/run/docker.sock。
            return (  # 返回具体修复方向，而不是只把 Docker 的低层错误透传给模型。
                "Error: docker daemon permission denied.\n"
                "The current user cannot access the Docker socket. Add the user to the docker group, "
                "adjust /var/run/docker.sock permissions, or run the agent from an environment that can access Docker.\n"
                f"Docker output:\n{detail}"
            )  # 结束权限错误提示。
        return f"Error: docker daemon unavailable.\nDocker output:\n{detail}"  # 其他 daemon 连接失败统一返回原始输出。

    async def _check_image_available(self, image: str) -> str:  # 检查目标 Docker 镜像是否已经存在本地；返回空字符串表示可用。
        try:  # 镜像检查可能因为 daemon 状态、镜像名错误或权限问题失败。
            proc = await asyncio.create_subprocess_exec(  # 使用 `docker image inspect`，不会触发网络拉取。
                "docker",  # Docker CLI。
                "image",  # 镜像相关子命令。
                "inspect",  # 检查本地镜像元数据。
                image,  # 要执行 Bash 命令的目标镜像名。
                stdout=asyncio.subprocess.DEVNULL,  # 镜像存在时元数据很长，这里不需要返回。
                stderr=asyncio.subprocess.PIPE,  # 镜像不存在或检查失败时保留错误信息。
                env=docker_subprocess_env(),
            )  # 得到镜像检查子进程。
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=DOCKER_CHECK_TIMEOUT)  # 限时等待本地镜像检查。
        except asyncio.TimeoutError:  # Docker 本地镜像检查异常卡住时中断。
            proc.kill()  # 终止卡住的 inspect 进程。
            await proc.wait()  # 回收子进程状态。
            return f"Error: docker image check timed out after {DOCKER_CHECK_TIMEOUT}s: {image}"  # 返回镜像检查超时。
        except Exception as e:  # 捕获其他检查异常。
            return f"Error checking docker image {image}: {e}"  # 将异常转成工具错误。

        if proc.returncode == 0:  # 镜像存在本地，后续 docker run 不需要先拉取。
            return ""  # 空字符串表示镜像可用。

        detail = stderr.decode(errors="replace").strip()  # 解码 Docker 的镜像检查错误。
        return (  # 给出两条修复路径：预拉取默认镜像，或通过环境变量指定已有镜像。
            f"Error: docker image not found locally: {image}\n"
            f"Run `docker pull {image}` first, or set `{DOCKER_IMAGE_ENV}` to an existing image that contains bash.\n"
            f"Docker output:\n{detail}"
        )  # 结束镜像缺失提示。

    async def _check_image_supports_bash(self, image: str) -> str:  # 验证镜像可以按 Bash 工具的调用方式运行 `bash -lc`。
        try:  # 镜像可能没有 bash，或镜像入口点会拦截传入的 bash 命令。
            proc = await asyncio.create_subprocess_exec(  # 启动一个极小的容器，执行 true 作为兼容性探针。
                "docker",  # Docker CLI。
                "run",  # 启动一次性容器。
                "--rm",  # 探针容器结束后立即删除。
                "--network",  # 探针不需要网络。
                "none",  # 关闭网络，避免启动检查产生外部访问。
                image,  # 要验证的目标镜像。
                "bash",  # 和 Bash.execute 中一致，要求镜像 PATH 中存在 bash。
                "-lc",  # 和 Bash.execute 中一致，用 Bash 解释命令字符串。
                "true",  # 最小无副作用命令，只验证 Bash 能启动。
                stdout=asyncio.subprocess.DEVNULL,  # 成功时不需要输出。
                stderr=asyncio.subprocess.PIPE,  # 失败时保留镜像入口点或 bash 缺失的错误。
                env=docker_subprocess_env(),
            )  # 获取探针容器子进程。
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=DOCKER_CHECK_TIMEOUT)  # 限时等待探针完成。
        except asyncio.TimeoutError:  # 镜像启动或入口点卡住时中断探针。
            proc.kill()  # 终止探针 docker run 进程。
            await proc.wait()  # 回收子进程状态。
            return f"Error: docker image bash check timed out after {DOCKER_CHECK_TIMEOUT}s: {image}"  # 返回镜像探针超时。
        except Exception as e:  # 捕获其他探针异常。
            return f"Error checking bash support in docker image {image}: {e}"  # 将异常转成启动错误。

        if proc.returncode == 0:  # 探针成功说明镜像支持当前 Bash 工具的调用方式。
            return ""  # 空字符串表示镜像可用。

        detail = stderr.decode(errors="replace").strip() or "(no output)"  # 解码探针失败信息。
        return (  # 返回明确原因和配置建议。
            f"Error: docker image cannot run `bash -lc`: {image}\n"
            f"Set `{DOCKER_IMAGE_ENV}` to an image that contains bash and allows command execution.\n"
            f"Docker output:\n{detail}"
        )  # 结束 Bash 支持检查错误。

    async def _pull_image(self, image: str) -> str:  # 拉取目标 Docker 镜像；返回空字符串表示成功。
        pull_timeout = get_docker_pull_timeout()  # 读取启动拉取超时配置，默认 30 分钟。
        try:  # docker pull 可能因为网络、认证、镜像名错误或 daemon 问题失败。
            proc = await asyncio.create_subprocess_exec(  # 异步启动 docker pull，避免阻塞事件循环。
                "docker",  # Docker CLI。
                "pull",  # 拉取镜像命令。
                image,  # 要拉取的 Bash 执行镜像。
                stdout=asyncio.subprocess.PIPE,  # 捕获拉取进度和成功信息。
                stderr=asyncio.subprocess.PIPE,  # 捕获网络错误、认证错误等诊断信息。
                env=docker_subprocess_env(),
            )  # 得到 docker pull 子进程对象。
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=pull_timeout)  # 限时等待镜像下载完成。
        except asyncio.TimeoutError:  # 拉取耗时超过配置上限时中止。
            proc.kill()  # 终止 docker pull 进程。
            await proc.wait()  # 回收子进程状态。
            return f"Error: docker pull timed out after {pull_timeout}s: {image}"  # 返回明确的拉取超时错误。
        except Exception as e:  # 捕获其他拉取阶段异常。
            return f"Error pulling docker image {image}: {e}"  # 将异常转成工具错误。

        detail = self._decode_output(stdout, stderr)  # 合并 docker pull 输出，便于失败时诊断。
        if proc.returncode != 0:  # docker pull 返回非 0 表示拉取失败。
            return f"Error: failed to pull docker image: {image}\nDocker output:\n{detail}"  # 返回镜像名和 Docker 原始输出。
        return ""  # 空字符串表示拉取成功。

    def _decode_output(self, stdout: bytes, stderr: bytes) -> str:  # 把 Docker 预检命令的 stdout/stderr 合并成紧凑文本。
        parts: list[str] = []  # 保存存在的输出片段。
        if stdout:  # 有标准输出时加入诊断文本。
            parts.append(stdout.decode(errors="replace").strip())  # 容错解码 stdout。
        if stderr:  # 有标准错误时加入诊断文本。
            parts.append(stderr.decode(errors="replace").strip())  # 容错解码 stderr。
        return "\n".join(part for part in parts if part) or "(no output)"  # 如果 Docker 没返回文本，也给出显式占位。

    async def _force_remove_container(self, container_name: str) -> None:  # 超时后的兜底清理：按名称强制删除可能仍在运行的 Docker 容器。
        try:  # 清理失败不应该覆盖原始超时错误，因此这里吞掉所有异常。
            proc = await asyncio.create_subprocess_exec(  # 异步执行 `docker rm -f`，避免清理过程阻塞事件循环。
                "docker",  # Docker CLI。
                "rm",  # 删除容器命令。
                "-f",  # 强制停止并删除容器，适用于命令已经超时的场景。
                container_name,  # 要清理的本次工具调用专属容器名。
                stdout=asyncio.subprocess.DEVNULL,  # 清理命令的正常输出不需要暴露给模型。
                stderr=asyncio.subprocess.DEVNULL,  # 清理失败也不需要额外噪声，原始超时错误已足够说明问题。
                env=docker_subprocess_env(),
            )  # 获取清理子进程对象，用于等待其结束。
            await asyncio.wait_for(proc.wait(), timeout=10)  # 最多等待 10 秒，避免 Docker 自身卡住导致工具清理无限挂起。
        except Exception:  # 删除时可能遇到容器已自动消失、Docker 不可用或等待超时等情况。
            pass  # 清理只是尽力而为；不再抛出异常，保留 execute 返回的原始超时错误。


async def ensure_docker_image(image: str | None = None) -> ToolResult:  # 对外暴露的启动预检函数，供 CLI 在注册工具前调用。
    return await Bash().ensure_image(image)  # 复用 Bash 工具内部的 Docker daemon 检查、镜像检查和拉取逻辑。
