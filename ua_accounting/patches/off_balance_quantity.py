"""Quantity accounting on the off-balance accounts of tolling (022) and commission (024)."""

import frappe


def execute():
    for code in ("022", "023", "024"):
        if frappe.db.exists("UA Account", code):
            frappe.db.set_value("UA Account", code, "quantity_accounting", 1, update_modified=False)
