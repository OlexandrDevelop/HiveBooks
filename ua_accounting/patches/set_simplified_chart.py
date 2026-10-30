"""Mark the leaf accounts of the simplified chart of small enterprises. Runs once; later changes are made by hand."""

import frappe

from ua_accounting.accounting.simplified_tax import SIMPLE_CHART_ACCOUNTS


def execute():
    for code in SIMPLE_CHART_ACCOUNTS:
        if frappe.db.get_value("UA Account", code, "is_group") == 0:
            frappe.db.set_value("UA Account", code, "in_simplified_chart", 1, update_modified=False)
