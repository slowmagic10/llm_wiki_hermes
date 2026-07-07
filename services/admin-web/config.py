from __future__ import annotations

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/root/llm_wiki_hermes"))
VAULT_PATH = Path(os.getenv("VAULT_PATH", str(PROJECT_ROOT / "vault"))).resolve()
RAG_BASE_URL = os.getenv("RAG_BASE_URL", "http://127.0.0.1:18080")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rag:rag@127.0.0.1:25432/rag")
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:14000/v1")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
SYNC_SCRIPT = Path(os.getenv("SYNC_SCRIPT", str(PROJECT_ROOT / "bin/sync_vault_and_rag.sh")))
SYNC_STATUS_FILE = Path(os.getenv("SYNC_STATUS_FILE", str(PROJECT_ROOT / "logs/llm-wiki-sync-status.json")))
SCHEMA_DOC = PROJECT_ROOT / "docs" / "wiki-frontmatter-schema.md"
MODEL_SETTINGS_PATH = Path(os.getenv("MODEL_SETTINGS_PATH", str(PROJECT_ROOT / "config/model-settings.json")))
DOMAIN_REGISTRY_PATH = Path(os.getenv("DOMAIN_REGISTRY_PATH", str(PROJECT_ROOT / "config/domains.yml")))
WEB_DIR = Path(__file__).resolve().parent / "web"
INDEX_HTML = WEB_DIR / "index.html"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
REQUIRED_FRONTMATTER = ("title", "type", "status", "owner", "updated", "domain")
VALID_STATUS = {"active", "draft", "archived"}
SKU_KEYS = ("sku", "aliases")
