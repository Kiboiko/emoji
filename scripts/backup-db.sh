#!/usr/bin/env bash
#
# Резервная копия базы маркетплейса.
#
# Запускается с хоста, где поднят docker compose. Дамп делается внутри
# контейнера и сразу сжимается, чтобы не держать несжатую копию на диске.
#
# Установка в cron (ежедневно в 3:30):
#   30 3 * * * cd /path/to/marketplace && ./scripts/backup-db.sh >> /var/log/marketplace-backup.log 2>&1
#
# Проверка восстановления — scripts/restore-db.sh. Бэкап, который ни разу не
# восстанавливали, бэкапом не является: см. README, раздел «Бэкапы».

set -euo pipefail
umask 077

cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
SERVICE="postgres"

# Читаем только нужные ключи, а не source .env целиком: значения там бывают
# со скобками и пробелами, на которых source падает, а кроме того source
# выполняет содержимое файла как код.
env_value() {
    [[ -f .env ]] || return 0
    local line
    line="$(grep -m1 "^$1=" .env || true)"
    line="${line#*=}"
    line="${line%$'\r'}"
    # Снимаем обрамляющие кавычки, если они есть
    line="${line%\"}"; line="${line#\"}"
    line="${line%\'}"; line="${line#\'}"
    printf '%s' "$line"
}

DB_NAME="${DB_NAME:-$(env_value DB_NAME)}"
DB_NAME="${DB_NAME:-marketplace}"
DB_USER="${DB_USER:-$(env_value DB_USER)}"
DB_USER="${DB_USER:-marketplace_user}"

[[ "$KEEP_DAYS" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid KEEP_DAYS" >&2; exit 1; }
[[ "$DB_NAME" =~ ^[a-zA-Z0-9_]+$ ]] || { echo "Invalid DB_NAME" >&2; exit 1; }
mkdir -p "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.backup.lock"
flock -n 9 || { echo "Backup already running" >&2; exit 1; }

STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="$BACKUP_DIR/${DB_NAME}_${STAMP}.sql.gz"

echo "[$(date '+%F %T')] Создаю дамп $DB_NAME -> $TARGET"

# --clean --if-exists: дамп можно накатить на существующую базу
# Пишем во временный файл и переименовываем только после успеха, иначе
# прерванный дамп остался бы в каталоге и выглядел как рабочая копия
TMP="${TARGET}.part"
trap 'rm -f -- "$TMP"' EXIT
docker compose -f docker-compose.yml exec -T "$SERVICE" \
    pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
    < /dev/null | gzip -9 > "$TMP"

# Пустой или обрезанный дамп — признак сбоя, а не повод его сохранить
if [[ ! -s "$TMP" ]] || ! gzip -t "$TMP" 2>/dev/null; then
    rm -f "$TMP"
    echo "ОШИБКА: дамп повреждён или пуст, файл удалён" >&2
    exit 1
fi

mv "$TMP" "$TARGET"
sha256sum "$TARGET" > "${TARGET}.sha256"
touch "$BACKUP_DIR/.last-success"
SIZE="$(du -h "$TARGET" | cut -f1)"
echo "[$(date '+%F %T')] Готово: $TARGET ($SIZE)"

# Ротация
DELETED="$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f -mtime "+$KEEP_DAYS" -print -delete | wc -l)"
if [[ "$DELETED" -gt 0 ]]; then
    echo "Удалено копий старше $KEEP_DAYS дней: $DELETED"
fi

find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz.sha256" -type f -mtime "+$KEEP_DAYS" -delete

echo "Всего копий: $(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f | wc -l)"
