"""Fill the sequence `UA Stock Cost` from the documents posted before it existed."""

import frappe


def execute():
    from frappe.beeone.sequences import rebuild_entries

    if frappe.db.exists("Sequence", "UA Stock Cost"):
        rebuild_entries("UA Stock Cost")
