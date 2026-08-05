myCodingAgent 沙箱镜像使用说明
===============================

Runtime 在每次 Agent 会话开始时自动启动一个工作区沙箱容器，所有 Bash 调用通过 `docker exec` 复用它。
容器会在 Agent 退出时删除，所以不要在容器里手动安装包并期望跨会话保留。
长期可复用的命令和 Python 包都应该安装进 Docker 镜像：

    mycodingagent-sandbox:py312


1. 沙箱镜像文件
---------------

相关文件：

    Dockerfile.sandbox
    requirements-sandbox.txt
    mycodingagent/configuration/settings.py
    mycodingagent/tool_runtime/bash.py
    mycodingagent/workspace_runtime.py

说明：

    Dockerfile.sandbox
        定义沙箱基础镜像、apt 源、系统命令工具。

    requirements-sandbox.txt
        定义沙箱内预装的 Python 包。

    mycodingagent/configuration/settings.py
        默认 Docker 镜像为 mycodingagent-sandbox:py312。

    mycodingagent/tool_runtime/bash.py
        负责检查镜像、自动构建本地沙箱镜像、审批并执行命令。

    mycodingagent/workspace_runtime.py
        负责会话容器、工作区专用网络以及退出清理。


2. 重新构建沙箱镜像
-------------------

修改 Dockerfile.sandbox 或 requirements-sandbox.txt 后，执行：

    DOCKER_CONFIG=/home/djia/PycharmProjects/myCodingAgent/.docker-cli \
    docker build --network=host -f Dockerfile.sandbox -t mycodingagent-sandbox:py312 .

构建成功后，项目后续每次启动容器都会使用新镜像。


3. 增加或减少 Linux 命令工具
----------------------------

如果想让沙箱内增加命令，例如 jq、vim、ffmpeg，需要修改：

    Dockerfile.sandbox

在 apt-get install 列表中增加对应 apt 包名，例如：

    jq \
    vim \
    ffmpeg \

然后重新构建镜像。

如果想减少某个命令，从 Dockerfile.sandbox 的 apt-get install 列表删除对应包名，再重新构建镜像。

注意：命令名和 apt 包名不一定完全一致：

    awk              -> gawk
    ssh              -> openssh-client
    ps               -> procps
    pstree / killall -> psmisc
    xz               -> xz-utils
    sh               -> dash
    which            -> debianutils


4. 增加或减少 Python 包
-----------------------

如果想让沙箱内增加 Python 包，例如 beautifulsoup4、lxml、pandas，需要修改：

    requirements-sandbox.txt

增加一行，例如：

    beautifulsoup4

然后重新构建镜像。

如果想减少某个 Python 包，从 requirements-sandbox.txt 删除对应行，再重新构建镜像。


5. 验证沙箱镜像
---------------

验证基础命令是否存在：

    DOCKER_CONFIG=/home/djia/PycharmProjects/myCodingAgent/.docker-cli \
    docker run --rm --network none \
      -v /home/djia/PycharmProjects/myCodingAgent:/workspace:rw \
      -w /workspace \
      mycodingagent-sandbox:py312 \
      bash -lc 'command -v bash sh find grep sed awk tar gzip zip unzip xz bzip2 curl wget git ssh less tree file which ps pstree killall time'

验证 Python 包是否可导入：

    DOCKER_CONFIG=/home/djia/PycharmProjects/myCodingAgent/.docker-cli \
    docker run --rm --network none \
      -v /home/djia/PycharmProjects/myCodingAgent:/workspace:rw \
      -w /workspace \
      mycodingagent-sandbox:py312 \
      python -c "import openai, pydantic, rich, typer, httpx, requests, yaml, orjson; print('ok')"

验证项目代码的 Docker 预检逻辑：

    ./.venv/bin/python - <<'PY'
    import asyncio
    from tools.bash import ensure_docker_image, get_docker_image

    async def main():
        print("configured image:", get_docker_image())
        result = await ensure_docker_image()
        print("is_error:", result.is_error)
        print(result.output)

    asyncio.run(main())
    PY


6. 运行时行为
-------------

默认镜像：

    mycodingagent-sandbox:py312

对应配置在 mycodingagent/configuration/settings.py：

    MYCODINGAGENT_DOCKER_IMAGE

如果默认镜像不存在，mycodingagent/tool_runtime/bash.py 会优先检查它是否是本项目本地沙箱镜像。
对于 mycodingagent-sandbox:py312，代码会使用 Dockerfile.sandbox 自动构建，而不是错误地执行 docker pull。

如果使用其他远程镜像，镜像不存在时仍然会执行 docker pull。


7. 常用环境变量
---------------

    MYCODINGAGENT_DOCKER_IMAGE
        覆盖默认沙箱镜像。

    MYCODINGAGENT_NETWORK_ENABLED
        控制 Agent 工具公网权限的启动默认值；CLI 会话始终使用 Runtime 创建的 internal 网络和受控出口。

    MYCODINGAGENT_NETWORK_UPSTREAM_PROXY
        设置 Runtime 上游代理。默认 auto，自动读取 HTTP_PROXY、HTTPS_PROXY 或 ALL_PROXY，也支持 SOCKS5。

    MYCODINGAGENT_DOCKER_BUILD_NETWORK
        控制 docker build 阶段网络，默认 host。

    MYCODINGAGENT_DOCKER_CPUS
        控制容器 CPU 限制，默认 2。

    MYCODINGAGENT_DOCKER_MEMORY
        控制容器内存限制，默认 1g。

    MYCODINGAGENT_DOCKER_PULL_TIMEOUT
        控制镜像拉取或本地构建超时时间，默认 1800 秒。


8. 注意事项
-----------

    1. 每次 Agent 会话复用一个工作区容器，Agent 退出后自动删除。
    2. 需要长期保留的命令或包必须写入 Dockerfile.sandbox 或 requirements-sandbox.txt。
    3. 修改 Dockerfile.sandbox 或 requirements-sandbox.txt 后必须重新构建 mycodingagent-sandbox:py312。
    4. .docker-cli 是 Docker CLI 的可写配置目录，已加入 .gitignore。
    5. apt 默认使用 Aliyun Debian 源，pip 默认使用 Aliyun PyPI 源。
