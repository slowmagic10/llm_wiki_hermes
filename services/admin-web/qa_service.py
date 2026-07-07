from __future__ import annotations

import json
from typing import Any

from db import fetch_all
from utils import jsonable


def gaps() -> list[dict[str, Any]]:
    rows = fetch_all("""
        select last_seen_at, frequency, status, query, suggested_title
        from knowledge_gaps
        order by last_seen_at desc
        limit 100
    """)
    return jsonable(rows)


def audit() -> list[dict[str, Any]]:
    rows = fetch_all("""
        select created_at, answerable, round(confidence::numeric, 4) as confidence, query, citations
        from audit_logs
        order by created_at desc
        limit 100
    """)
    for row in rows:
        row["citations"] = json.dumps(row.get("citations") or [], ensure_ascii=False)
    return jsonable(rows)
