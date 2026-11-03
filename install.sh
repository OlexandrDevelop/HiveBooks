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

OLD_PORT=""; [ -f .env ] && OLD_PORT="$(sed -n 's/^HTTP_PORT=//p' .env | tail -n 1)"
OLD_PORT="${OLD_PORT:-8080}"
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
  # volumes of an earlier install of this project keep their site: its admin password and data win over this run
  project="${PROJECT_ARG:-${COMPOSE_PROJECT_NAME:-$(basename "$PWD" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_\n-' '_' | sed 's/^[-_]*//')}}"
  old_volumes="$(docker volume ls -q --filter "label=com.docker.compose.project=$project" 2>/dev/null | tr '\n' ' ')"
  if [ -n "$old_volumes" ]; then
    echo "Увага: знайдено томи Docker попереднього встановлення (проєкт $project): $old_volumes" >&2
    echo "  Сайт, дані й пароль адміністратора беруться з них, а не з цього запуску: вхід з новим паролем буде відхилено." >&2
    echo "  Пароль скинете так: docker compose exec backend bench --site <сайт> set-admin-password '<пароль>'" >&2
    echo "  Чисте встановлення (ВИДАЛЯЄ дані): docker compose -p $project down -v" >&2
  fi
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

env_get() { sed -n "s/^$1=//p" .env | tail -n 1; }
env_set() { if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi; }

# 0 when something listens on TCP port $1 (ss, then lsof, then a bash /dev/tcp probe: Linux, macOS, WSL2)
port_busy() {
  local port="$1" host
  host="$(env_get HTTP_HOST_IP)"; host="${host:-0.0.0.0}"; [ "$host" = 0.0.0.0 ] && host=127.0.0.1
  if command -v ss >/dev/null 2>&1; then
    ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${port}$" && return 0 || return 1
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && return 0 || return 1
  fi
  (exec 3<>"/dev/tcp/$host/$port") >/dev/null 2>&1 && return 0 || return 1
}

# name of the program holding port $1, empty when unknown
port_owner() {
  local port="$1" out=""
  if command -v ss >/dev/null 2>&1; then
    out="$(ss -ltnpH 2>/dev/null | awk -v p=":$port" '$4 ~ p"$" {print $NF}' | sed -n 's/.*users:(("\([^"]*\)",pid=\([0-9]*\).*/\1 (pid \2)/p' | head -n 1)"
  fi
  if [ -z "$out" ] && command -v lsof >/dev/null 2>&1; then
    out="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1 " (pid " $2 ")"}')"
  fi
  echo "$out"
}

next_free_port() { local p=$(( $1 + 1 )); while port_busy "$p"; do p=$(( p + 1 )); done; echo "$p"; }

if [ -n "$HTTP_PORT_ARG" ]; then
  [[ "$HTTP_PORT_ARG" =~ ^[0-9]+$ ]] && [ "$HTTP_PORT_ARG" -ge 1 ] && [ "$HTTP_PORT_ARG" -le 65535 ] || die "--http-port: число від 1 до 65535"
  [ "$(env_get HTTP_PORT)" = "$HTTP_PORT_ARG" ] || { env_set HTTP_PORT "$HTTP_PORT_ARG"; echo "Порт сайту змінено на $HTTP_PORT_ARG (.env)."; }
fi

# Is the port held by the program that is not this project's own running frontend?
PORT="$(env_get HTTP_PORT)"; PORT="${PORT:-8080}"
own_frontend=0
[ -n "$(docker compose ps --status running -q frontend 2>/dev/null)" ] && [ "$PORT" = "$OLD_PORT" ] && own_frontend=1
if [ "$own_frontend" = 0 ] && port_busy "$PORT"; then
  owner="$(port_owner "$PORT")"
  echo "Порт $PORT уже зайнятий іншою програмою${owner:+: $owner}." >&2
  [ "$YES" = 1 ] && die "звільніть порт $PORT або оберіть інший: ./install.sh --http-port ПОРТ --yes"
  while :; do
    suggest="$(next_free_port "$PORT")"
    read -r -p "Вільний порт [$suggest] (Enter - прийняти або введіть свій): " answer
    answer="${answer:-$suggest}"
    if ! { [[ "$answer" =~ ^[0-9]+$ ]] && [ "$answer" -ge 1 ] && [ "$answer" -le 65535 ]; }; then echo "Потрібне число від 1 до 65535." >&2; PORT="$suggest"; continue; fi
    if port_busy "$answer"; then echo "Порт $answer теж зайнятий." >&2; PORT="$answer"; continue; fi
    PORT="$answer"; break
  done
  env_set HTTP_PORT "$PORT"
  echo "Сайт буде на порту $PORT (записано в .env)."
fi

up_log="$(mktemp)"; trap 'rm -f "$up_log"' EXIT
set +e
docker compose up -d --build 2>&1 | tee "$up_log"
up_rc="${PIPESTATUS[0]}"
set -e
if [ "$up_rc" != 0 ]; then
  echo >&2; echo "Не вдалося запустити." >&2
  echo "Помилка Docker:" >&2
  { grep -iE 'error|denied|allocated|in use|failed' "$up_log" || tail -n 10 "$up_log"; } | tail -n 10 | sed 's/^/  /' >&2
  echo "Стан сервісів:" >&2
  docker compose ps -a >&2 || true
  failed=0
  for svc in $(docker compose config --services 2>/dev/null); do
    line="$(docker compose ps -a --format '{{.State}}|{{.ExitCode}}' "$svc" 2>/dev/null | head -n 1)"
    state="${line%%|*}"; code="${line##*|}"
    if [ -z "$line" ]; then why="не створено"
    elif [ "$state" = running ]; then continue
    elif [ "$state" = exited ] && [ "$code" = 0 ]; then continue
    else why="$state, код $code"; fi
    failed=1
    echo "---- $svc ($why): останні рядки журналу ----" >&2
    docker compose logs --tail 40 "$svc" >&2 || true
  done
  [ "$failed" = 1 ] || docker compose logs --tail 40 >&2 || true
  exit 1
fi

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
