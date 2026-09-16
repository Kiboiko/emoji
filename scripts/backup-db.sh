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
    # Снимаем обрамляющие кавычки, если они есть
    line="${line%\"}"; line="${line#\"}"
    line="${line%\'}"; line="${line#\'}"
    printf '%s' "$line"
}

DB_NAME="${DB_NAME:-$(env_value DB_NAME)}"
DB_NAME="${DB_NAME:-marketplace}"
DB_USER="${DB_USER:-$(env_value DB_USER)}"
DB_USER="${DB_USER:-marketplace_user}"

mkdir -p "$BACKUP_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="$BACKUP_DIR/${DB_NAME}_${STAMP}.sql.gz"

echo "[$(date '+%F %T')] Создаю дамп $DB_NAME -> $TARGET"

# --clean --if-exists: дамп можно накатить на существующую базу
# Пишем во временный файл и переименовываем только после успеха, иначе
# прерванный дамп остался бы в каталоге и выглядел как рабочая копия
TMP="${TARGET}.part"
docker compose exec -T "$SERVICE" \
    pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
    | gzip -9 > "$TMP"

# Пустой или обрезанный дамп — признак сбоя, а не повод его сохранить
if [[ ! -s "$TMP" ]] || ! gzip -t "$TMP" 2>/dev/null; then
    rm -f "$TMP"
    echo "ОШИБКА: дамп повреждён или пуст, файл удалён" >&2
    exit 1
fi

mv "$TMP" "$TARGET"
SIZE="$(du -h "$TARGET" | cut -f1)"
echo "[$(date '+%F %T')] Готово: $TARGET ($SIZE)"

# Ротация
DELETED="$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f -mtime "+$KEEP_DAYS" -print -delete | wc -l)"
if [[ "$DELETED" -gt 0 ]]; then
    echo "Удалено копий старше $KEEP_DAYS дней: $DELETED"
fi

echo "Всего копий: $(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f | wc -l)"
