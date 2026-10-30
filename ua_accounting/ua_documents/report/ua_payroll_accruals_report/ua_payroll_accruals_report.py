"""Звіт по нарахуваннях: accrued, taxes, net, paid and the rest to pay for each employee."""

import frappe

from ua_accounting.reporting import payroll


def execute(filters=None):
    filters = frappe._dict(filters or {})
    money = {"fieldtype": "Currency", "width": 130}
    columns = [
        {"fieldname": "employee", "label": "Співробітник", "fieldtype": "Link", "options": "UA Employee", "width": 220},
        {"fieldname": "accrued", "label": "Нараховано", **money},
        {"fieldname": "pdfo", "label": "ПДФО", **money},
        {"fieldname": "military_levy", "label": "Військовий збір", **money},
        {"fieldname": "esv", "label": "ЄСВ", **money},
        {"fieldname": "net", "label": "До виплати", **money},
        {"fieldname": "paid", "label": "Виплачено", **money},
        {"fieldname": "to_pay", "label": "Залишок до виплати", **money},
    ]
    if not (filters.organization and filters.date_from and filters.date_to):
        return columns, []
    payroll.check_access(filters.organization)
    return columns, payroll.accrual_rows(filters.organization, filters.date_from, filters.date_to)
