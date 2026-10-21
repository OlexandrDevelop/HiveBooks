import frappe
from frappe.model.document import Document


class UAAccountingEntry(Document):
    """Register row. Written only by ua_accounting.accounting.ledger."""

    pass


def on_doctype_update():
    table = "UA Accounting Entry"
    frappe.db.add_index(table, ["registrar_type", "registrar"], "idx_ua_ae_registrar")
    frappe.db.add_index(
        table, ["organization", "account_dr", "posting_date"], "idx_ua_ae_org_dr_date"
    )
    frappe.db.add_index(
        table, ["organization", "account_cr", "posting_date"], "idx_ua_ae_org_cr_date"
    )
    # reports without an organization filter read one account by date
    frappe.db.add_index(table, ["account_dr", "posting_date"], "idx_ua_ae_dr_date")
    frappe.db.add_index(table, ["account_cr", "posting_date"], "idx_ua_ae_cr_date")
    frappe.db.add_index(table, ["posting_date"], "idx_ua_ae_date")
    frappe.db.add_index(table, ["period", "organization"], "idx_ua_ae_period_org")
    for side in ("dr", "cr"):
        for i in (1, 2, 3):
            col = f"subconto_{side}{i}"
            frappe.db.add_index(table, [col], f"idx_ua_ae_{col}")
