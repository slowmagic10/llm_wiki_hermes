from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import yaml

import httpx
import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/root/llm_wiki_hermes"))
VAULT_PATH = Path(os.getenv("VAULT_PATH", str(PROJECT_ROOT / "vault"))).resolve()
RAG_BASE_URL = os.getenv("RAG_BASE_URL", "http://127.0.0.1:18080")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rag:rag@127.0.0.1:25432/rag")
SYNC_SCRIPT = Path(os.getenv("SYNC_SCRIPT", str(PROJECT_ROOT / "bin/sync_vault_and_rag.sh")))
SYNC_STATUS_FILE = Path(os.getenv("SYNC_STATUS_FILE", str(PROJECT_ROOT / "logs/sales-wiki-sync-status.json")))
SCHEMA_DOC = PROJECT_ROOT / "docs" / "wiki-frontmatter-schema.md"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
REQUIRED_FRONTMATTER = ("title", "type", "status", "owner", "updated")
VALID_STATUS = {"active", "draft", "archived"}
SKU_KEYS = ("sku", "aliases")

app = FastAPI(title="Sales Wiki Admin", version="0.1.0")


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 120) -> dict[str, Any]:
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
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout[-12000:],
        "stderr": result.stderr[-12000:],
    }


def _conn():
    return psycopg2.connect(DATABASE_URL)


def _fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row or {})


def _fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def _safe_rel_path(value: str) -> Path:
    rel = Path(value or ".")
    if rel.is_absolute() or ".." in rel.parts:
        raise HTTPException(status_code=400, detail="invalid path")
    target = (VAULT_PATH / rel).resolve()
    if not str(target).startswith(str(VAULT_PATH)):
        raise HTTPException(status_code=400, detail="invalid path")
    return target


def _read_sync_status() -> dict[str, Any]:
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


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


class QueryRequest(BaseModel):
    query: str


