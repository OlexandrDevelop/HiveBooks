"""Відомість по товарах на складах: opening, receipts, expense and closing for a period."""

import frappe
from frappe.utils import add_days, flt, getdate

from ua_accounting.accounting.stock import stock_movements


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"fieldname": "item", "label": "Номенклатура", "fieldtype": "Link", "options": "UA Item", "width": 220},
        {"fieldname": "warehouse", "label": "Склад", "fieldtype": "Link", "options": "UA Warehouse", "width": 180},
    ]
    for key, label in (("opening", "Початковий залишок"), ("receipt", "Надходження"),
                       ("expense", "Видаток"), ("closing", "Кінцевий залишок")):
        columns.append({"fieldname": f"{key}_qty", "label": f"{label}, кількість", "fieldtype": "Float", "width": 120})
        columns.append({"fieldname": f"{key}_amount", "label": f"{label}, сума", "fieldtype": "Currency", "width": 130})
    if not (filters.organization and filters.date_from and filters.date_to):
        return columns, []
    args = {"organization": filters.organization, "warehouse": filters.warehouse}
    before = stock_movements(date_to=add_days(getdate(filters.date_from), -1), **args)
    during = stock_movements(date_from=filters.date_from, date_to=filters.date_to, **args)
    rows = []
    for key in sorted(set(before) | set(during)):
        b = before.get(key, {"dr": [0, 0], "cr": [0, 0]})
        d = during.get(key, {"dr": [0, 0], "cr": [0, 0]})
        row = {
            "item": key[0], "warehouse": key[1],
            "opening_qty": flt(b["dr"][0] - b["cr"][0], 3), "opening_amount": flt(b["dr"][1] - b["cr"][1], 2),
            "receipt_qty": flt(d["dr"][0], 3), "receipt_amount": flt(d["dr"][1], 2),
            "expense_qty": flt(d["cr"][0], 3), "expense_amount": flt(d["cr"][1], 2),
        }
        row["closing_qty"] = flt(row["opening_qty"] + row["receipt_qty"] - row["expense_qty"], 3)
        row["closing_amount"] = flt(row["opening_amount"] + row["receipt_amount"] - row["expense_amount"], 2)
        if any(row[k] for k in row if k not in ("item", "warehouse")):
            rows.append(row)
    return columns, rows
