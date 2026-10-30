"""Залишки товарів: quantity and cost of stock by item and warehouse on a date."""

import frappe
from frappe.utils import flt, today

from ua_accounting.accounting.stock import stock_movements


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"fieldname": "item", "label": "Номенклатура", "fieldtype": "Link", "options": "UA Item", "width": 240},
        {"fieldname": "warehouse", "label": "Склад", "fieldtype": "Link", "options": "UA Warehouse", "width": 200},
        {"fieldname": "quantity", "label": "Кількість", "fieldtype": "Float", "width": 120},
        {"fieldname": "amount", "label": "Сума", "fieldtype": "Currency", "width": 140},
    ]
    if not filters.organization:
        return columns, []
    moves = stock_movements(
        filters.organization, date_to=filters.date or today(), warehouse=filters.warehouse, item=filters.item
    )
    rows = []
    for (item, warehouse), m in sorted(moves.items()):
        qty = flt(m["dr"][0] - m["cr"][0], 3)
        amount = flt(m["dr"][1] - m["cr"][1], 2)
        if qty or amount:
            rows.append({"item": item, "warehouse": warehouse, "quantity": qty, "amount": amount})
    return columns, rows
