#!/usr/bin/env bash
# Створює власний застосунок owner_custom (каталог owner_app/) для ваших змін. Виконується один раз.
set -euo pipefail
cd "$(dirname "$0")"
[ ! -e owner_app ] || { echo "Помилка: каталог owner_app вже існує, нічого не змінено." >&2; exit 1; }
cp -r deploy/owner_app_template owner_app
echo "Створено owner_app/ (застосунок owner_custom)."
echo "Далі:"
echo "  1. ./install.sh            (встановить застосунок на сайт)"
echo "  2. git add owner_app && git commit -m 'Власний застосунок'"
echo "Детальніше: CUSTOMIZE.md"
