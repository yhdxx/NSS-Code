#!/usr/bin/env bash
set -Eeuo pipefail

# Install the host-side runtime and all LSP servers that can be installed
# through package managers already available on the machine.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${MYCODINGAGENT_VENV:-$ROOT_DIR/.venv}"
PYTHON_BIN="${MYCODINGAGENT_PYTHON:-python3}"
SKIP_DOCKER=0
SKIP_LSP=0
UPGRADE_MODE=0

usage() {
    cat <<'EOF'
用法：bash scripts/install.sh [选项]

选项：
  --skip-docker  不构建 Bash Docker 沙箱镜像
  --skip-lsp     不安装或探测语言服务器
  --upgrade      安装必要依赖，并询问是否安装可选分析工具
  -h, --help     显示帮助

环境变量：
  MYCODINGAGENT_PYTHON    Python 解释器，默认 python3
  MYCODINGAGENT_VENV      虚拟环境目录，默认 .venv
EOF
}

log() {
    printf '[myCodingAgent] %s\n' "$*"
}

warn() {
    printf '[myCodingAgent][提示] %s\n' "$*" >&2
}

ask_optional() {
    local prompt="$1"
    if [[ ! -t 0 ]]; then
        warn "当前不是交互终端，跳过可选依赖：$prompt"
        return 1
    fi
    local answer
    read -r -p "是否安装可选依赖：$prompt？[y/N] " answer
    [[ "$answer" =~ ^([Yy]|[Yy][Ee][Ss])$ ]]
}

die() {
    printf '[myCodingAgent][错误] %s\n' "$*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --skip-docker) SKIP_DOCKER=1 ;;
        --skip-lsp) SKIP_LSP=1 ;;
        --upgrade) UPGRADE_MODE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "未知选项：$1" ;;
    esac
    shift
done

cd "$ROOT_DIR"

if ((UPGRADE_MODE == 1)); then
    log "开始升级依赖"
fi

if [[ -z "${MYCODINGAGENT_PYTHON:-}" && -x "$VENV_DIR/bin/python" ]]; then
    PYTHON_BIN="$VENV_DIR/bin/python"
fi
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "找不到 Python：$PYTHON_BIN"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 12), sys.version' \
    || die "myCodingAgent 需要 Python 3.12 或更高版本"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    log "创建 Python 虚拟环境：$VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR" || die "创建虚拟环境失败；请安装 python3-venv"
fi
export PATH="$VENV_DIR/bin:$PATH"

log "安装 Python 依赖"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt

if ((SKIP_LSP == 0)); then
    if ask_optional "Python/TypeScript/JavaScript LSP（Pyright、pylsp、typescript-language-server）"; then
        if ! command -v pylsp >/dev/null 2>&1; then
            log "安装 Python LSP 后备实现"
            "$VENV_DIR/bin/python" -m pip install 'python-lsp-server>=1.12,<2'
        fi

        if ! command -v npm >/dev/null 2>&1; then
            warn "未找到 npm，跳过 pyright 和 typescript-language-server；可安装 Node.js 后重新运行"
        elif ! command -v pyright-langserver >/dev/null 2>&1 || \
            ! command -v typescript-language-server >/dev/null 2>&1; then
            log "安装 Pyright 与 TypeScript/JavaScript LSP"
            npm install --global pyright typescript typescript-language-server
            command -v pyright-langserver >/dev/null 2>&1 || \
                warn "pyright-langserver 未出现在 PATH；请把 npm 的 global bin 目录加入 PATH"
            command -v typescript-language-server >/dev/null 2>&1 || \
                warn "typescript-language-server 未出现在 PATH；请把 npm 的 global bin 目录加入 PATH"
        fi
    fi

    if command -v go >/dev/null 2>&1; then
        if ask_optional "Go 语言服务器 gopls" && ! command -v gopls >/dev/null 2>&1; then
            log "安装 gopls"
            go install golang.org/x/tools/gopls@latest
            if [[ -d "${GOBIN:-$HOME/go/bin}" && ":$PATH:" != *":${GOBIN:-$HOME/go/bin}:"* ]]; then
                warn "请将 ${GOBIN:-$HOME/go/bin} 加入 PATH，才能让 myAgent 找到 gopls"
            fi
        fi
    else
        warn "未找到 Go，无法安装 gopls；安装 Go 后重新运行 --upgrade"
    fi

    if command -v rustup >/dev/null 2>&1; then
        if ask_optional "Rust 语言服务器 rust-analyzer" && ! command -v rust-analyzer >/dev/null 2>&1; then
            log "安装 rust-analyzer"
            rustup component add rust-analyzer
        fi
    else
        warn "未找到 rustup，无法安装 rust-analyzer；安装 Rust 后重新运行 --upgrade"
    fi

    if ! command -v jdtls >/dev/null 2>&1; then
        warn "未找到 jdtls；Java LSP 需要单独安装 Eclipse JDT Language Server"
    fi
fi

if ((SKIP_DOCKER == 0)); then
    command -v docker >/dev/null 2>&1 || die "找不到 Docker；使用 --skip-docker 可跳过镜像构建"
    if docker image inspect mycodingagent-sandbox:py312 >/dev/null 2>&1; then
        log "Bash Docker 沙箱镜像已存在，跳过构建"
    else
        log "构建 Bash Docker 沙箱镜像"
        DOCKER_CONFIG="${DOCKER_CONFIG:-$ROOT_DIR/.docker-cli}" \
            docker build --network=host -f Dockerfile.sandbox -t mycodingagent-sandbox:py312 .
    fi
else
    log "已跳过 Docker 沙箱镜像构建"
fi

log "安装完成"
printf '\n启动方式（会保留当前目录作为工作区）：\n  %q/scripts/myAgent\n' "$ROOT_DIR"
printf '\n检查 LSP 状态：\n  PYTHONPATH=. %q -c '\''from pathlib import Path; from mycodingagent.code_intelligence import LSPManager; print(LSPManager(Path.cwd()).runtime_payload())'\''\n' "$VENV_DIR/bin/python"
