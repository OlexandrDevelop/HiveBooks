"""Data exchange: import from 1C and Excel, bank statements, NBU, classifiers, files for M.E.Doc and Вчасно."""

import json

import frappe
from frappe import _
from frappe.beeone import exchange as core_exchange
from frappe.utils import cint

from ua_accounting.exchange import balances, bank, bank_formats, catalogs, classifiers, excel, nbu, onec, tax_files
from ua_accounting.exchange.common import (ExchangeError, check_organization, check_roles, file_bytes, run_logged, status_of,
                                            total, write_log)

ONEC_KINDS = ("catalogs", "balances")


def _list(value):
    return json.loads(value) if isinstance(value, str) else value


def _import(kind_log, organization, file_name, dry_run, work):
    """Runs an import; a dry run is rolled back and not logged."""

    def run():
        if dry_run:
            frappe.db.savepoint("exchange_dry")
        result = work()
        if dry_run:
            frappe.db.rollback(save_point="exchange_dry")
            result["log"] = None
            return result
        created, updated, errors = total(result["created"]), total(result["updated"]), result["errors"]
        result["log"] = write_log("Імпорт", kind_log, status_of(errors, created, updated), organization=organization,
                                  file_name=file_name, created=created, updated=updated, errors=len(errors),
                                  details={"created": result["created"], "updated": result["updated"], "errors": errors})
        return result

    return run_logged(kind_log, "Імпорт", run, organization=organization, file_name=file_name, log=not dry_run)


def _balances(organization, date_value, rows, replace, kind_log, file_name, dry_run):
    return _import(kind_log, organization, file_name, dry_run,
                   lambda: balances.post(organization, rows, date_value, replace))


def _catalogs(organization, records, kind_log, file_name, dry_run):
    return _import(kind_log, organization, file_name, dry_run, lambda: catalogs.import_catalogs(organization, records).result())


@frappe.whitelist(methods=["POST"])
def import_1c_xml(organization, kind, content, dry_run=0, replace=0, date=None, file_name=None):
    """Catalogs or opening balances from an EnterpriseData XML file of 1C BAU."""
    check_roles()
    check_organization(organization)
    if kind not in ONEC_KINDS:
        frappe.throw(_("Невідомий вид імпорту «{0}»: catalogs або balances").format(kind))
    data = file_bytes(content)
    dry_run, replace = cint(dry_run), cint(replace)
    root = onec.parse(data)
    if kind == "catalogs":
        return _catalogs(organization, onec.catalogs(root), "catalogs_1c", file_name, dry_run)
    file_date, rows = onec.balances(root)
    given = onec.parse_date(date) if date else None
    if date and not given:
        frappe.throw(_("Дату «{0}» не розпізнано. Вкажіть її як РРРР-ММ-ДД").format(date))
    return _balances(organization, given or file_date, rows, replace, "balances_1c", file_name, dry_run)


@frappe.whitelist(methods=["POST"])
def import_excel(organization, kind, content, dry_run=0, replace=0, date=None, file_name=None):
    """Counterparties, items, warehouses or opening balances from an Excel template."""
    check_roles()
    check_organization(organization)
    if kind not in excel.HEADERS:
        frappe.throw(_("Невідомий вид імпорту «{0}»").format(kind))
    data = file_bytes(content)
    dry_run, replace = cint(dry_run), cint(replace)
    rows = excel.read(data, kind)
    if kind == "balances":
        file_date, items = excel.balances(rows)
        given = onec.parse_date(date) if date else None
        if date and not given:
            frappe.throw(_("Дату «{0}» не розпізнано. Вкажіть її як РРРР-ММ-ДД").format(date))
        return _balances(organization, given or file_date, items, replace, "balances_excel", file_name, dry_run)
    records = getattr(excel, kind)(rows)
    return _catalogs(organization, {kind: records}, "catalogs_excel", file_name, dry_run)


@frappe.whitelist(methods=["GET", "POST"])
def get_template(kind):
    check_roles()
    return excel.template(kind)


