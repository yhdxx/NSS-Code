from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fake_launcher_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "project"
    scripts = root / "scripts"
    venv_bin = root / ".venv" / "bin"
    scripts.mkdir(parents=True)
    venv_bin.mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "scripts" / "myAgent", scripts / "myAgent")
    (root / "__main__.py").write_text("", encoding="utf-8")
    install_log = tmp_path / "install.log"
    python_log = tmp_path / "python.log"
    (scripts / "install.sh").write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$INSTALL_LOG\"\n",
        encoding="utf-8",
    )
    (venv_bin / "python").write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$PYTHON_LOG\"\n",
        encoding="utf-8",
    )
    (scripts / "install.sh").chmod(0o755)
    (venv_bin / "python").chmod(0o755)
    return scripts / "myAgent", install_log, python_log


def test_launcher_normal_start_does_not_run_installer(tmp_path):
    launcher, install_log, python_log = _fake_launcher_project(tmp_path)
    env = {**os.environ, "INSTALL_LOG": str(install_log), "PYTHON_LOG": str(python_log)}

    subprocess.run([str(launcher), "ordinary-arg"], check=True, env=env)

    assert not install_log.exists()
    assert python_log.read_text(encoding="utf-8").splitlines()[-1] == "ordinary-arg"


def test_launcher_upgrade_runs_installer_once_and_strips_argument(tmp_path):
    launcher, install_log, python_log = _fake_launcher_project(tmp_path)
    env = {**os.environ, "INSTALL_LOG": str(install_log), "PYTHON_LOG": str(python_log)}

    subprocess.run([str(launcher), "--upgrade", "ordinary-arg"], check=True, env=env)

    assert install_log.read_text(encoding="utf-8").splitlines() == ["--upgrade"]
    forwarded = python_log.read_text(encoding="utf-8").splitlines()
    assert "--upgrade" not in forwarded
    assert forwarded[-1] == "ordinary-arg"


def test_install_script_creates_user_level_launcher(tmp_path):
    bin_dir = tmp_path / "bin"
    env = {**os.environ, "MYCODINGAGENT_BIN_DIR": str(bin_dir)}

    subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts" / "install.sh"), "--launcher-only"],
        check=True,
        env=env,
        cwd=PROJECT_ROOT,
    )

    launcher = bin_dir / "myAgent"
    assert launcher.is_symlink()
    assert launcher.resolve() == (PROJECT_ROOT / "scripts" / "myAgent").resolve()


def test_install_script_rejects_misspelled_upgrade():
    result = subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts" / "install.sh"), "--upgrate"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert result.returncode != 0
    assert "未知选项" in result.stderr
