"""Інвентарна картка обліку основних засобів (ОЗ-6): cost, wear and parameters on a date."""

import frappe
from frappe.utils import flt, getdate

from ua_accounting.accounting import assets
from ua_accounting.accounting.utils import title_of


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"fieldname": "asset", "label": "Основний засіб", "fieldtype": "Link", "options": "UA Fixed Asset", "width": 200},
        {"fieldname": "inventory_no", "label": "Інвентарний номер", "fieldtype": "Data", "width": 130},
        {"fieldname": "initial_cost", "label": "Первісна вартість", "fieldtype": "Currency", "width": 130},
        {"fieldname": "accumulated_depreciation", "label": "Сума зносу", "fieldtype": "Currency", "width": 130},
        {"fieldname": "residual_value", "label": "Залишкова вартість", "fieldtype": "Currency", "width": 130},
        {"fieldname": "useful_life_months", "label": "Строк корисного використання, міс.", "fieldtype": "Int", "width": 110},
        {"fieldname": "depreciation_method", "label": "Метод амортизації", "fieldtype": "Data", "width": 220},
        {"fieldname": "commissioning_date", "label": "Дата введення в експлуатацію", "fieldtype": "Date", "width": 130},
        {"fieldname": "department", "label": "Підрозділ", "fieldtype": "Link", "options": "UA Department", "width": 150},
        {"fieldname": "responsible", "label": "Матеріально відповідальна особа", "fieldtype": "Link", "options": "UA Person", "width": 180},
    ]
    if not filters.organization:
        return columns, []
    date_to = getdate(filters.date_to) if filters.date_to else getdate()
    rows = []
    for acc in assets.acceptances(filters.organization, date_to, assets.FA, filters.asset or None):
        inventory_no = frappe.db.get_value(assets.FA, acc.asset, "inventory_no")
        cost = assets.cost_at(acc, date_to)
        wear = assets.wear_at(acc, date_to)
        rows.append(
            {
                "asset": acc.asset,
                "inventory_no": inventory_no,
                "initial_cost": cost,
                "accumulated_depreciation": wear,
                "residual_value": flt(cost - wear, 2),
                "useful_life_months": acc.useful_life_months,
                "depreciation_method": acc.depreciation_method,
                "commissioning_date": str(acc.posting_date),
                "department": assets.card_value_at(assets.FA, acc.asset, "department", date_to, filters.organization),
                "responsible": assets.card_value_at(assets.FA, acc.asset, "responsible", date_to, filters.organization),
            }
        )
    return columns, rows
