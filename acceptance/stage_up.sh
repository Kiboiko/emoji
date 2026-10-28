# Одноразовый приёмочный стенд: копия боевой базы + код из /opt/marketplace + тот же nginx.
# Боевые контейнеры и данные не трогаются. Подробности — acceptance/README.md
set -e
cd /opt/marketplace
DBU=$(tr -d '\r' < .env | grep '^DB_USER=' | cut -d= -f2)
DBN=$(tr -d '\r' < .env | grep '^DB_NAME=' | cut -d= -f2)

echo "== cleanup of any previous stage"
docker rm -f mp-acc-nginx mp-acc-backend mp-acc-db > /dev/null 2>&1 || true
docker network rm mp-acc-net > /dev/null 2>&1 || true
rm -rf /opt/acc/uploads /opt/acc/outbox
mkdir -p /opt/acc/uploads /opt/acc/outbox
chmod 777 /opt/acc/outbox

echo "== volumes present?"
docker volume ls --format '{{.Name}}' | grep -E '^marketplace_(uploads|frontend-dist|admin-dist)$'

echo "== backend image from the code in /opt/marketplace/backend (the production image is not touched)"
docker build -q -t mp-acc-backend-img /opt/marketplace/backend | tail -1
echo "== network + database (restored from a FRESH dump of production, read-only)"
docker network create mp-acc-net > /dev/null
docker run -d --name mp-acc-db --network mp-acc-net -e POSTGRES_USER="$DBU" -e POSTGRES_PASSWORD=t -e POSTGRES_DB="$DBN" postgres:17-alpine > /dev/null
for i in $(seq 1 40); do docker exec mp-acc-db pg_isready -U "$DBU" -d "$DBN" > /dev/null 2>&1 && break; sleep 1; done
sleep 2
docker compose exec -T postgres pg_dump -U "$DBU" "$DBN" < /dev/null | docker exec -i mp-acc-db psql -U "$DBU" -d "$DBN" -q -v ON_ERROR_STOP=0 2>&1 | grep -ciE '^psql.*error' || true
docker exec mp-acc-db psql -U "$DBU" -d "$DBN" -At -c "select 'copy: alembic ' || version_num from alembic_version union all select 'copy: users ' || count(*) from users union all select 'copy: products ' || count(*) from products"

echo "== migrations on the restored real data, with the release-candidate image"
docker run --rm --network mp-acc-net -e DATABASE_URL="postgresql+asyncpg://$DBU:t@mp-acc-db:5432/$DBN" -e SECRET_KEY=x --entrypoint alembic mp-acc-backend-img upgrade head 2>&1 | grep -E "Running upgrade|rror"
docker exec mp-acc-db psql -U "$DBU" -d "$DBN" -At -c "select 'after migration: alembic ' || version_num from alembic_version" < /dev/null
echo "== uploads copy (so catalog images exist)"
docker run --rm -v marketplace_uploads:/from:ro -v /opt/acc/uploads:/to alpine sh -c 'cp -a /from/. /to/ && chown -R 1000:1000 /to && du -sh /to'

echo "== backend (production image, fake bot token, Telegram transport captured)"
docker run -d --name mp-acc-backend --network mp-acc-net --network-alias backend \
  -e DATABASE_URL="postgresql+asyncpg://$DBU:t@mp-acc-db:5432/$DBN" \
  -e SECRET_KEY=acc-secret-key-for-staging-only -e DEBUG=false -e COOKIE_SECURE=true \
  -e ADMIN_USERNAME=acc_admin -e ADMIN_PASSWORD=acc-admin-pass-123 \
  -e TELEGRAM_BOT_TOKEN=111111111:ACCfakeTokenFakeTokenFakeTokenFake12 \
  -e ADMIN_CHAT_ID=111,222 -e REVIEWS_CHANNEL_ID=@acc_reviews \
  -e SITE_URL=https://acc.example -e CORS_ORIGINS='["https://acc.example"]' \
  -e TON_NETWORK=testnet -e INTERNAL_API_TOKEN=acc-internal -e OUTBOX=/outbox/telegram.jsonl \
  -v /opt/acc/uploads:/app/uploads -v /opt/acc/outbox:/outbox -v /opt/acc/code:/acc:ro \
  --entrypoint python mp-acc-backend-img /acc/run_backend.py > /dev/null

echo "== nginx (production config, production frontend and admin builds)"
docker run -d --name mp-acc-nginx --network mp-acc-net -p 127.0.0.1:18080:80 \
  -v /opt/marketplace/nginx/nginx.conf:/etc/nginx/nginx.conf:ro \
  -v marketplace_frontend-dist:/usr/share/nginx/html/frontend:ro \
  -v marketplace_admin-dist:/usr/share/nginx/html/admin:ro \
  -v /opt/acc/uploads:/usr/share/nginx/html/uploads:ro nginx:1.27-alpine > /dev/null

echo "== wait for readiness"
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/api/categories || true)
  [ "$code" = "200" ] && break; sleep 2
done
echo "categories via nginx: $code"
docker logs mp-acc-backend 2>&1 | grep -E 'Schema|Схема|startup complete|Error|Traceback' | head -5
