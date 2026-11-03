#!/usr/bin/env bash
# HiveBooks: встановлення однією командою.
#   ./install.sh                                  питає тип бази, домен і пароль
#   ./install.sh --db postgres --site erp.example.com --admin-password '...' --yes
# Повторний запуск нічого не питає: перебудовує образ і оновлює сайт (для оновлень з GitHub: ./update.sh).
#   ./install.sh --dev     режим розробки: каталог із кодом підключається до контейнерів (лише локально)
#   ./install.sh --prod    повернення до звичайного режиму (код береться з образу)
set -euo pipefail
cd "$(dirname "$0")"

DB=""; SITE=""; ADMIN_PASSWORD_ARG=""; HTTP_PORT_ARG=""; PROJECT_ARG=""; BEEONE_CONTEXT_ARG="${BEEONE_CONTEXT:-}"; YES=0; MODE=""
die() { echo "Помилка: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB="${2:?--db mariadb|postgres}"; shift 2 ;;
    --site) SITE="${2:?--site НАЗВА}"; shift 2 ;;
    --admin-password) ADMIN_PASSWORD_ARG="${2:?--admin-password ПАРОЛЬ}"; shift 2 ;;
    --http-port) HTTP_PORT_ARG="${2:?--http-port ПОРТ}"; shift 2 ;;
    --project) PROJECT_ARG="${2:?--project НАЗВА}"; shift 2 ;;
    --beeone-context) BEEONE_CONTEXT_ARG="${2:?--beeone-context КАТАЛОГ}"; shift 2 ;;
    --dev) MODE=dev; shift ;;
    --prod) MODE=prod; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) sed -n 2,9p "$0"; exit 0 ;;
    *) die "невідомий параметр $1" ;;
  esac
done

command -v docker >/dev/null || die "Docker не знайдено. Встановіть Docker: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "Потрібен Docker Compose v2 (команда 'docker compose')."

random() { head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }

if [ ! -f .env ]; then
  [ -n "$DB" ] || {
    [ "$YES" = 1 ] && DB=mariadb || {
      echo "База даних:"; echo "  1) MariaDB (типово)"; echo "  2) PostgreSQL"
      read -r -p "Оберіть 1 або 2 [1]: " choice
      case "${choice:-1}" in 1) DB=mariadb ;; 2) DB=postgres ;; *) die "оберіть 1 або 2" ;; esac
    }
  }
  case "$DB" in mariadb|postgres) ;; *) die "--db: mariadb або postgres" ;; esac
  [ -n "$SITE" ] || { [ "$YES" = 1 ] && SITE=localhost || { read -r -p "Ім'я сайту (домен) [localhost]: " SITE; SITE="${SITE:-localhost}"; }; }
  [[ "$SITE" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || die "ім'я сайту: літери, цифри, крапки й дефіси"
  PASSWORD="$ADMIN_PASSWORD_ARG"; GENERATED=0
  if [ -z "$PASSWORD" ]; then
    if [ "$YES" = 1 ]; then PASSWORD="$(random 16)"; GENERATED=1
    else
      read -r -s -p "Пароль адміністратора (Enter - створити випадковий): " PASSWORD; echo
      if [ -z "$PASSWORD" ]; then PASSWORD="$(random 16)"; GENERATED=1
      else read -r -s -p "Повторіть пароль: " again; echo; [ "$PASSWORD" = "$again" ] || die "паролі не збігаються"; fi
    fi
  fi
  case "$PASSWORD" in *[\'\"\\\$\ ]*) die "у паролі не можна лапки, пробіл, \\ та \$" ;; esac
  compose_file=$([ "$DB" = postgres ] && echo docker-compose.postgres.yml || echo docker-compose.yml)
  umask 077
  {
    echo "SITE_NAME=$SITE"
    echo "DB_TYPE=$DB"
    echo "DB_ROOT_PASSWORD=$(random 24)"
    echo "ADMIN_PASSWORD=$PASSWORD"
    echo "HTTP_PORT=${HTTP_PORT_ARG:-8080}"
    echo "LOAD_DEMO=0"
    echo "BEEONE_REF=${BEEONE_REF:-beeone-16}"
    [ -z "$PROJECT_ARG" ] || echo "COMPOSE_PROJECT_NAME=$PROJECT_ARG"
    echo "COMPOSE_FILE=$compose_file:compose.ports.yaml"
  } > .env
  [ "$GENERATED" = 0 ] || echo "Пароль адміністратора (збережіть, він показується один раз): $PASSWORD"
else
  echo "Знайдено .env: оновлення наявного встановлення (тип бази не змінюється)."
fi

if [ -n "$BEEONE_CONTEXT_ARG" ]; then
  grep -q '^BEEONE_CONTEXT=' .env || echo "BEEONE_CONTEXT=$BEEONE_CONTEXT_ARG" >> .env
  grep -q 'compose.local-beeone.yaml' .env || sed -i 's|^COMPOSE_FILE=.*|&:compose.local-beeone.yaml|' .env
fi

if [ "$MODE" = dev ]; then
  grep -q '^DEV_MODE=' .env || echo "DEV_MODE=1" >> .env
  grep -q '^HTTP_HOST_IP=' .env || echo "HTTP_HOST_IP=127.0.0.1" >> .env
  grep -q 'compose.dev.yaml' .env || sed -i 's|^COMPOSE_FILE=.*|&:compose.dev.yaml|' .env
  if [ "$(uname -s)" = Linux ] && [ "$(id -u)" != 1000 ]; then
    echo "Увага: ваш користувач має uid $(id -u), а контейнери пишуть від uid 1000. Щоб зміни з інтерфейсу потрапляли у файли, виконайте:" >&2
    echo "  setfacl -R -m u:1000:rwX -m d:u:1000:rwX ." >&2
  fi
  echo "Режим розробки: сайт доступний лише на цьому комп'ютері (127.0.0.1). Не відкривайте його в мережу."
elif [ "$MODE" = prod ]; then
  sed -i '/^DEV_MODE=/d;/^HTTP_HOST_IP=/d;s|:compose\.dev\.yaml||' .env
fi

docker compose up -d --build || { echo "Не вдалося запустити. Журнал ініціалізації:" >&2; docker compose logs init >&2 || true; exit 1; }

# nginx must not keep the address of a replaced backend container
docker compose restart frontend >/dev/null

set -a; . ./.env; set +a
command -v curl >/dev/null || { echo "Запущено (curl не знайдено, перевірку відповіді пропущено): http://localhost:${HTTP_PORT:-8080}"; exit 0; }
echo "Очікуємо відповідь сайту..."
for _ in $(seq 1 90); do
  if curl -fsS "http://localhost:${HTTP_PORT:-8080}/api/method/ping" >/dev/null 2>&1; then
    echo "Готово: http://localhost:${HTTP_PORT:-8080} (сайт $SITE_NAME), користувач Administrator."
    echo "Усі дані зберігаються в томах Docker. Не виконуйте 'docker compose down -v' на робочому сайті."
    exit 0
  fi
  sleep 2
done
echo "Сайт не відповів за 3 хвилини. Журнал: docker compose logs" >&2
exit 1
