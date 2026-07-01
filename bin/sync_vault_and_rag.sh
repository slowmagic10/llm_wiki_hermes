#!/usr/bin/env bash
set -euo pipefail

export NO_PROXY="*"
export no_proxy="*"

project_root="/root/llm_wiki_hermes"
vault_path="${project_root}/vault"
rag_base_url="${RAG_BASE_URL:-http://127.0.0.1:18080}"
log_dir="${project_root}/logs"
status_file="${log_dir}/llm-wiki-sync-status.json"
lock_file="/run/llm-wiki-sync.lock"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
run_id="$(date -u +%Y%m%dT%H%M%SZ)"
log_file="${log_dir}/llm-wiki-sync-${run_id}.log"

mkdir -p "${log_dir}"

write_status() {
  local status="$1"
  local exit_code="$2"
  local message="$3"
  local ended_at=""
  if [[ "${status}" != "running" ]]; then
    ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  fi
  python3 - "${status_file}" "${status}" "${exit_code}" "${message}" "${started_at}" "${ended_at}" "${log_file}" "${vault_path}" <<'PY'
import json
import pathlib
import subprocess
import sys

status_file, status, exit_code, message, started_at, ended_at, log_file, vault_path = sys.argv[1:]
data = {
    "status": status,
    "exit_code": int(exit_code),
    "message": message,
    "started_at": started_at,
    "ended_at": ended_at or None,
    "log_file": log_file,
    "vault_path": vault_path,
}
try:
    result = subprocess.run(
        ["git", "log", "-1", "--oneline", "--decorate"],
        cwd=vault_path,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    data["git_head"] = result.stdout.strip()
except Exception as exc:
    data["git_head_error"] = str(exc)
path = pathlib.Path(status_file)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

exec 9>"${lock_file}"
if ! flock -n 9; then
  write_status "skipped" 0 "another sync is already running"
  exit 0
fi

exec > >(tee -a "${log_file}") 2>&1

write_status "running" 0 "sync started"

cleanup() {
  local rc=$?
  if [[ ${rc} -eq 0 ]]; then
    write_status "success" 0 "git pull and RAG sync completed"
  else
    write_status "failed" "${rc}" "sync failed; see log_file"
  fi
  find "${log_dir}" -maxdepth 1 -type f -name 'llm-wiki-sync-*.log' -printf '%T@ %p\n' | sort -nr | awk 'NR>20 {print $2}' | xargs -r rm -f
  exit ${rc}
}
trap cleanup EXIT

echo "[sync] started_at=${started_at}"
cd "${vault_path}"
echo "[sync] git pull --ff-only"
git pull --ff-only

echo "[sync] refresh RAG index"
curl -fsS --noproxy "*" -X POST "${rag_base_url%/}/admin/sync/run"
echo

echo "[sync] completed"
