"""Розрахунки за тару: скільки нашої тари тримає контрагент (плюс) і скільки чужої тари тримаємо ми (мінус)."""

import frappe

from ua_accounting.accounting import packaging


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"fieldname": "counterparty", "label": "Контрагент", "fieldtype": "Link", "options": "UA Counterparty", "width": 240},
        {"fieldname": "item", "label": "Тара", "fieldtype": "Link", "options": "UA Item", "width": 240},
        {"fieldname": "quantity", "label": "Кількість", "fieldtype": "Float", "width": 120},
        {"fieldname": "amount", "label": "Сума застави", "fieldtype": "Currency", "width": 140},
    ]
    if not filters.organization:
        return columns, []
    frappe.has_permission("UA Packaging Return", "report", throw=True)
    return columns, packaging.balances(filters.organization, filters.counterparty)
