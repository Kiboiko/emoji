#!/usr/bin/env bash
# Candidate-only verification; never replaces production files, images or volumes.
set -euo pipefail
: "${VERIFY_ROOT:?Set absolute verification directory}"
case "$VERIFY_ROOT" in /opt/gram-verify-*) ;; *) echo 'Unexpected verification root'; exit 1;; esac
cd "$VERIFY_ROOT"
for name in gram-verify-db gram-verify-backend gram-verify-nginx; do
 if docker inspect "$name" >/dev/null 2>&1; then echo "Verification container already exists: $name"; exit 1; fi
done
mkdir -p artifacts uploads outbox frontend-dist admin-dist
chmod 777 outbox
chown 1000:1000 artifacts
docker network create --internal gram-verify-net >/dev/null
docker network create gram-verify-edge >/dev/null
docker run -d --name gram-verify-db --network gram-verify-net --cpus=1 --memory=768m \
 -e POSTGRES_USER=marketplace_user -e POSTGRES_PASSWORD=verify-only -e POSTGRES_DB=verify postgres:17-alpine >/dev/null
for i in $(seq 1 40); do docker exec gram-verify-db pg_isready -U marketplace_user -d verify >/dev/null 2>&1 && break; sleep 1; done
docker exec marketplace_db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' </dev/null \
 | docker exec -i gram-verify-db psql -U marketplace_user -d verify -v ON_ERROR_STOP=1 -q >artifacts/restore.log 2>&1
docker exec gram-verify-db createdb -U marketplace_user verify_test </dev/null
docker exec gram-verify-db createdb -U marketplace_user verify_empty </dev/null
cat > stage.env <<'ENV'
DATABASE_URL=postgresql+asyncpg://marketplace_user:verify-only@gram-verify-db:5432/verify
TEST_DATABASE_URL=postgresql+asyncpg://marketplace_user:verify-only@gram-verify-db:5432/verify_test
SECRET_KEY=acc-secret-key-for-staging-only
DEBUG=false
COOKIE_SECURE=true
ADMIN_USERNAME=acc_admin
ADMIN_PASSWORD=acc-admin-pass-123
TELEGRAM_BOT_TOKEN=111111111:ACCfakeTokenFakeTokenFakeTokenFake12
VITE_BOT_USERNAME=acc_bot
ADMIN_CHAT_ID=111,222
REVIEWS_CHANNEL_ID=@acc_reviews
SITE_URL=https://acc.example
CORS_ORIGINS=["https://acc.example"]
TON_NETWORK=testnet
TON_RECEIVING_ADDRESS=EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c
INTERNAL_API_TOKEN=acc-internal
OUTBOX=/outbox/telegram.jsonl
MOCK_CONTROLS=/outbox/mock-controls.json
CAPTURE_EXTERNAL_API=1
BASE=http://gram-verify-nginx
LOAD_SECONDS=50
LOAD_USERS_REAL=300
ENV
chmod 600 stage.env
echo 'Building backend candidate'
docker build -t gram-verify-backend-image candidate/backend >artifacts/build-backend.log 2>&1 </dev/null
echo 'Building frontend candidate'
docker build -t gram-verify-frontend-image --build-arg VITE_API_URL=/api --build-arg VITE_BOT_USERNAME=acc_bot --build-arg SITE_URL=https://acc.example candidate/frontend >artifacts/build-frontend.log 2>&1 </dev/null
echo 'Building admin candidate'
docker build -t gram-verify-admin-image candidate/admin >artifacts/build-admin.log 2>&1 </dev/null
echo 'Building bot candidate (tests only, no polling)'
docker build -t gram-verify-bot-image candidate/bot >artifacts/build-bot.log 2>&1 </dev/null
docker run --rm -v "$PWD/frontend-dist:/export" --entrypoint sh gram-verify-frontend-image -c 'cp -a /app/build/. /export/' </dev/null
docker run --rm -v "$PWD/admin-dist:/export" --entrypoint sh gram-verify-admin-image -c 'cp -a /app/build/. /export/' </dev/null
docker run --rm --network gram-verify-net --env-file stage.env --entrypoint alembic gram-verify-backend-image upgrade head >artifacts/migration-copy.log 2>&1 </dev/null
docker run --rm --network gram-verify-net --env-file stage.env -e DATABASE_URL=postgresql+asyncpg://marketplace_user:verify-only@gram-verify-db:5432/verify_empty --entrypoint alembic gram-verify-backend-image upgrade head >artifacts/migration-empty.log 2>&1 </dev/null
docker run --rm -v marketplace_uploads:/from:ro -v "$PWD/uploads:/to" alpine sh -c 'cp -a /from/. /to/ && chown -R 1000:1000 /to' </dev/null
docker run -d --name gram-verify-backend --network gram-verify-net --network-alias backend --cpus=1 --memory=1024m --env-file stage.env \
 -v "$PWD/uploads:/app/uploads" -v "$PWD/outbox:/outbox" -v "$PWD/candidate/acceptance:/acc:ro" --entrypoint python gram-verify-backend-image /acc/run_backend.py >/dev/null </dev/null
docker run -d --name gram-verify-nginx --network gram-verify-edge --cpus=.5 --memory=128m -p 127.0.0.1:18083:80 \
 -v "$PWD/candidate/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$PWD/frontend-dist:/usr/share/nginx/html/frontend:ro" \
 -v "$PWD/admin-dist:/usr/share/nginx/html/admin:ro" -v "$PWD/uploads:/usr/share/nginx/html/uploads:ro" nginx:1.27-alpine >/dev/null </dev/null
docker network connect gram-verify-net gram-verify-nginx
for i in $(seq 1 60); do
 if [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18083/api/categories)" = 200 ]; then echo 'Candidate stage ready on localhost:18083'; exit 0; fi
 sleep 1
done
echo 'Stage did not become ready; see artifacts and container logs'; exit 1
