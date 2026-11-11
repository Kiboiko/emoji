#!/usr/bin/env bash
# Remove only the disposable stage and its private data copies. Keep source/logs.
set -euo pipefail
: "${VERIFY_ROOT:?Set verification directory}"
case "$VERIFY_ROOT" in /opt/gram-verify-*) ;; *) echo 'Unexpected verification root'; exit 1;; esac
test "$(realpath -e "$VERIFY_ROOT")" = "$VERIFY_ROOT"
for name in gram-verify-nginx gram-verify-backend gram-verify-db; do
 if docker inspect "$name" >/dev/null 2>&1; then
  test "$(docker inspect -f '{{.Name}}' "$name")" = "/$name"
  test "$(docker inspect -f '{{if index .NetworkSettings.Networks "gram-verify-net"}}yes{{end}}' "$name")" = yes
  docker rm -f -v "$name" </dev/null
 fi
done
for name in gram-verify-net gram-verify-edge; do
 if docker network inspect "$name" >/dev/null 2>&1; then docker network rm "$name" </dev/null; fi
done
for name in uploads outbox; do
 if [ -d "$VERIFY_ROOT/$name" ]; then
  target=$(realpath -e "$VERIFY_ROOT/$name")
  test "$target" = "$VERIFY_ROOT/$name"
  rm -rf -- "$target"
 fi
done
chmod 700 "$VERIFY_ROOT"
echo 'Disposable databases, uploads, outbox and networks removed; candidate and restricted logs retained.'
