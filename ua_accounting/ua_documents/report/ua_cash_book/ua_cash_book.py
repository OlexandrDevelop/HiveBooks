"""Касова книга: documents and daily sheets for one cash desk."""

import frappe
from frappe.utils import flt, getdate

from ua_accounting.accounting.bank_cash import desk_balance


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"fieldname": "posting_date", "label": "Дата", "fieldtype": "Date", "width": 110},
        {"fieldname": "document", "label": "Документ", "fieldtype": "Data", "width": 180},
        {"fieldname": "receipt", "label": "Надходження", "fieldtype": "Currency", "width": 130},
        {"fieldname": "payment", "label": "Видаток", "fieldtype": "Currency", "width": 130},
        {"fieldname": "opening", "label": "Початковий залишок", "fieldtype": "Currency", "width": 150},
        {"fieldname": "closing", "label": "Кінцевий залишок", "fieldtype": "Currency", "width": 150},
    ]
    if not (filters.organization and filters.cash_desk and filters.date_from and filters.date_to):
        return columns, []
    desk_currency = frappe.db.get_value("UA Cash Desk", filters.cash_desk, "currency")
    if desk_currency and desk_currency != "UAH":
        return columns, []
    docs = []
    for doctype, field, direction in (("UA Cash Receipt", "receipt", 1),
                                      ("UA Cash Payment", "payment", -1),
                                      ("UA Cash Disbursement", "payment", -1)):
        for row in frappe.get_all(doctype, filters={"organization": filters.organization,
                                                   "cash_desk": filters.cash_desk,
                                                   "posting_date": ("between", [filters.date_from, filters.date_to]),
                                                   "docstatus": 1},
                                  fields=["name", "posting_date", "amount" if direction == 1 else
                                          ("total_amount" if doctype == "UA Cash Disbursement" else "amount")],
                                  order_by="posting_date asc"):
            amount = flt(row.get("amount") or row.get("total_amount"))
            docs.append({"posting_date": str(row.posting_date), "document": row.name,
                         "receipt": amount if direction == 1 else 0,
                         "payment": amount if direction == -1 else 0})
    docs.sort(key=lambda row: (row["posting_date"], row["document"]))
    rows = []
    ledger_days = frappe.db.sql_list(
        """select distinct posting_date from `tabUA Accounting Entry`
        where organization=%s and posting_date between %s and %s and (account_dr='301' or account_cr='301')""",
        (filters.organization, filters.date_from, filters.date_to))
    for day in sorted({row["posting_date"] for row in docs} | {str(d) for d in ledger_days}):
        # the ledger is the source: entries without a document of the desk (posted without a desk) are shown as one row
        opening = desk_balance(filters.organization, filters.cash_desk, day, before=True)
        if not any(row["posting_date"] == day for row in docs) and \
                desk_balance(filters.organization, filters.cash_desk, day) == opening:
            continue  # movements of other desks only
        today = [row for row in docs if row["posting_date"] == day]
        received = flt(sum(row["receipt"] for row in today), 2)
        paid = flt(sum(row["payment"] for row in today), 2)
        closing = desk_balance(filters.organization, filters.cash_desk, day)
        rest = flt(closing - opening - received + paid, 2)
        if rest:
            today.append({"posting_date": day, "document": "Інші проводки",
                          "receipt": rest if rest > 0 else 0, "payment": -rest if rest < 0 else 0})
            received = flt(received + max(rest, 0), 2)
            paid = flt(paid + max(-rest, 0), 2)
        rows.extend(today)
        rows.append({"row_type": "day_total", "posting_date": day, "opening": opening,
                     "receipt": received, "payment": paid,
                     "receipts": received, "payments": paid, "closing": closing})
    return columns, rows
