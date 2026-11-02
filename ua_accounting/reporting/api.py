"""Whitelisted methods of the reports.

Browser calls:
    run(report, filters, variant)         -> table model
    export_xlsx(report, filters, variant) -> Excel file (GET download)
    export_pdf(report, filters, variant)  -> PDF file (GET download)
    A variant (name or title of a saved variant of the user, see frappe.beeone.api.report_variants) sets the
    filters, the grouping, the hidden columns and the conditional formatting; the screen and the files use the same table.
    account_info(account)           -> flags and subconto of an account (for the form)
    subconto_types()                -> subconto types (for the "any subconto" filter)

A new report: write build(raw_filters) -> table model and add it to REPORTS.
"""

import frappe
from frappe import _
from frappe.beeone import report_export, report_variants

from ua_accounting.reporting.chart import Chart
from ua_accounting.reporting.export import to_xlsx
from ua_accounting.reporting.titles import Titles

REPORTS = {
    "osv": "ua_accounting.reporting.osv.build",
    "osv_account": "ua_accounting.reporting.osv_account.build",
    "account_card": "ua_accounting.reporting.account_card.build",
    "tax_invoice_register": "ua_accounting.reporting.tax_register.build",
    "tax_differences": "ua_accounting.reporting.tax_differences.build",
    "regulated_reports": "ua_accounting.reporting.regulated_reports.build",
}
READ_DOCTYPES = ("UA Accounting Entry", "UA Account Turnover")


def _build(report, filters, variant=None):
    if report not in REPORTS:
        frappe.throw(_("Невідомий звіт {0}").format(report))
    for doctype in READ_DOCTYPES:
        frappe.has_permission(doctype, "read", throw=True)
    if not variant:
        return frappe.get_attr(REPORTS[report])(filters)
    saved = report_variants.get_variant(report, title=variant, name=variant)
    if not saved:
        frappe.throw(_("Невідомий варіант {0}").format(variant))
    settings = saved["settings"]
    given = frappe.parse_json(filters) if isinstance(filters, str) else dict(filters or {})
    given.setdefault("group_by", settings["group_by"])
    table = frappe.get_attr(REPORTS[report])({**settings["filters"], **{k: v for k, v in given.items() if v not in (None, "")}})
    return report_variants.apply_to_table(table, settings)


@frappe.whitelist()
def run(report, filters=None, variant=None):
    return _build(report, filters, variant)


@frappe.whitelist()
def export_pdf(report, filters=None, variant=None):
    table = _build(report, filters, variant)
    frappe.response["filename"] = f"{report}.pdf"
    frappe.response["filecontent"] = report_export.to_pdf(table)
    frappe.response["type"] = "binary"


@frappe.whitelist()
def export_xlsx(report, filters=None, variant=None):
    table = _build(report, filters, variant)
    frappe.response["filename"] = f"{report}.xlsx"
    frappe.response["filecontent"] = to_xlsx(table)
    frappe.response["type"] = "binary"


@frappe.whitelist()
def account_info(account):
    frappe.has_permission("UA Account", "read", throw=True)
    chart = Chart()
    acc = chart.get(account)
    leaves = chart.expand([account])
    subconto = []
    seen = set()
    for leaf in leaves:
        for s in chart.get(leaf).subs:
            if s.subconto_type not in seen:
                seen.add(s.subconto_type)
                subconto.append(
                    {
                        "type": s.subconto_type,
                        "title": chart.type_title(s.subconto_type),
                        "turnover_only": s.turnover_only,
                    }
                )
    return {
        "name": acc.name,
        "label": chart.label(account),
        "is_group": acc.is_group,
        "off_balance": acc.off_balance,
        "quantity_accounting": any(chart.get(a).quantity_accounting for a in leaves),
        "currency_accounting": any(chart.get(a).currency_accounting for a in leaves),
        "subconto": subconto,
    }


@frappe.whitelist()
def subconto_types():
    frappe.has_permission("UA Subconto Type", "read", throw=True)
    return frappe.get_all(
        "UA Subconto Type",
        fields=["name", "subconto_name as title", "reference_doctype", "is_dynamic"],
        order_by="subconto_name asc",
        limit_page_length=0,
    )


@frappe.whitelist()
def link_titles(items):
    """Titles for the chips of the filter form. Key: doctype + newline + name."""
    titles = Titles()
    out = {}
    for doctype, name in frappe.parse_json(items) or []:
        if not (frappe.db.exists("DocType", doctype) and frappe.has_permission(doctype, "read")):
            continue
        if not frappe.db.exists(doctype, name):
            continue
        out[f"{doctype}\n{name}"] = titles.get(doctype, name)
    return out
