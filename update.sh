#!/usr/bin/env bash
# HiveBooks: оновлення з вихідного репозиторію (upstream) зі збереженням ваших змін.
#   ./update.sh                       підтягує upstream/main, зливає у вашу гілку, перебудовує й виконує міграції
#   ./update.sh --branch main --upstream URL --no-backup
# Коди виходу: 0 успіх, 1 не виконано умови, 2 конфлікт (злиття скасовано), 3 помилка встановлення після злиття.
set -uo pipefail
cd "$(dirname "$0")"

UPSTREAM_URL="https://github.com/OlexandrDevelop/HiveBooks.git"; BRANCH="main"; BACKUP=1
while [ $# -gt 0 ]; do
  case "$1" in
    --upstream) UPSTREAM_URL="${2:?--upstream URL}"; shift 2 ;;
    --branch) BRANCH="${2:?--branch ГІЛКА}"; shift 2 ;;
    --no-backup) BACKUP=0; shift ;;
    -h|--help) sed -n 2,5p "$0"; exit 0 ;;
    *) echo "Помилка: невідомий параметр $1" >&2; exit 1 ;;
  esac
done
fail() { echo "Помилка: $*" >&2; exit 1; }

command -v git >/dev/null || fail "git не знайдено."
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "це не git-репозиторій. Склонуйте репозиторій (git clone), а не завантажуйте архів."
git symbolic-ref -q HEAD >/dev/null || fail "ви не на гілці (detached HEAD). Перейдіть на свою гілку: git switch main"
[ ! -f "$(git rev-parse --git-dir)/MERGE_HEAD" ] || fail "попереднє злиття не завершене. Завершіть його (git add … && git commit) або скасуйте: git merge --abort"
dirty="$(git status --porcelain --untracked-files=no)"
if [ -n "$dirty" ]; then
  echo "$dirty" >&2
  fail "є незафіксовані зміни (список вище). Зробіть commit (git add -A && git commit -m 'Мої зміни') або git stash, потім запустіть ./update.sh знову."
fi

if ! git remote | grep -qx upstream; then
  echo "Віддаленого репозиторію upstream немає. Додаю: $UPSTREAM_URL"
  git remote add upstream "$UPSTREAM_URL" || fail "не вдалося додати upstream."
fi
echo "Отримую зміни з upstream..."
git fetch upstream || fail "не вдалося отримати upstream. Перевірте мережу та доступ до репозиторію (для приватного репозиторію потрібен доступ на читання)."
git rev-parse --verify -q "upstream/$BRANCH" >/dev/null || fail "у upstream немає гілки $BRANCH (параметр --branch)."

before="$(git rev-parse HEAD)"
if git merge-base --is-ancestor "upstream/$BRANCH" HEAD; then
  echo "Нових змін немає: ваша гілка вже містить upstream/$BRANCH."
  exit 0
fi

have_site=0
if [ -f .env ]; then
  set -a; . ./.env; set +a
  if [ "$BACKUP" = 1 ] && docker compose ps --status running --services 2>/dev/null | grep -qx backend; then
    echo "Резервна копія сайту..."
    docker compose exec -T backend bench --site "$SITE_NAME" backup || fail "не вдалося створити резервну копію. Нічого не змінено. (Пропустити: --no-backup)"
    echo "Резервна копія лежить у томі sites, каталог sites/$SITE_NAME/private/backups у контейнері backend."
  fi
  have_site=1
fi

GIT_MERGE_AUTOEDIT=no git merge --no-edit "upstream/$BRANCH"
if [ $? -ne 0 ]; then
  echo >&2
  echo "КОНФЛІКТ: ваші зміни та зміни upstream торкаються тих самих рядків у файлах:" >&2
  git diff --name-only --diff-filter=U | sed 's/^/  - /' >&2
  git merge --abort
  echo >&2
  echo "Злиття скасовано. Сайт працює як раніше, ваші файли та дані не змінено." >&2
  echo "Як вирішити конфлікт:" >&2
  echo "  1. git merge upstream/$BRANCH" >&2
  echo "  2. Відкрийте файли зі списку в IDE, виправте блоки між <<<<<<< та >>>>>>> і залиште потрібний код." >&2
  echo "     (У режимі розробки сайт може показувати помилки, доки в файлах є ці позначки.)" >&2
  echo "  3. git add <файли> && git commit" >&2
  echo "  4. ./update.sh" >&2
  echo "Порада: власні зміни тримайте в каталозі owner_app/ (див. CUSTOMIZE.md): там конфліктів не буває." >&2
  exit 2
fi

if [ "$have_site" = 0 ]; then
  echo "Код оновлено. Локального встановлення (.env) немає: для Easypanel виконайте git push і натисніть Deploy."
else
  echo "Перебудовую та виконую міграції..."
  if ! ./install.sh; then
    echo >&2
    echo "Помилка під час встановлення після злиття. Дані не видалялися." >&2
    echo "Повернути код: git reset --hard $before && ./install.sh" >&2
    echo "Відновити дані з резервної копії (якщо потрібно): docker compose exec backend bench --site $SITE_NAME restore <файл .sql.gz з sites/$SITE_NAME/private/backups>" >&2
    exit 3
  fi
fi
echo "Оновлено. Нові коміти:"
git log --oneline "$before..HEAD"
echo "Нагадування: update.sh нічого не надсилає. Збережіть у своєму репозиторії: git push origin $(git symbolic-ref --short HEAD)"
