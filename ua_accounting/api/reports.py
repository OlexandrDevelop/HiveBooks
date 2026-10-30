"""Whitelisted methods of the extra accounting reports (T-443).

    run(report, filters)            -> {columns, rows, totals, ..., table}
    export_excel(report, filters)   -> {filename, content}   content = base64 of an .xlsx
    print_html(report, filters)     -> {html}

`report` is the method code (`chess_sheet`) or the route of the page (`ua-chess-sheet`).
"""

import base64

import frappe
from frappe import _

from ua_accounting.reporting.check import accounting_check
from ua_accounting.reporting.export import to_xlsx
from ua_accounting.reporting.ledger_reports import (
    account_analysis,
    account_turnover,
    chess_sheet,
    entries_report,
    general_ledger,
    journal_order,
)
from ua_accounting.reporting.more_common import Ctx, print_html as render_print
from ua_accounting.reporting.subconto_reports import osv_subconto, subconto_analysis, subconto_card

REPORTS = {
    "subconto_analysis": subconto_analysis,
    "osv_subconto": osv_subconto,
    "account_turnover": account_turnover,
    "account_analysis": account_analysis,
    "general_ledger": general_ledger,
    "journal_order": journal_order,
    "chess_sheet": chess_sheet,
    "entries_report": entries_report,
    "subconto_card": subconto_card,
    "accounting_check": accounting_check,
}
READ_DOCTYPES = ("UA Accounting Entry", "UA Account Turnover")


def _build(report, filters):
    code = (report or "").strip()
    if code.startswith("ua-"):
        code = code[3:].replace("-", "_")
    if code not in REPORTS:
        frappe.throw(_("Невідомий звіт {0}").format(report))
    for doctype in READ_DOCTYPES:
        frappe.has_permission(doctype, "read", throw=True)
    return REPORTS[code](Ctx(filters)), code


@frappe.whitelist(methods=["POST", "GET"])
def run(report, filters=None):
    return _build(report, filters)[0]


@frappe.whitelist(methods=["POST", "GET"])
def export_excel(report, filters=None):
    res, code = _build(report, filters)
    return {"filename": f"{code}.xlsx", "content": base64.b64encode(to_xlsx(res["table"])).decode()}


@frappe.whitelist(methods=["POST", "GET"])
def print_html(report, filters=None):
    return {"html": render_print(_build(report, filters)[0]["table"])}
