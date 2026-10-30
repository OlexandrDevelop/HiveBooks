"""Розрахунковий листок: accrued, withheld, employer ЄСВ, to pay and paid for one employee and month."""

import frappe

from ua_accounting.reporting import payroll


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"fieldname": "section", "label": "Розділ", "fieldtype": "Data", "width": 220},
        {"fieldname": "item", "label": "Стаття", "fieldtype": "Data", "width": 220},
        {"fieldname": "amount", "label": "Сума, грн", "fieldtype": "Currency", "width": 140},
    ]
    if not (filters.organization and filters.employee and filters.month_start):
        return columns, []
    payroll.check_access(filters.organization)
    org = frappe.db.get_value("UA Employee", filters.employee, "organization")
    if org != filters.organization:
        frappe.throw(frappe._("Співробітник працює в іншій організації"))
    return columns, payroll.payslip_rows(filters.organization, filters.employee, filters.month_start)
