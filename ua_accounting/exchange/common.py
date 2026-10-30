"""Shared parts of the data exchange: rights, file decoding, the exchange log."""

import base64
import binascii
import json
import re

import frappe
from frappe import _
from frappe.beeone import exchange as core_exchange
from frappe.utils import now_datetime

ROLES = ("UA Accountant", "UA Accounting Manager", "UA Chief Accountant")
MAX_FILE_BYTES = 20 * 1024 * 1024
LOG = "UA Exchange Log"

RESULT_KEYS = ("created", "updated")


class ExchangeError(frappe.ValidationError):
    """A call that must change nothing. `errors` are shown to the user and saved in the log."""

    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = errors or []


def check_roles():
    if not set(frappe.get_roles()) & set(ROLES):
        frappe.throw(_("Недостатньо прав для обміну даними"), frappe.PermissionError)


def check_organization(organization):
    """The user may work with this organization (rights by organization, T-445)."""
    if not organization:
        frappe.throw(_("Вкажіть організацію"))
    frappe.get_doc("UA Organization", organization).check_permission("read")


def file_bytes(content):
    """Bytes of a file that travels as a base64 string."""
    if isinstance(content, bytes):
        data = content
    else:
        try:
            data = base64.b64decode(content or "", validate=False)
        except (binascii.Error, ValueError):
            frappe.throw(_("Файл передано некоректно"))
    if len(data) > MAX_FILE_BYTES:
        frappe.throw(_("Файл завеликий (понад 20 МБ)"))
    return data


def decode_text(data, encodings=("utf-8-sig", "windows-1251")):
    for enc in encodings:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    frappe.throw(_("Не вдалося прочитати файл: невідоме кодування"))


def flag(value):
    return str(value if value is not None else "").strip().lower() in ("true", "1", "так", "yes", "+", "x", "є")


def digits_only(value):
    return bool(re.fullmatch(r"\d+", value or ""))


def to_int(value):
    return int(value) if value not in (None, "") else 0


STATUS_EN = {"Успішно": "Success", "З помилками": "Partial", "Помилка": "Failed"}
DIRECTION_EN = {"Імпорт": "Import", "Експорт": "Export"}


UA_KINDS = ("catalogs_1c", "balances_1c", "catalogs_excel", "balances_excel", "bank_statement", "payment_orders", "nbu_rates",
            "banks", "classifier", "tax_invoices")


def write_log(direction, kind, status, organization=None, file_name=None, created=0, updated=0, errors=0, details=None):
    """One row in the journal of the core framework (System Manager) and one in the accountants' journal."""
    core_exchange.write_log(kind, DIRECTION_EN[direction], STATUS_EN[status], reference=organization, file_name=file_name,
                            created=created, updated=updated, errors=errors, details=details,
                            rule=frappe.db.get_value(core_exchange.RULE, {"handler": kind}))
    return ua_row(direction, kind, status, organization, file_name, created, updated, errors, details)


def ua_row(direction, kind, status, organization=None, file_name=None, created=0, updated=0, errors=0, details=None):
    if organization and not frappe.db.exists("UA Organization", organization):
        organization = None
    doc = frappe.new_doc(LOG)
    doc.update({
        "direction": direction, "kind": kind, "status": status, "organization": organization, "file_name": file_name,
        "user": frappe.session.user, "timestamp": now_datetime(), "created": created, "updated": updated, "errors": errors,
        "details": json.dumps(details, ensure_ascii=False, default=str) if details is not None else None,
    })
    doc.flags.exchange_log = True
    doc.insert(ignore_permissions=True)
    return doc.name


def total(counts):
    return sum((counts or {}).values())


def status_of(errors, created=0, updated=0):
    if not errors:
        return "Успішно"
    return "З помилками" if (created or updated) else "Помилка"


def run_logged(kind, direction, fn, organization=None, file_name=None, log=True):
    """Runs `fn` through the core framework: a disabled rule of the kind stops it; when `fn` raises, the changes are rolled
    back once and a row `Помилка` is written to both journals (the core calls `mirror_log`)."""
    return core_exchange.run_logged(kind, DIRECTION_EN[direction], fn, reference=organization, file_name=file_name, log=log)


def mirror_log(doc):
    """Hook `beeone_exchange_logged`: a run of the core framework also goes to the journal of the accountants."""
    if doc.handler not in UA_KINDS:
        return
    status = {v: k for k, v in STATUS_EN.items()}[doc.status]
    direction = {v: k for k, v in DIRECTION_EN.items()}[doc.direction]
    ua_row(direction, doc.handler, status, doc.reference, doc.file_name, doc.created or 0, doc.updated or 0, doc.errors or 0,
           json.loads(doc.details) if doc.details else None)
