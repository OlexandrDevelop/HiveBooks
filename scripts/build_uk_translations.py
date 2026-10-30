#!/usr/bin/env python3
"""Build the Ukrainian translations of the app.

Sources (later wins):
  1. translations/uk_frappe.csv   user's translation of Frappe (source only, never edited here)
  2. FIXES                        bad lines of that file
  3. translations/uk_app.csv      strings of the app
  4. OVERRIDES                    1C words (Записати, Провести, ...)

Output:
  translations/uk.csv   loaded by Frappe (the app is after frappe, so it wins over Frappe's own uk)
  locale/uk.po          same strings, for translators and `bench compile-po-to-mo`

Run from anywhere:  python3 apps/ua_accounting/scripts/build_uk_translations.py
"""

import csv
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "ua_accounting"
TR = APP / "translations"
PO = APP / "locale" / "uk.po"

# bad lines of uk_frappe.csv
FIXES = {
    "Add": "Додати",
    "Move": "Перемістити",
    "Saved": "Записано",
    "Actions": "Дії",
    "New": "Створити",
}

# 1C words. Key: "source", or ("source", "context").
OVERRIDES = {
    "Save": "Записати",
    "Saving": "Запис",
    "Not Saved": "Не записано",
    "Submit": "Провести",
    "Submitted": "Проведено",
    "Submitting": "Проведення",
    "Draft": "Чернетка",
    "Cancelled": "Скасовано",
    "Amend": "Виправити",
    "Amended From": "Змінено з",
    "New": "Створити",
    "New {0}": "{0} (створення)",
    "Add": "Додати",
    "Add Row": "Додати",
    "Add row": "Додати",
    "Add {0}": "Створити: {0}",
    ("Add {0}", "Primary action in list view"): "Створити: {0}",
    "Add multiple": "Додати кілька",
    "Create a new {0}": "Створити: {0}",
    "New Email": "Новий лист",
    "ID": "Номер",
    ("Message", "Default title of the message dialog"): "Повідомлення",
    "Delete row": "Видалити рядок",
    "Delete all": "Видалити всі",
    "Duplicate rows": "Скопіювати рядки",
    "No rows": "Немає рядків",
    "Search": "Пошук",
    "Search or type a command": "Пошук (Ctrl+F)",
    "Pages": "Сторінки",
    "Notification": "Сповіщення",
    "Notifications": "Сповіщення",
    "Menu": "Ще",
    "Actions": "Дії",
    "Move": "Перемістити",
    "Print": "Друк",
    "Filter": "Відбір",
    "Filters": "Відбір",
    "Sort": "Сортування",
    "No.": "№",
    "Sr": "№",
    "Edit": "Редагувати",
    "Duplicate": "Скопіювати",
    "Assigned To": "Призначено",
    "Created By": "Автор",
    "Tags": "Мітки",
    "Last Updated On": "Змінено",
    "Home": "Головне",
    "Log out": "Вийти",
    "Logout": "Вийти",
    "My Settings": "Мої налаштування",
    "List View": "Список",
    "Report View": "Звіт",
    "Reload List": "Оновити список",
    "Create": "Створити",
    "Close": "Закрити",
    "Cancel": "Скасувати",
    "Delete": "Видалити",
    "Refresh": "Оновити",
    "Settings": "Налаштування",
    "Show Sidebar": "Показати бічну панель",
    "Toggle Sidebar": "Бічна панель",
    "Toggle Theme": "Змінити тему",
    "Clear all filters": "Скинути відбір",
    "descending": "за спаданням",
    "ascending": "за зростанням",
    "Click to sort by {0}": "Сортувати за {0}",
    "Liked by me": "Вподобано мною",
    "Begin typing for results.": "Почніть вводити для пошуку.",
    "Document is in draft state": "Документ не проведено",
    "to navigate": "вибрати",
    "to select": "відкрити",
    "to close": "закрити",
    "to open Global Search": "глобальний пошук",
    "{0} results found": "Знайдено: {0}",
    "No results found": "Нічого не знайдено",
    "You created this": "Ви створили це",
    "You last edited this": "Ви змінили це востаннє",
    "You created this document {0}": "Ви створили цей документ {0}",
    "Show Links": "Показати зв'язки",
    "Copy to Clipboard": "Копіювати",
    "Remind Me": "Нагадати",
    "Remind Me In": "Нагадати через",
    "Undo": "Відмінити",
    "Redo": "Повторити",
    "Customize Quick Filters": "Налаштувати швидкі відбори",
    "DocType": "Тип документа",
    "Edit DocType": "Змінити тип документа",
    "EMail": "Ел. пошта",
    "Email": "Ел. пошта",
    "Advanced Search": "Розширений пошук",
    "Type a reply / comment": "Напишіть коментар",
    "{0} of {1}": "{0} / {1}",
    "Tree View": "Дерево",
    "Tree": "Дерево",
    "Expand/Collapse": "Розгорнути / згорнути",
    "Expand All": "Розгорнути все",
    "Collapse All": "Згорнути все",
}


def read_csv(path):
    out = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[0] or not row[1].strip():
                continue
            out[(row[0], row[2] if len(row) > 2 else "")] = row[1].strip()
    return out


def po_quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def main():
    merged = read_csv(TR / "uk_frappe.csv")
    merged.update({(k, ""): v for k, v in FIXES.items()})
    merged.update(read_csv(TR / "uk_app.csv"))
    merged.update({(k, "") if isinstance(k, str) else k: v for k, v in OVERRIDES.items()})

    # A row with a context is useless when the plain row has the same text (Frappe falls back to it).
    for key in [k for k in merged if k[1] and merged.get((k[0], "")) == merged[k]]:
        del merged[key]

    with (TR / "uk.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        for key in sorted(merged):
            source, context = key
            if context:
                writer.writerow([source, merged[key], context])
            else:
                writer.writerow([source, merged[key]])

    lines = [
        'msgid ""',
        'msgstr ""',
        '"Project-Id-Version: ua_accounting 0.0.1\\n"',
        '"Language: uk\\n"',
        '"MIME-Version: 1.0\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        "",
    ]
    for key in sorted(merged):
        source, context = key
        if context:
            lines.append("msgctxt " + po_quote(context))
        lines.append("msgid " + po_quote(source))
        lines.append("msgstr " + po_quote(merged[key]))
        lines.append("")
    PO.write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(merged)} strings -> {TR / 'uk.csv'}, {PO}")


if __name__ == "__main__":
    main()
