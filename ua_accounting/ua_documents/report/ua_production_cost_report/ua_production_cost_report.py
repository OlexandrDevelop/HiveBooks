"""Звіт про собівартість випуску: quantity, planned and actual cost of the output by product."""

import frappe
from frappe.utils import flt


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"fieldname": "item", "label": "Продукція", "fieldtype": "Link", "options": "UA Item", "width": 240},
        {"fieldname": "quantity", "label": "Кількість", "fieldtype": "Float", "width": 110},
        {"fieldname": "planned_cost", "label": "Планова собівартість", "fieldtype": "Currency", "width": 160},
        {"fieldname": "actual_cost", "label": "Фактична собівартість", "fieldtype": "Currency", "width": 160},
        {"fieldname": "deviation", "label": "Відхилення", "fieldtype": "Currency", "width": 140},
    ]
    if not filters.organization or not filters.date_from or not filters.date_to:
        return columns, []
    frappe.has_permission("UA Production Report", "report", throw=True)
    values = (filters.organization, filters.date_from, filters.date_to)
    produced = frappe.db.sql(
        """select subconto_dr1 as item, sum(quantity_dr) as quantity, sum(amount) as planned_cost
        from `tabUA Accounting Entry`
        where registrar_type = 'UA Production Report' and organization = %s and posting_date between %s and %s
        and account_dr in ('26', '25') and account_cr = '23' group by subconto_dr1""",
        values,
        as_dict=True,
    )
    closed = frappe.db.sql(
        """select l.item, sum(l.actual_cost) as actual_cost, sum(l.deviation) as deviation
        from `tabUA Production Closing Line` l join `tabUA Production Month Closing` c on c.name = l.parent
        where c.docstatus = 1 and c.organization = %s and c.posting_date between %s and %s group by l.item""",
        values,
        as_dict=True,
    )
    closing = {r.item: r for r in closed}
    rows = []
    for r in sorted(produced, key=lambda x: x.item):
        c = closing.get(r.item)
        rows.append(
            {
                "item": r.item,
                "quantity": flt(r.quantity, 3),
                "planned_cost": flt(r.planned_cost, 2),
                "actual_cost": flt(c.actual_cost, 2) if c else 0.0,
                "deviation": flt(c.deviation, 2) if c else 0.0,
            }
        )
    return columns, rows
