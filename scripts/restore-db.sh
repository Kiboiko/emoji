#!/usr/bin/env bash
#
# Восстановление базы из резервной копии.
#
#   ./scripts/restore-db.sh backups/marketplace_20260917_033000.sql.gz
#
# ВНИМАНИЕ: содержимое текущей базы будет заменено. Скрипт спрашивает
# подтверждение и перед накатом делает копию того, что есть сейчас, — чтобы
# ошибка в выборе файла не стоила данных.
#
# Проверять восстановление нужно регулярно, а не в день аварии: дамп, который
# ни разу не разворачивали, ничего не гарантирует. Безопасный способ —
# развернуть копию в отдельную базу:
#
#   TARGET_DB=marketplace_restore_test ./scripts/restore-db.sh <файл>

set -euo pipefail

cd "$(dirname "$0")/.."

DUMP="${1:-}"
if [[ -z "$DUMP" ]]; then
    echo "Укажите файл дампа: $0 backups/marketplace_YYYYMMDD_HHMMSS.sql.gz" >&2
    exit 1
fi
if [[ ! -f "$DUMP" ]]; then
    echo "Файл не найден: $DUMP" >&2
    exit 1
fi
if ! gzip -t "$DUMP" 2>/dev/null; then
    echo "Файл повреждён (не проходит проверку gzip): $DUMP" >&2
    exit 1
fi

# Точечное чтение вместо source: см. пояснение в backup-db.sh
env_value() {
    [[ -f .env ]] || return 0
    local line
    line="$(grep -m1 "^$1=" .env || true)"
    line="${line#*=}"
    line="${line%\"}"; line="${line#\"}"
    line="${line%\'}"; line="${line#\'}"
    printf '%s' "$line"
}

DB_USER="${DB_USER:-$(env_value DB_USER)}"
DB_USER="${DB_USER:-marketplace_user}"
SOURCE_DB="${DB_NAME:-$(env_value DB_NAME)}"
SOURCE_DB="${SOURCE_DB:-marketplace}"
TARGET_DB="${TARGET_DB:-$SOURCE_DB}"
SERVICE="postgres"

echo "Дамп:      $DUMP"
echo "База:      $TARGET_DB"
if [[ "$TARGET_DB" == "$SOURCE_DB" ]]; then
    echo
    echo "Это РАБОЧАЯ база. Её текущее содержимое будет заменено."
fi
read -r -p "Продолжить? Введите yes: " CONFIRM
[[ "$CONFIRM" == "yes" ]] || { echo "Отменено"; exit 1; }

# Страховка: копия текущего состояния перед накатом
SAFETY="backups/pre-restore_$(date +%Y%m%d_%H%M%S).sql.gz"
mkdir -p backups
echo "Сохраняю текущее состояние в $SAFETY"
docker compose exec -T "$SERVICE" \
    pg_dump -U "$DB_USER" -d "$TARGET_DB" --clean --if-exists 2>/dev/null \
    | gzip -9 > "$SAFETY" || echo "  (база пуста или не существует — пропускаю)"

# Отдельная база для проверки создаётся на лету
if [[ "$TARGET_DB" != "$SOURCE_DB" ]]; then
    echo "Создаю базу $TARGET_DB"
    docker compose exec -T "$SERVICE" \
        psql -U "$DB_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS \"$TARGET_DB\";" \
        -c "CREATE DATABASE \"$TARGET_DB\" OWNER \"$DB_USER\";"
fi

echo "Восстанавливаю..."
# ON_ERROR_STOP: без него psql проглатывает ошибки и заканчивает с кодом 0,
# оставляя базу наполовину восстановленной
gunzip -c "$DUMP" | docker compose exec -T "$SERVICE" \
    psql -U "$DB_USER" -d "$TARGET_DB" -v ON_ERROR_STOP=1 --quiet

echo
echo "Готово. Проверка:"
docker compose exec -T "$SERVICE" psql -U "$DB_USER" -d "$TARGET_DB" -t -c "
    SELECT 'пользователей: ' || (SELECT count(*) FROM users)
        || ', заказов: '     || (SELECT count(*) FROM orders)
        || ', сделок: '      || (SELECT count(*) FROM deals)
        || ', проводок: '    || (SELECT count(*) FROM ledger_entries);
"

echo
echo "Копия состояния до восстановления: $SAFETY"
if [[ "$TARGET_DB" == "$SOURCE_DB" ]]; then
    echo "Перезапустите бэкенд: docker compose restart backend"
fi
