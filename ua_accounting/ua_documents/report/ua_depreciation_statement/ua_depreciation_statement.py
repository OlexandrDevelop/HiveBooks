"""Відомість амортизації: wear of every asset at the start and the end of the period."""

import frappe
from frappe.utils import add_days, flt, getdate

from ua_accounting.accounting import assets


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"fieldname": "asset", "label": "Актив", "fieldtype": "Data", "width": 200},
        {"fieldname": "initial_cost", "label": "Первісна вартість", "fieldtype": "Currency", "width": 130},
        {"fieldname": "accumulated_opening", "label": "Знос на початок", "fieldtype": "Currency", "width": 130},
        {"fieldname": "depreciation", "label": "Нараховано за період", "fieldtype": "Currency", "width": 130},
        {"fieldname": "accumulated_closing", "label": "Знос на кінець", "fieldtype": "Currency", "width": 130},
        {"fieldname": "residual_closing", "label": "Залишкова вартість на кінець", "fieldtype": "Currency", "width": 150},
        {"fieldname": "tax_depreciation", "label": "Податкова амортизація", "fieldtype": "Currency", "width": 130},
    ]
    if not (filters.organization and filters.date_from and filters.date_to):
        return columns, []
    date_from, date_to = getdate(filters.date_from), getdate(filters.date_to)
    before = add_days(date_from, -1)
    rows = []
    for acc in assets.acceptances(filters.organization, date_to):
        cost = assets.cost_at(acc, date_to)
        opening = assets.wear_at(acc, before)
        closing = assets.wear_at(acc, date_to)
        amount, tax = frappe.db.sql(
            """select coalesce(sum(l.amount), 0), coalesce(sum(l.tax_amount), 0)
            from `tabUA Asset Depreciation Line` l join `tabUA Asset Depreciation` p on p.name = l.parent
            where p.docstatus = 1 and l.parenttype = 'UA Asset Depreciation' and p.organization = %s
            and l.asset_type = %s and l.asset = %s and p.posting_date between %s and %s""",
            (filters.organization, acc.asset_type, acc.asset, date_from, date_to),
        )[0]
        if not (opening or closing or amount):
            continue
        rows.append(
            {
                "asset": acc.asset,
                "initial_cost": cost,
                "accumulated_opening": opening,
                "depreciation": flt(amount, 2),
                "accumulated_closing": closing,
                "residual_closing": flt(cost - closing, 2),
                "tax_depreciation": flt(tax, 2),
            }
        )
    return columns, rows
