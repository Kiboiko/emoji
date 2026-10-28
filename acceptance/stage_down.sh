docker rm -f mp-acc-nginx mp-acc-backend mp-acc-db > /dev/null 2>&1
docker network rm mp-acc-net > /dev/null 2>&1
docker rmi mp-acc-backend-img > /dev/null 2>&1
rm -rf /opt/acc
echo "stage removed:"
docker ps -a --format '{{.Names}}' | grep -c '^mp-acc-' || true
ls /opt/acc 2>&1 | head -1
docker compose -f /opt/marketplace/docker-compose.yml ps --format '{{.Service}} {{.Status}}' < /dev/null
