from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


def run_command(cmd: list[str], *, cwd: Path | None = None, timeout: int = 120) -> dict[str, Any]:
    env = os.environ.copy()
    env.update({"NO_PROXY": "*", "no_proxy": "*"})
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "returncode": 124, "stdout": exc.stdout or "", "stderr": "timeout"}
    except FileNotFoundError as exc:
        return {"ok": False, "returncode": 127, "stdout": "", "stderr": str(exc)}
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout[-12000:],
        "stderr": result.stderr[-12000:],
    }
