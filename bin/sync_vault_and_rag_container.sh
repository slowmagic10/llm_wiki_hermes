#!/bin/sh
set -eu

export NO_PROXY="*"
export no_proxy="*"

project_root="/root/llm_wiki_hermes"
vault_path="${project_root}/vault"
rag_base_url="${RAG_BASE_URL:-http://rag-api:18080}"
log_dir="${project_root}/logs"
status_file="${log_dir}/sales-wiki-sync-status.json"
lock_file="/tmp/sales-wiki-sync.lock"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
run_id="$(date -u +%Y%m%dT%H%M%SZ)"
log_file="${log_dir}/sales-wiki-sync-${run_id}.log"

mkdir -p "${log_dir}"

git config --global --add safe.directory "${vault_path}" >/dev/null 2>&1 || true

json_escape() {
  printf '%s' "$1" | tr '
' ' ' | sed 's/"/\"/g'
}

write_status() {
  status="$1"
  exit_code="$2"
  message="$3"
  ended_at=""
  if [ "${status}" != "running" ]; then
    ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  fi
  git_head=""
  if [ -d "${vault_path}/.git" ]; then
    git_head="$(git -C "${vault_path}" log -1 --oneline --decorate 2>/dev/null || true)"
  fi
  cat > "${status_file}" <<EOF
{
  "status": "$(json_escape "${status}")",
  "exit_code": ${exit_code},
  "message": "$(json_escape "${message}")",
  "started_at": "$(json_escape "${started_at}")",
  "ended_at": "$(json_escape "${ended_at}")",
  "log_file": "$(json_escape "${log_file}")",
  "vault_path": "$(json_escape "${vault_path}")",
  "git_head": "$(json_escape "${git_head}")"
}
EOF
}

run_sync() {
  echo "[sync] started_at=${started_at}"
  cd "${vault_path}"
  echo "[sync] git pull --ff-only"
  git pull --ff-only
  echo "[sync] refresh RAG index via ${rag_base_url%/}"
  wget -qO- --post-data='' "${rag_base_url%/}/admin/sync/run"
  echo
  echo "[sync] completed"
}

if ! flock -n "${lock_file}" -c "echo locked" >/dev/null 2>&1; then
  write_status "skipped" 0 "another sync is already running"
  exit 0
fi

write_status "running" 0 "sync started"
if run_sync > "${log_file}" 2>&1; then
  cat "${log_file}"
  write_status "success" 0 "git pull and RAG sync completed"
else
  rc=$?
  cat "${log_file}" || true
  write_status "failed" "${rc}" "sync failed; see log_file"
  exit "${rc}"
fi

find "${log_dir}" -maxdepth 1 -type f -name 'sales-wiki-sync-*.log' -printf '%T@ %p
' 2>/dev/null | sort -nr | awk 'NR>20 {print $2}' | xargs -r rm -f 2>/dev/null || true
