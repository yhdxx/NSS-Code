from __future__ import annotations

import argparse
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
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--network-name", required=True)
    parser.add_argument("--docker-config", required=True, type=Path)
    args = parser.parse_args()
    cleanup_runtime(args.runtime_id, args.network_name, args.docker_config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
