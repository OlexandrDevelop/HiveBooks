"""Додаток 4ДФ: income, ПДФО, військовий збір and ЄСВ of each person for a quarter."""

import frappe

from ua_accounting.reporting import payroll


def execute(filters=None):
    filters = frappe._dict(filters or {})
    money = {"fieldtype": "Currency", "width": 130}
    columns = [
        {"fieldname": "ipn", "label": "ІПН", "fieldtype": "Data", "width": 110},
        {"fieldname": "employee", "label": "Співробітник", "fieldtype": "Link", "options": "UA Employee", "width": 200},
        {"fieldname": "income_accrued", "label": "Нараховано доходу", **money},
        {"fieldname": "income_paid", "label": "Виплачено доходу", **money},
        {"fieldname": "pdfo_accrued", "label": "ПДФО нараховано", **money},
        {"fieldname": "pdfo_withheld", "label": "ПДФО утримано", **money},
        {"fieldname": "military_levy", "label": "Військовий збір", **money},
        {"fieldname": "esv_base", "label": "База ЄСВ", **money},
        {"fieldname": "esv", "label": "ЄСВ", **money},
        {"fieldname": "income_sign", "label": "Ознака доходу", "fieldtype": "Data", "width": 90},
        {"fieldname": "hire_date", "label": "Дата прийняття", "fieldtype": "Data", "width": 110},
        {"fieldname": "dismissal_date", "label": "Дата звільнення", "fieldtype": "Data", "width": 110},
    ]
    if not (filters.organization and filters.year and filters.quarter):
        return columns, []
    payroll.check_access(filters.organization)
    return columns, payroll.form_4df_rows(filters.organization, filters.year, filters.quarter)
