# syntax=docker/dockerfile:1
# Empty unless a local clone of the platform is given: docker build --build-context beeone=DIR (see compose.local-beeone.yaml)
FROM scratch AS beeone
FROM frappe/bench@sha256:c035a1de96da6766069a965617440fd2e0220b0702c5ee4fca611b55906c12ed AS build
ARG BEEONE_REPOSITORY=https://github.com/OlexandrDevelop/beeone.git
ARG BEEONE_REF=beeone-16
USER frappe
RUN --mount=from=beeone,target=/beeone-src \
    if [ -f /beeone-src/frappe/__init__.py ]; then \
        git config --global --add safe.directory '*' && \
        bench init --frappe-path /beeone-src --frappe-branch "$BEEONE_REF" \
            --no-procfile --no-backups --skip-redis-config-generation /home/frappe/frappe-bench; \
    else \
        bench init --frappe-path "$BEEONE_REPOSITORY" --frappe-branch "$BEEONE_REF" \
            --no-procfile --no-backups --skip-redis-config-generation /home/frappe/frappe-bench; \
    fi
WORKDIR /home/frappe/frappe-bench
ARG APP_NAME
COPY --chown=frappe:frappe . /tmp/configuration
RUN test "$APP_NAME" = ua_accounting -o "$APP_NAME" = ua_trade && \
    cp -a /tmp/configuration "apps/$APP_NAME" && \
    ./env/bin/pip install -e "apps/$APP_NAME" && \
    printf '\n%s\n' "$APP_NAME" >> sites/apps.txt && \
    bench build --app "$APP_NAME" && \
    if [ -f "apps/$APP_NAME/owner_app/pyproject.toml" ]; then \
        ln -s "$APP_NAME/owner_app" apps/owner_custom && \
        ./env/bin/pip install -e apps/owner_custom && \
        printf '%s\n' owner_custom >> sites/apps.txt && \
        bench build --app owner_custom; \
    fi && \
    ./env/bin/python -c "import shutil; shutil.copytree('sites/assets', '/home/frappe/image-assets', ignore=shutil.ignore_patterns('node_modules'))"
COPY --chown=frappe:frappe deploy/bootstrap.sh /home/frappe/bootstrap.sh
ENV CONFIGURATION_APP=$APP_NAME
EXPOSE 8000 9000
CMD ["/home/frappe/frappe-bench/env/bin/gunicorn", "--chdir=/home/frappe/frappe-bench/sites", "--bind=0.0.0.0:8000", "--workers=2", "--threads=4", "--worker-class=gthread", "--timeout=120", "frappe.app:application"]
