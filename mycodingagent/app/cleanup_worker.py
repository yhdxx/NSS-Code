from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import time
from pathlib import Path


def cleanup_runtime(runtime_id: str, network_name: str, docker_config: Path) -> None:
    env = os.environ.copy()
    docker_config.mkdir(parents=True, exist_ok=True)
    env["DOCKER_CONFIG"] = str(docker_config)
    listed = _run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.mycodingagent.managed=true",
            "--filter",
            f"label=com.mycodingagent.runtime={runtime_id}",
        ],
        env,
    )
    container_ids = listed.stdout.split() if listed.returncode == 0 else []
    if container_ids:
        _run(["docker", "rm", "-f", *container_ids], env)
    for _attempt in range(10):
        removed = _run(["docker", "network", "rm", network_name], env)
        if removed.returncode == 0 or "not found" in removed.stderr.lower():
            return
        time.sleep(0.25)


def cleanup_stale_workspace_runtimes(
    workspace_root: Path,
    docker_config: Path,
    *,
    excluded_runtime_ids: set[str] | None = None,
) -> None:
    """Remove managed runtimes left by a crashed process for one workspace."""
    workspace_key = hashlib.sha256(
        str(workspace_root.expanduser().resolve(strict=False)).encode("utf-8")
    ).hexdigest()[:16]
    excluded = excluded_runtime_ids or set()
    env = os.environ.copy()
    docker_config.mkdir(parents=True, exist_ok=True)
    env["DOCKER_CONFIG"] = str(docker_config)
    networks = _run(
        [
            "docker",
            "network",
            "ls",
            "-q",
            "--filter",
            "label=com.mycodingagent.managed=true",
            "--filter",
            "label=com.mycodingagent.kind=managed-network",
            "--filter",
            f"label=com.mycodingagent.workspace={workspace_key}",
        ],
        env,
    )
    for network_id in networks.stdout.split() if networks.returncode == 0 else []:
        inspected = _run(
            ["docker", "network", "inspect", "--format", "{{index .Labels \"com.mycodingagent.runtime\"}}", network_id],
            env,
        )
        runtime_id = inspected.stdout.strip()
        if runtime_id and runtime_id not in excluded:
            cleanup_runtime(runtime_id, network_id, docker_config)

    containers = _run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.mycodingagent.managed=true",
            "--filter",
            "label=com.mycodingagent.kind=workspace-runtime",
            "--filter",
            f"label=com.mycodingagent.workspace={workspace_key}",
        ],
        env,
    )
    for container_id in containers.stdout.split() if containers.returncode == 0 else []:
        inspected = _run(
            ["docker", "inspect", "--format", "{{index .Config.Labels \"com.mycodingagent.runtime\"}}", container_id],
            env,
        )
        if inspected.stdout.strip() not in excluded:
            _run(["docker", "rm", "-f", container_id], env)


def _run(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, "", str(exc))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-id")
    parser.add_argument("--network-name")
    parser.add_argument("--docker-config", required=True, type=Path)
    parser.add_argument("--stale-workspace", type=Path)
    parser.add_argument("--exclude-runtime", action="append", default=[])
    args = parser.parse_args()
    if args.stale_workspace is not None:
        cleanup_stale_workspace_runtimes(
            args.stale_workspace,
            args.docker_config,
            excluded_runtime_ids=set(args.exclude_runtime),
        )
    else:
        if not args.runtime_id or not args.network_name:
            parser.error("--runtime-id and --network-name are required without --stale-workspace")
        cleanup_runtime(args.runtime_id, args.network_name, args.docker_config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
