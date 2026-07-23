from __future__ import annotations

import os
import re
from pathlib import Path


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_csv(name: str, default: str = "") -> set[str]:
    return {item.strip() for item in os.getenv(name, default).split(",") if item.strip()}


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


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
DOMAIN_HOOK_SYNC_SCRIPT = Path(os.getenv("DOMAIN_HOOK_SYNC_SCRIPT", str(PROJECT_ROOT / "bin/sync_hermes_domain_hooks.py")))
HERMES_HOOKS_PATH = Path(os.getenv("HERMES_HOOKS_PATH", "/root/.hermes/hooks"))
WEB_DIR = Path(__file__).resolve().parent / "web"
INDEX_HTML = WEB_DIR / "index.html"

AUTH_MODE = os.getenv("AUTH_MODE", "disabled").strip().lower()
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "knowledge_hub_session").strip() or "knowledge_hub_session"
AUTH_COOKIE_SECURE = env_bool("AUTH_COOKIE_SECURE")
AUTH_SESSION_SECRET = os.getenv("AUTH_SESSION_SECRET", "")
AUTH_SESSION_TTL_SECONDS = env_int("AUTH_SESSION_TTL_SECONDS", 28800)
LDAP_URL = os.getenv("LDAP_URL", "").strip()
LDAP_BASE_DN = os.getenv("LDAP_BASE_DN", "").strip()
LDAP_USERS_RDN = os.getenv("LDAP_USERS_RDN", "cn=users").strip() or "cn=users"
LDAP_ADMIN_USERS = env_csv("LDAP_ADMIN_USERS", "knowledge-hub-admin")
LDAP_CONNECT_TIMEOUT_SECONDS = env_int("LDAP_CONNECT_TIMEOUT_SECONDS", 5)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
REQUIRED_FRONTMATTER = ("title", "type", "status", "owner", "updated", "domain")
VALID_STATUS = {"active", "draft", "archived"}
SKU_KEYS = ("sku", "aliases")
