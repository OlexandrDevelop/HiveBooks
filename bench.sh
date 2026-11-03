#!/usr/bin/env bash
# Виконує команду bench для вашого сайту: ./bench.sh migrate, ./bench.sh clear-cache, ./bench.sh export-fixtures --app owner_custom
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo "Помилка: немає файлу .env. Спочатку виконайте ./install.sh" >&2; exit 1; }
set -a; . ./.env; set +a
exec docker compose exec backend bench --site "$SITE_NAME" "$@"
