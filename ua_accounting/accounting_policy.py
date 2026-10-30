"""Dated accounting policy lookup used by posting."""

import frappe


def policy_for(organization, date):
    if not organization or not date:
        return None
    rows = frappe.get_all(
        "UA Accounting Policy", filters={"organization": organization, "effective_from": ("<=", date)},
        fields=["*"], order_by="effective_from desc", limit=1,
    )
    return rows[0] if rows else None


@frappe.whitelist()
def get_policy(organization, date):
    frappe.has_permission("UA Organization", "read", organization, throw=True)
    return policy_for(organization, date)