HTML_PAGE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Sales Wiki Admin</title>
  <style>
    :root { color-scheme: light; --bg:#f6f7f8; --panel:#fff; --line:#d9dde3; --text:#1f2933; --muted:#6b7280; --blue:#1f6feb; --green:#0f8f52; --red:#b42318; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    header { height:56px; display:flex; align-items:center; justify-content:space-between; padding:0 18px; border-bottom:1px solid var(--line); background:#fff; position:sticky; top:0; z-index:10; }
    h1 { font-size:17px; margin:0; font-weight:650; }
    main { display:grid; grid-template-columns:220px 1fr; min-height:calc(100vh - 56px); }
    nav { border-right:1px solid var(--line); background:#fff; padding:12px; }
    nav button { width:100%; text-align:left; border:0; background:transparent; padding:9px 10px; border-radius:6px; cursor:pointer; color:var(--text); }
    nav button.active, nav button:hover { background:#eef4ff; color:#0b57d0; }
    section { display:none; padding:18px; max-width:1280px; }
    section.active { display:block; }
    .grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); }
    .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }
    .metric { font-size:24px; font-weight:700; margin-top:4px; }
    .muted { color:var(--muted); }
    .toolbar { display:flex; gap:8px; flex-wrap:wrap; margin:0 0 12px; align-items:center; }
    button.primary { background:var(--blue); color:#fff; border-color:var(--blue); }
    button, input, textarea { font:inherit; }
    button.action { border:1px solid var(--line); background:#fff; border-radius:6px; padding:8px 10px; cursor:pointer; }
    button.action:hover { border-color:#9aa4b2; }
    input, textarea { border:1px solid var(--line); border-radius:6px; padding:8px; width:100%; background:#fff; color:var(--text); }
    textarea { min-height:96px; resize:vertical; }
    pre { margin:0; white-space:pre-wrap; word-break:break-word; background:#0f172a; color:#e5e7eb; border-radius:8px; padding:12px; max-height:520px; overflow:auto; }
    table { width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    th, td { border-bottom:1px solid var(--line); padding:9px; vertical-align:top; text-align:left; }
    th { background:#f1f3f5; font-weight:650; }
    tr:last-child td { border-bottom:0; }
    .split { display:grid; grid-template-columns:320px 1fr; gap:12px; }
    .file-list a { display:block; padding:7px 8px; color:#1f2933; text-decoration:none; border-radius:5px; }
    .file-list a:hover { background:#eef4ff; }
    .ok { color:var(--green); font-weight:650; }
    .bad { color:var(--red); font-weight:650; }
    @media (max-width: 860px) { main { grid-template-columns:1fr; } nav { display:flex; overflow:auto; border-right:0; border-bottom:1px solid var(--line); } nav button { width:auto; white-space:nowrap; } .split { grid-template-columns:1fr; } }
  </style>
</head>
<body>
<header><h1>Sales Wiki Admin</h1><div class="muted" id="now"></div></header>
<main>
<nav>
  <button class="active" data-tab="dashboard">仪表盘</button>
  <button data-tab="sync">同步管理</button>
  <button data-tab="rag">RAG 测试</button>
  <button data-tab="docs">文档浏览</button>
  <button data-tab="gaps">知识缺口</button>
  <button data-tab="audit">审计日志</button>
  <button data-tab="health">健康检查</button>
  <button data-tab="schema">Schema 模板</button>
  <button data-tab="obsidian">obsidian-wiki</button>
</nav>
<div>
<section id="dashboard" class="active"><div class="toolbar"><button class="action primary" onclick="loadStatus()">刷新状态</button></div><div id="statusCards" class="grid"></div><div class="card" style="margin-top:12px"><pre id="statusRaw">loading...</pre></div></section>
<section id="sync"><div class="toolbar"><button class="action" onclick="runAction('/api/git-pull')">Git Pull</button><button class="action" onclick="runAction('/api/sync-index')">重新索引</button><button class="action primary" onclick="runAction('/api/full-sync')">Git Pull + 重新索引</button></div><pre id="actionLog">等待操作...</pre></section>
<section id="rag"><div class="card"><textarea id="query" placeholder="输入要测试的问题，例如：QSFP-100G-DR/FR的使用场景"></textarea><div class="toolbar" style="margin-top:10px"><button class="action primary" onclick="testRag()">测试 RAG</button></div></div><div class="card" style="margin-top:12px"><pre id="ragResult">等待查询...</pre></div></section>
<section id="docs"><div class="split"><div class="card"><div class="toolbar"><button class="action" onclick="loadFiles('.')">根目录</button></div><div id="files" class="file-list">loading...</div></div><div class="card"><div id="docTitle" class="muted">选择 Markdown 文件预览</div><pre id="docPreview" style="margin-top:10px"></pre></div></div></section>
<section id="gaps"><div class="toolbar"><button class="action primary" onclick="loadGaps()">刷新</button></div><div id="gapsTable"></div></section>
<section id="audit"><div class="toolbar"><button class="action primary" onclick="loadAudit()">刷新</button></div><div id="auditTable"></div></section>
<section id="health"><div class="toolbar"><button class="action primary" onclick="loadHealth()">运行健康检查</button></div><div id="healthSummary" class="grid"></div><div class="card" style="margin-top:12px"><pre id="healthResult">等待检查...</pre></div></section>
<section id="schema"><div class="toolbar"><button class="action primary" onclick="loadSchema()">刷新模板</button></div><div class="card"><pre id="schemaTemplate">等待加载...</pre></div></section>
<section id="obsidian"><div class="toolbar"><button class="action primary" onclick="loadObsidianWiki()">检测 obsidian-wiki</button></div><div class="card"><pre id="obsidianInfo">等待检测...</pre></div></section>
</div>
</main>
<script>
const $ = (id) => document.getElementById(id);
function showTab(id){ document.querySelectorAll('section').forEach(s=>s.classList.remove('active')); $(id).classList.add('active'); document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active', b.dataset.tab===id)); }
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
function pretty(x){ return JSON.stringify(x,null,2); }
async function getJson(url, opts={}){ const r=await fetch(url, opts); const t=await r.text(); try{ const j=JSON.parse(t); if(!r.ok) throw j; return j; }catch(e){ if(!r.ok) throw new Error(t); return t; } }
function escapeHtml(s){ return s.replace(/[&<>"']/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function q(s){ return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'"); }
function table(rows, cols){ if(!rows.length) return '<div class="card muted">暂无数据</div>'; return '<table><thead><tr>'+cols.map(c=>`<th>${c[1]}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>`<td>${escapeHtml(String(r[c[0]] ?? ''))}</td>`).join('')+'</tr>').join('')+'</tbody></table>'; }
async function loadStatus(){ const data=await getJson('/api/status'); $('statusRaw').textContent=pretty(data); const cards=[['documents','文档'],['chunks','Chunks'],['indexed_files','索引文件'],['knowledge_gaps_open','Open 缺口'],['audit_logs','审计记录']]; const sync=data.sync_status||{}; $('statusCards').innerHTML=cards.map(([k,t])=>`<div class="card"><div class="muted">${t}</div><div class="metric">${data.counts?.[k] ?? '-'}</div></div>`).join('') + `<div class="card"><div class="muted">RAG</div><div class="metric ${data.rag_health?.ok?'ok':'bad'}">${data.rag_health?.ok?'OK':'FAIL'}</div></div>` + `<div class="card"><div class="muted">同步</div><div class="metric ${sync.status==='success'?'ok':(sync.status==='failed'?'bad':'')}">${sync.status || '-'}</div><div class="muted">${sync.ended_at || sync.started_at || ''}</div></div>`; }
async function runAction(url){ $('actionLog').textContent='running...'; try{ const data=await getJson(url,{method:'POST'}); $('actionLog').textContent=pretty(data); loadStatus(); }catch(e){ $('actionLog').textContent=String(e.stack||e); } }
async function testRag(){ const query=$('query').value.trim(); if(!query){ $('ragResult').textContent='请输入问题'; return; } $('ragResult').textContent='querying...'; try{ const data=await getJson('/api/rag-test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query})}); $('ragResult').textContent=pretty(data); }catch(e){ $('ragResult').textContent=String(e.stack||e); } }
async function loadFiles(path='.'){ const data=await getJson('/api/files?path='+encodeURIComponent(path)); let h=''; if(data.parent!==null) h+=`<a href="#" onclick="loadFiles('${q(data.parent)}');return false;">..</a>`; h += data.entries.map(e=>`<a href="#" onclick="${e.type==='dir'?`loadFiles('${q(e.path)}')`:`previewFile('${q(e.path)}')`};return false;">${e.type==='dir'?'📁':'📄'} ${escapeHtml(e.name)}</a>`).join(''); $('files').innerHTML=h||'<span class="muted">空目录</span>'; }
async function previewFile(path){ const data=await getJson('/api/file?path='+encodeURIComponent(path)); $('docTitle').textContent=data.path; $('docPreview').textContent=data.content; }
async function loadGaps(){ const rows=await getJson('/api/gaps'); $('gapsTable').innerHTML=table(rows,[['last_seen_at','最近'],['frequency','次数'],['status','状态'],['query','问题'],['suggested_title','原因/建议']]); }
async function loadAudit(){ const rows=await getJson('/api/audit'); $('auditTable').innerHTML=table(rows,[['created_at','时间'],['answerable','可答'],['confidence','置信度'],['query','问题'],['citations','来源']]); }
async function loadHealth(){ const data=await getJson('/api/wiki-health'); $('healthResult').textContent=pretty(data); const s=data.summary||{}; $('healthSummary').innerHTML=[['files','Markdown'],['issues','问题'],['errors','错误'],['warnings','警告']].map(([k,t])=>`<div class="card"><div class="muted">${t}</div><div class="metric ${k==='errors'&&s[k]>0?'bad':''}">${s[k] ?? '-'}</div></div>`).join(''); }
async function loadSchema(){ const data=await getJson('/api/schema-template'); $('schemaTemplate').textContent=data.content || pretty(data); }
async function loadObsidianWiki(){ const data=await getJson('/api/obsidian-wiki'); $('obsidianInfo').textContent=pretty(data); }
$('now').textContent=new Date().toLocaleString(); loadStatus(); loadFiles('.');
</script>
</body>
</html>'''


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML_PAGE


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    counts = _fetch_one("""
        select
          (select count(*) from documents) as documents,
          (select count(*) from chunks) as chunks,
          (select count(*) from indexed_files) as indexed_files,
          (select count(*) from knowledge_gaps where status='open') as knowledge_gaps_open,
          (select count(*) from audit_logs) as audit_logs
    """)
    latest_index = _fetch_one("select path, status, indexed_at, error from indexed_files order by indexed_at desc limit 1")
    latest_quality = _fetch_one("select created_at, summary, issues from quality_reports order by created_at desc limit 1")
    git_head = _run(["git", "log", "-1", "--oneline", "--decorate"], cwd=VAULT_PATH, timeout=10)
    git_status = _run(["git", "status", "--short"], cwd=VAULT_PATH, timeout=10)
    services = {
        name: _run(["systemctl", "is-active", name], timeout=5)["stdout"].strip()
        for name in ["obsidian-rag-mcp.service", "obsidian-rag-mcp-bridge.service", "sales-wiki-sync.timer"]
    }
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            rag_health = (await client.get(f"{RAG_BASE_URL}/health")).json()
    except Exception as exc:
        rag_health = {"ok": False, "error": str(exc)}
    return _jsonable({"vault_path": str(VAULT_PATH), "project_root": str(PROJECT_ROOT), "counts": counts, "latest_index": latest_index, "latest_quality": latest_quality, "git_head": git_head, "git_status": git_status, "services": services, "rag_health": rag_health, "sync_status": _read_sync_status()})


@app.get("/api/sync-status")
def sync_status() -> dict[str, Any]:
    return _jsonable(_read_sync_status())


@app.post("/api/git-pull")
def git_pull() -> dict[str, Any]:
    return _run(["git", "pull", "--ff-only"], cwd=VAULT_PATH, timeout=180)


@app.post("/api/sync-index")
async def sync_index() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
        response = await client.post(f"{RAG_BASE_URL}/admin/sync/run")
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
    return {"ok": response.status_code < 400, "status_code": response.status_code, "body": body}


@app.post("/api/full-sync")
def full_sync() -> dict[str, Any]:
    if not SYNC_SCRIPT.exists():
        raise HTTPException(status_code=500, detail=f"sync script not found: {SYNC_SCRIPT}")
    return _run([str(SYNC_SCRIPT)], timeout=900)


@app.post("/api/rag-test")
async def rag_test(request: QueryRequest) -> dict[str, Any]:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        response = await client.post(f"{RAG_BASE_URL}/rag/answer", json={"query": request.query.strip()})
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


@app.get("/api/files")
def files(path: str = Query(".")) -> dict[str, Any]:
    target = _safe_rel_path(path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name.startswith(".git"):
            continue
        if child.is_dir() or child.suffix.lower() == ".md":
            entries.append({"name": child.name, "path": child.relative_to(VAULT_PATH).as_posix(), "type": "dir" if child.is_dir() else "file"})
    rel = target.relative_to(VAULT_PATH).as_posix() if target != VAULT_PATH else "."
    parent = None if target == VAULT_PATH else target.parent.relative_to(VAULT_PATH).as_posix()
    return {"path": rel, "parent": parent, "entries": entries}


@app.get("/api/file")
def file_preview(path: str) -> dict[str, Any]:
    target = _safe_rel_path(path)
    if not target.exists() or not target.is_file() or target.suffix.lower() != ".md":
        raise HTTPException(status_code=404, detail="markdown file not found")
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"path": target.relative_to(VAULT_PATH).as_posix(), "content": content[:100000]}


@app.get("/api/gaps")
def gaps() -> list[dict[str, Any]]:
    rows = _fetch_all("""
        select last_seen_at, frequency, status, query, suggested_title
        from knowledge_gaps
        order by last_seen_at desc
        limit 100
    """)
    return _jsonable(rows)


@app.get("/api/audit")
def audit() -> list[dict[str, Any]]:
    rows = _fetch_all("""
        select created_at, answerable, round(confidence::numeric, 4) as confidence, query, citations
        from audit_logs
        order by created_at desc
        limit 100
    """)
    for row in rows:
        row["citations"] = json.dumps(row.get("citations") or [], ensure_ascii=False)
    return _jsonable(rows)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, raw[match.end():]


def _wiki_page_candidates() -> dict[str, Path]:
    pages: dict[str, Path] = {}
    for file_path in VAULT_PATH.rglob("*.md"):
        rel = file_path.relative_to(VAULT_PATH).as_posix()
        pages[rel[:-3]] = file_path
        pages[file_path.stem] = file_path
    return pages


def _check_updated(value: Any) -> tuple[str, str | None]:
    if not value:
        return "warning", "missing updated"
    text = str(value)
    try:
        dt = datetime.fromisoformat(text[:10]).replace(tzinfo=timezone.utc)
    except Exception:
        return "warning", f"invalid updated: {text}"
    age_days = (datetime.now(timezone.utc) - dt).days
    if age_days > 180:
        return "warning", f"updated is stale: {age_days} days"
    return "ok", None


@app.get("/api/wiki-health")
def wiki_health() -> dict[str, Any]:
    docs = sorted((VAULT_PATH / "10_Knowledge").rglob("*.md")) if (VAULT_PATH / "10_Knowledge").exists() else []
    indexed_rows = _fetch_all("select path, status, error from indexed_files")
    indexed = {row["path"]: row for row in indexed_rows}
    pages = _wiki_page_candidates()
    issues: list[dict[str, Any]] = []
    sku_seen: dict[str, str] = {}

    def add(path: str, severity: str, code: str, message: str) -> None:
        issues.append({"path": path, "severity": severity, "code": code, "message": message})

    for file_path in docs:
        rel = file_path.relative_to(VAULT_PATH).as_posix()
        raw = file_path.read_text(encoding="utf-8", errors="replace")
        fm, body = _parse_frontmatter(raw)
        if not fm:
            add(rel, "warning", "missing_frontmatter", "缺少 YAML frontmatter，RAG 只能依赖正文和标题。")
        else:
            for key in REQUIRED_FRONTMATTER:
                if key not in fm or fm.get(key) in (None, ""):
                    add(rel, "warning", "missing_required_field", f"缺少字段: {key}")
            status = str(fm.get("status") or "").lower()
            if status and status not in VALID_STATUS:
                add(rel, "error", "invalid_status", f"status 不合法: {status}")
            state, msg = _check_updated(fm.get("updated"))
            if msg:
                add(rel, state, "updated_check", msg)
            for key in SKU_KEYS:
                for value in _as_list(fm.get(key)):
                    norm = re.sub(r"[^a-z0-9]+", "", value.lower())
                    if not norm:
                        continue
                    if norm in sku_seen and sku_seen[norm] != rel:
                        add(rel, "error", "duplicate_sku_alias", f"{key}={value} 与 {sku_seen[norm]} 重复")
                    else:
                        sku_seen[norm] = rel
        for link in WIKILINK_RE.findall(body):
            clean = link.strip()
            if clean and clean not in pages:
                add(rel, "warning", "broken_wikilink", f"断链: [[{clean}]]")
        row = indexed.get(rel)
        if not row:
            add(rel, "warning", "not_indexed", "该文件未出现在 indexed_files 中。")
        elif row.get("status") != "indexed":
            add(rel, "error", "index_status", f"索引状态: {row.get('status')} {row.get('error') or ''}")

    summary = {
        "files": len(docs),
        "issues": len(issues),
        "errors": sum(1 for item in issues if item["severity"] == "error"),
        "warnings": sum(1 for item in issues if item["severity"] == "warning"),
    }
    return {"summary": summary, "issues": issues}


@app.get("/api/schema-template")
def schema_template() -> dict[str, Any]:
    if not SCHEMA_DOC.exists():
        return {"content": "schema document not found"}
    return {"path": str(SCHEMA_DOC), "content": SCHEMA_DOC.read_text(encoding="utf-8", errors="replace")}


@app.get("/api/obsidian-wiki")
def obsidian_wiki() -> dict[str, Any]:
    command = shutil.which("obsidian-wiki")
    venv_command = Path(sys.executable).parent / "obsidian-wiki"
    if command is None and venv_command.exists():
        command = str(venv_command)
    pip_show = _run([sys.executable, "-m", "pip", "show", "obsidian-wiki"], timeout=20)
    installed = bool(command) or pip_show.get("ok", False)
    info: dict[str, Any] = {
        "installed": installed,
        "command": command,
        "pip_show": pip_show,
        "vault_path": str(VAULT_PATH),
    }
    if command:
        info["version"] = _run([command, "--version"], timeout=20)
        info["info"] = _run([command, "info"], cwd=VAULT_PATH, timeout=60)
    elif installed:
        info["note"] = "obsidian-wiki Python package is installed, but no obsidian-wiki CLI entrypoint was found in PATH."
    else:
        info["note"] = "obsidian-wiki is not installed in this environment yet. Install it in the project venv before enabling skill operations."
    return info
