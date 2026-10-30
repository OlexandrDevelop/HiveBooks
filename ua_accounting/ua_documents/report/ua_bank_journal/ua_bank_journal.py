"""Journal of bank statements by account and date."""

import frappe
from frappe.utils import flt


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"fieldname": "posting_date", "label": "Дата", "fieldtype": "Date", "width": 110},
        {"fieldname": "document", "label": "Виписка", "fieldtype": "Data", "width": 180},
        {"fieldname": "direction", "label": "Напрям", "fieldtype": "Data", "width": 140},
        {"fieldname": "amount", "label": "Сума", "fieldtype": "Currency", "width": 140},
    ]
    if not (filters.organization and filters.bank_account and filters.date_from and filters.date_to):
        return columns, []
    rows = []
    names = frappe.get_all("UA Bank Statement", filters={"organization": filters.organization,
                                                          "bank_account": filters.bank_account,
                                                          "posting_date": ("between", [filters.date_from, filters.date_to]),
                                                          "docstatus": 1},
                           pluck="name", order_by="posting_date asc")
    for name in names:
        doc = frappe.get_doc("UA Bank Statement", name)
        for line in doc.lines:
            rows.append({"posting_date": str(doc.posting_date), "document": name,
                         "direction": line.direction, "amount": flt(line.amount)})
    return columns, rows