# ------------------------------------------------------------------ bank
@frappe.whitelist(methods=["POST"])
def import_bank_statement(bank_account, format, content, file_name=None):
    check_roles()
    data = file_bytes(content)
    organization = frappe.db.get_value("UA Bank Account", bank_account, "organization")

    def run():
        result = bank.import_statement(bank_account, format, data)
        result["log"] = write_log("Імпорт", "bank_statement", "Успішно", organization=result["organization"], file_name=file_name,
                                  created=result["new"], details={k: result[k] for k in ("statement", "lines", "new", "duplicates",
                                                                                         "matched", "unmatched", "warnings")})
        return result

    return run_logged("bank_statement", "Імпорт", run, organization=organization, file_name=file_name)


@frappe.whitelist(methods=["POST"])
def post_statement(name):
    check_roles()
    result = bank.post_statement(name)
    result.pop("organization", None)
    return result


@frappe.whitelist(methods=["POST"])
def export_payment_orders(names, format):
    check_roles()
    names = _list(names)

    def run():
        result = bank.export_orders(names, format)
        result["log"] = write_log("Експорт", "payment_orders", "Успішно", organization=result["organization"],
                                  file_name=result["filename"], created=result["count"],
                                  details={"names": names, "format": format, "total": result["total"]})
        return result

    return run_logged("payment_orders", "Експорт", run, file_name=None)


# ------------------------------------------------------------------ NBU
@frappe.whitelist(methods=["POST"])
def load_nbu_rates(date_from=None, date_to=None):
    check_roles()
    return nbu.load_rates_logged(date_from, date_to)


@frappe.whitelist(methods=["POST"])
def load_banks():
    check_roles()
    core_exchange.check_enabled(core_exchange.rule_for("banks"))
    try:
        result = nbu.load_banks()
    except ExchangeError as e:
        write_log("Імпорт", "banks", "Помилка", errors=1, details={"errors": [str(e)]})
        return {"created": 0, "updated": 0, "deactivated": 0, "errors": [str(e)]}
    write_log("Імпорт", "banks", status_of(result["errors"], result["created"], result["updated"]), created=result["created"],
              updated=result["updated"], errors=len(result["errors"]), details=result)
    return result


@frappe.whitelist(methods=["GET", "POST"])
def get_bank(mfo):
    frappe.has_permission("UA Bank", "read", throw=True)
    return nbu.bank_dict(str(mfo or "").strip())


@frappe.whitelist(methods=["GET", "POST"])
def bank_by_iban(iban):
    frappe.has_permission("UA Bank", "read", throw=True)
    return nbu.bank_by_iban(iban)


@frappe.whitelist(methods=["GET", "POST"])
def validate_iban(iban):
    frappe.has_permission("UA Bank", "read", throw=True)
    return nbu.validate_iban(iban)


# ------------------------------------------------------------------ classifiers
@frappe.whitelist(methods=["POST"])
def load_classifier(kind, content):
    check_roles()
    classifiers.spec(kind)
    data = file_bytes(content)

    def run():
        result = classifiers.load(kind, data)
        result["log"] = write_log("Імпорт", "classifier", status_of(result["errors"], result["created"], result["updated"]),
                                  file_name=kind, created=result["created"], updated=result["updated"],
                                  errors=len(result["errors"]), details=result)
        return result

    return run_logged("classifier", "Імпорт", run, file_name=kind)


@frappe.whitelist(methods=["GET", "POST"])
def search_classifier(kind, text, limit=20):
    return classifiers.search(kind, text, limit)


# ------------------------------------------------------------------ M.E.Doc / Вчасно
@frappe.whitelist(methods=["POST"])
def export_tax_invoices(items, target):
    check_roles()
    items = _list(items)

    def run():
        result = tax_files.export(items, target)
        result["log"] = write_log("Експорт", "tax_invoices", "Успішно", organization=result["organization"], file_name=target,
                                  created=result["count"], details={"target": target, "items": items})
        return result

    return run_logged("tax_invoices", "Експорт", run, file_name=target)
