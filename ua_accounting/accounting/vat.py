"""VAT registers API: tax liabilities (ПДВ нараховане) and tax credit (ПДВ кредит).

Documents call post_vat_entries(doc, liabilities, credits) from on_submit.
cancel_entries() in ledger.py calls cancel_vat_entries(doc) too.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting.utils import first_of_month, pick, std_columns

LIABILITY = "UA VAT Liability Entry"
CREDIT = "UA VAT Credit Entry"

FIELDS = [
    "posting_date",
    "period",
    "registrar_type",
    "registrar",
    "line_no",
    "organization",
    "counterparty",
    "contract",
    "settlement_doc_type",
    "settlement_doc",
    "vat_rate",
    "event",
    "base_amount",
    "vat_amount",
    "tax_invoice_type",
    "tax_invoice",
    "content",
]


def post_vat_entries(doc, liabilities=(), credits=()):
    _insert(LIABILITY, doc, liabilities)
    _insert(CREDIT, doc, credits)


def cancel_vat_entries(doc):
    for doctype in (LIABILITY, CREDIT):
        frappe.db.delete(doctype, {"registrar_type": doc.doctype, "registrar": doc.name})


def _insert(doctype, doc, entries):
    entries = list(entries or [])
    if not entries:
        return
    std = std_columns()
    values = []
    for idx, e in enumerate(entries, start=1):
        posting_date = pick(doc, e, "posting_date")
        organization = pick(doc, e, "organization")
        if not posting_date or not organization or not e.get("vat_rate"):
            frappe.throw(_("Рядок ПДВ {0}: потрібні дата, організація і ставка ПДВ").format(idx))
        row = {
            "posting_date": getdate(posting_date),
            "period": first_of_month(posting_date),
            "registrar_type": doc.doctype,
            "registrar": doc.name,
            "line_no": idx,
            "organization": organization,
            "counterparty": e.get("counterparty") or "",
            "contract": e.get("contract") or "",
            "settlement_doc_type": e.get("settlement_doc_type") or "",
            "settlement_doc": e.get("settlement_doc") or "",
            "vat_rate": e["vat_rate"],
            "event": e.get("event") or "Інше",
            "base_amount": flt(e.get("base_amount")),
            "vat_amount": flt(e.get("vat_amount")),
            "tax_invoice_type": e.get("tax_invoice_type") or "",
            "tax_invoice": e.get("tax_invoice") or "",
            "content": (e.get("content") or "")[:140],
        }
        values.append([row[f] for f in FIELDS] + [std[k] for k in std])
    frappe.db.bulk_insert(doctype, FIELDS + list(std), values)
