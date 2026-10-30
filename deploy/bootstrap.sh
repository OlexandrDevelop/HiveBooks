#!/bin/bash
set -euo pipefail
cd /home/frappe/frappe-bench
: "${SITE_NAME:?Set SITE_NAME}" "${DB_ROOT_PASSWORD:?Set DB_ROOT_PASSWORD}" "${ADMIN_PASSWORD:?Set ADMIN_PASSWORD}"
[[ "$SITE_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || { echo 'Invalid SITE_NAME' >&2; exit 1; }
mkdir -p sites/assets
# bench init/build creates absolute symlinks; nginx uses an independent image.
# Replace only those links, never uploaded site files.
find sites/assets -maxdepth 1 -type l -delete
cp -a /home/frappe/image-assets/. sites/assets/
printf 'frappe\n%s\n' "$CONFIGURATION_APP" > sites/apps.txt
bench set-config -g db_host db
bench set-config -gp db_port 3306
bench set-config -g redis_cache redis://redis-cache:6379
bench set-config -g redis_queue redis://redis-queue:6379
bench set-config -g redis_socketio redis://redis-queue:6379
bench set-config -gp socketio_port 9000
if [ ! -f "sites/$SITE_NAME/site_config.json" ]; then
    bench new-site "$SITE_NAME" --db-type mariadb --db-host db \
        --db-root-password "$DB_ROOT_PASSWORD" --admin-password "$ADMIN_PASSWORD" \
        --mariadb-user-host-login-scope='%'
fi
# install-app is skipped on subsequent deployments; migration always runs.
if ! bench --site "$SITE_NAME" list-apps --format json | python -c 'import json,os,sys; sys.exit(os.environ["CONFIGURATION_APP"] not in json.load(sys.stdin).get(os.environ["SITE_NAME"], []))'; then
    bench --site "$SITE_NAME" install-app "$CONFIGURATION_APP"
fi
bench --site "$SITE_NAME" migrate
if [ "${LOAD_DEMO:-1}" = 1 ]; then
    bench --site "$SITE_NAME" execute "$CONFIGURATION_APP.deployment_demo.run"
fi
bench --site "$SITE_NAME" enable-scheduler
bench --site "$SITE_NAME" set-maintenance-mode off
printf 'Ready: %s (%s)\n' "$SITE_NAME" "$CONFIGURATION_APP"
