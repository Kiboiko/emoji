#!/usr/bin/env bash
set -euo pipefail
: "${VERIFY_ROOT:?Set verification directory}"
case "$VERIFY_ROOT" in /opt/gram-verify-*) ;; *) exit 1;; esac
cd "$VERIFY_ROOT"
docker exec gram-verify-nginx nginx -t >artifacts/nginx-check.log 2>&1 </dev/null
docker run --rm --network gram-verify-net --entrypoint python gram-verify-bot-image -m unittest discover -s tests -q >artifacts/bot-tests.log 2>&1 </dev/null
tail -4 artifacts/bot-tests.log
docker run --rm --network gram-verify-net --cpus=1 --memory=1024m --env-file stage.env \
 -e DATABASE_URL=postgresql+asyncpg://marketplace_user:verify-only@gram-verify-db:5432/verify_test -v "$PWD/candidate/nginx:/nginx:ro" -v "$PWD/artifacts:/artifacts" --entrypoint python gram-verify-backend-image \
 -m pytest -q -p no:cacheprovider --cov=services --cov=routes --cov=utils --cov-report=json:/artifacts/coverage.json --cov-report=term:skip-covered >artifacts/pytest.log 2>&1 </dev/null
tail -4 artifacts/pytest.log
docker run --rm --network gram-verify-net --env-file stage.env -e PYTHONPATH=/app -v "$PWD/candidate/acceptance:/acc:ro" -v "$PWD/outbox:/outbox" --entrypoint python gram-verify-backend-image /acc/growth_http.py >artifacts/growth-http.log 2>&1 </dev/null
tail -5 artifacts/growth-http.log
docker run --rm --network gram-verify-net --cpus=.75 --memory=768m --env-file stage.env -e PYTHONPATH=/app \
 -v "$PWD/candidate/acceptance:/acc:ro" -v "$PWD/outbox:/outbox" --entrypoint python gram-verify-backend-image /acc/acceptance.py >artifacts/acceptance.log 2>&1 </dev/null
tail -15 artifacts/acceptance.log
