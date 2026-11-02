"""Register UA Subconto Type as a chart of characteristic types; fill value types and mark seeded kinds predefined."""

import frappe

from ua_accounting.setup import seed


def execute():
    seed.setup_subconto_characteristic_chart()
    seeded = {row[0] for row in seed._read("subconto_types.json")}
    for name in frappe.get_all("UA Subconto Type", pluck="name"):
        doc = frappe.get_doc("UA Subconto Type", name)
        doc.predefined = 1 if name in seeded else doc.predefined
        doc.flags.ignore_permissions = True
        doc.flags.ignore_version = True
        doc.save()
