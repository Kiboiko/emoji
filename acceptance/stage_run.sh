cd /opt/marketplace
DBU=$(tr -d '\r' < .env | grep '^DB_USER=' | cut -d= -f2)
DBN=$(tr -d '\r' < .env | grep '^DB_NAME=' | cut -d= -f2)
: > /opt/acc/outbox/telegram.jsonl
rm -f /opt/acc/outbox/results.json
chmod 666 /opt/acc/outbox/telegram.jsonl
echo "== running acceptance suite inside the stage network"
docker run --rm --network mp-acc-net -e PYTHONPATH=/app -w /app \
  -e DATABASE_URL="postgresql+asyncpg://$DBU:t@mp-acc-db:5432/$DBN" \
  -e SECRET_KEY=acc-secret-key-for-staging-only -e DEBUG=false \
  -e ADMIN_USERNAME=acc_admin -e ADMIN_PASSWORD=acc-admin-pass-123 \
  -e TELEGRAM_BOT_TOKEN=111111111:ACCfakeTokenFakeTokenFakeTokenFake12 -e ADMIN_CHAT_ID=111,222 \
  -e BASE=http://mp-acc-nginx -e OUTBOX=/outbox/telegram.jsonl -e LOAD_SECONDS=${LOAD_SECONDS:-50} -e LOAD_USERS_REAL=${LOAD_USERS_REAL:-300} \
  -v /opt/acc/code:/acc:ro -v /opt/acc/outbox:/outbox \
  --entrypoint python mp-acc-backend-img /acc/acceptance.py
RC=$?
echo "== suite exit code: $RC"
echo "== stage backend log: secrets and errors"
echo "fake bot token occurrences in stage logs: $(docker logs mp-acc-backend 2>&1 | grep -c 'ACCfakeTokenFake')"
echo "redaction markers in stage logs:          $(docker logs mp-acc-backend 2>&1 | grep -c 'скрыто')"
echo "startup bot check in stage log (fake token, Telegram must reject it and say so):"
docker logs mp-acc-backend 2>&1 | grep -F '[CONFIG]' | cut -c1-160 | head -3
docker logs mp-acc-backend 2>&1 | grep -E 'Traceback|Exception|ERROR ' | grep -v 'TELEGRAM' | sort | uniq -c | sort -rn | head -8
echo "== resources after the run"
docker stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}' mp-acc-backend mp-acc-db mp-acc-nginx marketplace_backend marketplace_db
exit 0
