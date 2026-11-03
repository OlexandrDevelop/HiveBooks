#!/bin/bash
set -euo pipefail
cd /home/frappe/frappe-bench
: "${SITE_NAME:?Set SITE_NAME}" "${DB_ROOT_PASSWORD:?Set DB_ROOT_PASSWORD}" "${ADMIN_PASSWORD:?Set ADMIN_PASSWORD}"
DB_TYPE="${DB_TYPE:-mariadb}"
case "$DB_TYPE" in
    mariadb) DB_PORT=3306 ;;
    postgres) DB_PORT=5432 ;;
    *) echo 'Invalid DB_TYPE (mariadb or postgres)' >&2; exit 1 ;;
esac
[[ "$SITE_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || { echo 'Invalid SITE_NAME' >&2; exit 1; }
mkdir -p sites/assets
# bench init/build creates absolute symlinks; nginx uses an independent image.
# Replace only those links, never uploaded site files.
find sites/assets -maxdepth 1 -type l -delete
cp -a /home/frappe/image-assets/. sites/assets/
# owner_custom: the owner's own app (see CUSTOMIZE.md); present when the image was built with owner_app/
APPS=("$CONFIGURATION_APP")
[ ! -d apps/owner_custom ] || APPS+=(owner_custom)
printf 'frappe\n' > sites/apps.txt
printf '%s\n' "${APPS[@]}" >> sites/apps.txt
bench set-config -g db_host db
bench set-config -gp db_port "$DB_PORT"
bench set-config -g redis_cache redis://redis-cache:6379
bench set-config -g redis_queue redis://redis-queue:6379
bench set-config -g redis_socketio redis://redis-queue:6379
bench set-config -gp socketio_port 9000
if [ ! -f "sites/$SITE_NAME/site_config.json" ]; then
    if [ "$DB_TYPE" = postgres ]; then
        bench new-site "$SITE_NAME" --db-type postgres --db-host db --db-port 5432 \
            --db-root-username postgres --db-root-password "$DB_ROOT_PASSWORD" \
            --admin-password "$ADMIN_PASSWORD"
    else
        bench new-site "$SITE_NAME" --db-type mariadb --db-host db \
            --db-root-password "$DB_ROOT_PASSWORD" --admin-password "$ADMIN_PASSWORD" \
            --mariadb-user-host-login-scope='%'
    fi
fi
# install-app is skipped on subsequent deployments; migration always runs.
for app in "${APPS[@]}"; do
    if ! bench --site "$SITE_NAME" list-apps --format json | APP="$app" python -c 'import json,os,sys; sys.exit(os.environ["APP"] not in json.load(sys.stdin).get(os.environ["SITE_NAME"], []))'; then
        bench --site "$SITE_NAME" install-app "$app"
    fi
done
# dev mode (./install.sh --dev): DocTypes edited in the UI are written to the mounted checkout
bench set-config -gp developer_mode "${DEV_MODE:-0}"
bench --site "$SITE_NAME" migrate
# the stock Frappe setup wizard is completed without questions; the site is fixed to one language
prepare=(bench --site "$SITE_NAME" beeone prepare-site --language "${SITE_LANGUAGE:-uk}")
[ -z "${SITE_COUNTRY:-}" ] || prepare+=(--country "$SITE_COUNTRY")
[ -z "${SITE_TIME_ZONE:-}" ] || prepare+=(--time-zone "$SITE_TIME_ZONE")
[ -z "${SITE_CURRENCY:-}" ] || prepare+=(--currency "$SITE_CURRENCY")
"${prepare[@]}"
# demo data only on request; the first-run screen of the site offers it otherwise
if [ "${LOAD_DEMO:-0}" = 1 ]; then
    bench --site "$SITE_NAME" beeone demo --app "$CONFIGURATION_APP" --if-allowed
fi
bench --site "$SITE_NAME" enable-scheduler
bench --site "$SITE_NAME" set-maintenance-mode off
printf 'Ready: %s (%s)\n' "$SITE_NAME" "$CONFIGURATION_APP"
