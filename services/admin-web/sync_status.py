from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import SYNC_STATUS_FILE


def read_sync_status() -> dict[str, Any]:
    if not SYNC_STATUS_FILE.exists():
        return {"exists": False, "path": str(SYNC_STATUS_FILE)}
    try:
        data = json.loads(SYNC_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"exists": True, "path": str(SYNC_STATUS_FILE), "error": str(exc)}
    data["exists"] = True
    data["path"] = str(SYNC_STATUS_FILE)
    log_file = data.get("log_file")
    if log_file:
        log_path = Path(str(log_file))
        if log_path.exists():
            try:
                data["log_tail"] = log_path.read_text(encoding="utf-8", errors="replace")[-12000:]
            except Exception as exc:
                data["log_tail_error"] = str(exc)
    return data
