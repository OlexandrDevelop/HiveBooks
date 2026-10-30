"""Prices of items by price type (Типи цін, Встановлення цін номенклатури).

The price is the one registered by the last submitted `UA Price Setting` with a date
up to the given day. Of two settings of one day the later one wins.
"""

import frappe
from frappe import _
from frappe.utils import flt


def price_of(item, price_type, date):
    """Price of an item or None. No permission check: documents call it on the server."""
    rows = frappe.db.sql(
        """select row.price from `tabUA Price Row` row
        join `tabUA Price Setting` doc on doc.name = row.parent
        where doc.docstatus = 1 and doc.price_type = %s and doc.posting_date <= %s and row.item = %s
        order by doc.posting_date desc, doc.creation desc, row.idx desc limit 1""",
        (price_type, date, item),
    )
    return flt(rows[0][0], 2) if rows else None


@frappe.whitelist()
def get_price(item, price_type, date):
    """Price of the item in the price type on the date, or null."""
    frappe.has_permission("UA Price Setting", "read", throw=True)
    return price_of(item, price_type, date)
