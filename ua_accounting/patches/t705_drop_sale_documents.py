"""T-705: there is no sale document. UA Sales Invoice, UA Service Act and UA Sales Return are events of the Invoice.

The DocTypes, their documents, print forms and sequence entries are removed. The sales of a site are made again
(demo data is loaded again); nothing is converted.
"""

import frappe

DROPPED = ("UA Sales Invoice", "UA Service Act", "UA Sales Return")


def execute():
    for doctype in DROPPED:
        frappe.db.delete("Sequence Entry", {"document_type": doctype})
        for register in ("UA Accounting Entry", "UA VAT Liability Entry", "UA VAT Credit Entry", "UA Tax Ledger Entry"):
            frappe.db.delete(register, {"registrar_type": doctype})
        frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True, delete_permanently=True)
    if frappe.db.exists("Print Format", "UA Податкова накладна"):
        frappe.delete_doc("Print Format", "UA Податкова накладна", force=True, ignore_permissions=True)
    if frappe.db.exists("Sequence", "UA Stock Cost"):
        frappe.db.delete("Sequence Document", {"parent": "UA Stock Cost", "document_type": ("in", DROPPED)})
        if not frappe.db.exists("Sequence Document", {"parent": "UA Stock Cost", "document_type": "UA Payment Invoice"}):
            sequence = frappe.get_doc("Sequence", "UA Stock Cost")
            sequence.append("documents", {"document_type": "UA Payment Invoice"})
            sequence.save(ignore_permissions=True)
