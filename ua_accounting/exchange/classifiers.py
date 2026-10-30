"""Classifiers УКТЗЕД, КВЕД, ДКПП: load from a `code;description` CSV and search."""

import csv
import io
import re

import frappe
from frappe import _

from ua_accounting.exchange.common import ExchangeError, decode_text

KINDS = {
    "uktzed": ("UA UKTZED", r"\d{4,10}", lambda c: c[:4] if len(c) > 4 else None),
    "kved": ("UA KVED", r"\d{2}(\.\d{2})?", lambda c: c[:2] if "." in c else None),
    "dkpp": ("UA DKPP", r"\d{2}\.\d{2}(\.\d)?", lambda c: c[:5] if c.count(".") == 2 else None),
}


def spec(kind):
    if kind not in KINDS:
        raise ExchangeError(_("Невідомий класифікатор «{0}»").format(kind))
    return KINDS[kind]


def load(kind, data):
    doctype, pattern, parent_of = spec(kind)
    rows = csv.reader(io.StringIO(decode_text(data)), delimiter=";")
    created = updated = 0
    errors, parents = [], set()
    for n, row in enumerate(rows, start=1):
        if not row or not any(c.strip() for c in row):
            continue
        code, description = row[0].strip(), (row[1].strip() if len(row) > 1 else "")
        if not re.fullmatch(pattern, code):
            errors.append({"row": n, "message": _("Код «{0}» не знайдено. Перевірте код у рядку файлу").format(code)})
            continue
        if not description:
            errors.append({"row": n, "message": _("Код «{0}»: немає назви").format(code)})
            continue
        parent = parent_of(code)
        if frappe.db.exists(doctype, code):
            doc = frappe.get_doc(doctype, code)
            doc.update({"description": description, "parent_code": parent})
            doc.save(ignore_permissions=True)
            updated += 1
        else:
            frappe.get_doc({"doctype": doctype, "code": code, "description": description, "parent_code": parent,
                            "is_group": 0}).insert(ignore_permissions=True)
            created += 1
        if parent:
            parents.add(parent)
    for code in parents:
        if frappe.db.exists(doctype, code):
            frappe.db.set_value(doctype, code, "is_group", 1, update_modified=False)
    # a code loaded now may already have children from an earlier file
    return {"created": created, "updated": updated, "errors": errors}


def search(kind, text, limit=20):
    doctype = spec(kind)[0]
    frappe.has_permission(doctype, "read", throw=True)
    text = (text or "").strip().lower()
    try:
        limit = max(1, min(int(limit or 20), 200))
    except (TypeError, ValueError):
        limit = 20
    like = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return frappe.db.sql(
        f"""select name as code, description from `tab{doctype}`
        where lower(name) like %(prefix)s or lower(description) like %(any)s order by name limit {limit}""",
        {"prefix": like + "%", "any": "%" + like + "%"}, as_dict=True)
