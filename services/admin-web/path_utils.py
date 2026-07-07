from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from config import VAULT_PATH


def safe_rel_path(value: str) -> Path:
    rel = Path(value or ".")
    if rel.is_absolute() or ".." in rel.parts:
        raise HTTPException(status_code=400, detail="invalid path")
    target = (VAULT_PATH / rel).resolve()
    if not str(target).startswith(str(VAULT_PATH)):
        raise HTTPException(status_code=400, detail="invalid path")
    return target
