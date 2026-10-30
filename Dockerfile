# syntax=docker/dockerfile:1
FROM frappe/bench@sha256:c035a1de96da6766069a965617440fd2e0220b0702c5ee4fca611b55906c12ed AS build
ARG BEEONE_REPOSITORY=https://github.com/OlexandrDevelop/beeone.git
ARG BEEONE_REF=beeone-16
ARG BEEONE_COMMIT=d43723333c9c36bea86c16a3c09664485acfcdf2
USER frappe
RUN bench init --frappe-path "$BEEONE_REPOSITORY" --frappe-branch "$BEEONE_REF" \
    --no-procfile --no-backups --skip-redis-config-generation /home/frappe/frappe-bench
WORKDIR /home/frappe/frappe-bench
RUN git -C apps/frappe fetch --quiet origin "$BEEONE_REF" && \
    git -C apps/frappe checkout --quiet --detach "$BEEONE_COMMIT"
ARG APP_NAME
COPY --chown=frappe:frappe . /tmp/configuration
RUN test "$APP_NAME" = ua_accounting -o "$APP_NAME" = ua_trade && \
    cp -a /tmp/configuration "apps/$APP_NAME" && \
    ./env/bin/pip install -e "apps/$APP_NAME" && \
    printf '\n%s\n' "$APP_NAME" >> sites/apps.txt && \
    bench build --app "$APP_NAME" && \
    ./env/bin/python -c "import shutil; shutil.copytree('sites/assets', '/home/frappe/image-assets', ignore=shutil.ignore_patterns('node_modules'))"
COPY --chown=frappe:frappe deploy/bootstrap.sh /home/frappe/bootstrap.sh
COPY --chown=frappe:frappe deploy/demo.py /home/frappe/frappe-bench/apps/${APP_NAME}/${APP_NAME}/deployment_demo.py
ENV CONFIGURATION_APP=$APP_NAME
EXPOSE 8000 9000
CMD ["/home/frappe/frappe-bench/env/bin/gunicorn", "--chdir=/home/frappe/frappe-bench/sites", "--bind=0.0.0.0:8000", "--workers=2", "--threads=4", "--worker-class=gthread", "--timeout=120", "frappe.app:application"]
