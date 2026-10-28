cd /opt/marketplace
DBU=$(tr -d '\r' < .env | grep '^DB_USER=' | cut -d= -f2)
DBN=$(tr -d '\r' < .env | grep '^DB_NAME=' | cut -d= -f2)
export DATABASE_URL="postgresql+asyncpg://$DBU:t@mp-acc-db:5432/$DBN"
echo "== data for the load test"
TOK=$(docker run --rm --network mp-acc-net -e PYTHONPATH=/app -w /app -e DATABASE_URL -e SECRET_KEY=acc-secret-key-for-staging-only -v /opt/acc/code:/acc:ro --entrypoint python mp-acc-backend-img /acc/mint_tokens.py 30)
CATS=$(curl -s "http://127.0.0.1:18080/api/categories" | python3 -c "import json,sys; print(','.join(c['id'] for c in json.load(sys.stdin)))")
PRODS=$(curl -s "http://127.0.0.1:18080/api/products?limit=100&lang=ru" | python3 -c "import json,sys; print(','.join(p['id'] for p in json.load(sys.stdin)))")
echo "tokens: $(echo $TOK | tr ',' '\n' | wc -l), categories: $(echo $CATS | tr ',' '\n' | wc -l), products: $(echo $PRODS | tr ',' '\n' | wc -l), catalog size: $(curl -sI 'http://127.0.0.1:18080/api/products?limit=1' | grep -ci x-has-more) has-more header"
echo "== server CPU sampled in the middle of each phase"
( sleep 40;  echo "[phase real300 @40s]";   docker stats --no-stream --format '  {{.Name}} cpu={{.CPUPerc}}' mp-acc-backend mp-acc-db mp-acc-nginx
  sleep 60;  echo "[phase burst/stress @100s]"; docker stats --no-stream --format '  {{.Name}} cpu={{.CPUPerc}}' mp-acc-backend mp-acc-db mp-acc-nginx
  sleep 33;  echo "[phase rate500 @133s]";   docker stats --no-stream --format '  {{.Name}} cpu={{.CPUPerc}}' mp-acc-backend mp-acc-db mp-acc-nginx
  sleep 20;  echo "[phase rate1000 @153s]"; docker stats --no-stream --format '  {{.Name}} cpu={{.CPUPerc}}' mp-acc-backend mp-acc-db mp-acc-nginx
  sleep 20;  echo "[phase rate2000 @173s]"; docker stats --no-stream --format '  {{.Name}} cpu={{.CPUPerc}}' mp-acc-backend mp-acc-db mp-acc-nginx ) > /tmp/k6_cpu.txt 2>&1 &
echo "== k6 (real users, stress, then fixed request rates)"
docker run --rm --network mp-acc-net -v /opt/acc/code:/acc:ro -e BASE=http://mp-acc-nginx -e TOKENS="$TOK" -e CATS="$CATS" -e PRODS="$PRODS" grafana/k6 run --quiet /acc/load.js 2>&1 | grep -vE '^\s*$|running|✓ |^ +time=|level=' | head -150
wait
echo "== CPU during phases"; cat /tmp/k6_cpu.txt
echo "== backend errors during the run"
docker logs mp-acc-backend --since 5m 2>&1 | grep -cE 'Traceback|ERROR '
echo "== nginx 5xx during the run"
docker logs mp-acc-nginx --since 5m 2>&1 | grep -cE '" 5[0-9][0-9] '
exit 0
