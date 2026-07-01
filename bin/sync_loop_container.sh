#!/bin/sh
set -eu
while true; do
  /root/llm_wiki_hermes/bin/sync_vault_and_rag_container.sh || true
  sleep "${SYNC_INTERVAL_SECONDS:-86400}"
done
