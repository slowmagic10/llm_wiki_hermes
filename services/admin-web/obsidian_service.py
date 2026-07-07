from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from config import VAULT_PATH
from shell import run_command


def obsidian_wiki() -> dict[str, Any]:
    command = shutil.which("obsidian-wiki")
    venv_command = Path(sys.executable).parent / "obsidian-wiki"
    if command is None and venv_command.exists():
        command = str(venv_command)
    pip_show = run_command([sys.executable, "-m", "pip", "show", "obsidian-wiki"], timeout=20)
    installed = bool(command) or pip_show.get("ok", False)
    info: dict[str, Any] = {
        "installed": installed,
        "command": command,
        "pip_show": pip_show,
        "vault_path": str(VAULT_PATH),
    }
    if command:
        info["version"] = run_command([command, "--version"], timeout=20)
        info["info"] = run_command([command, "info"], cwd=VAULT_PATH, timeout=60)
    elif installed:
        info["note"] = "obsidian-wiki Python package is installed, but no obsidian-wiki CLI entrypoint was found in PATH."
    else:
        info["note"] = "obsidian-wiki is not installed in this environment yet. Install it in the project venv before enabling skill operations."
    return info
